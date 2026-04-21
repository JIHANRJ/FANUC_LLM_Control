"""LLM + voice order controller mapped to FANUC TP order registers."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Add repo root to path for local imports.
MODULE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = MODULE_ROOT.parents[0]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from llm.robot_control_llm import RobotControlLLM
from voice import PressToTalkVoiceController

ROS2_AVAILABLE = False
FANUC_IO_AVAILABLE = False
FanucIOClient = None
fanuc_import_error: Optional[BaseException] = None

try:
    import rclpy

    ROS2_AVAILABLE = True
except ImportError as exc:
    fanuc_import_error = exc

if ROS2_AVAILABLE:
    try:
        from fanuc_io_control import FanucIOClient

        FANUC_IO_AVAILABLE = True
    except ImportError as exc:
        fanuc_import_error = exc


@dataclass(frozen=True)
class Product:
    key: str
    register: int
    description: str
    aliases: tuple[str, ...]


PRODUCTS: tuple[Product, ...] = (
    Product("nuttiess_choclae", 1, "Nuttiess Choclae", ("nutties", "nutties", "nuttiess", "nutties chocolate", "nuttiess choclae", "nutties choclate")),
    Product("nivea", 2, "NIVEA", ("nivea",)),
    Product("shampoo", 3, "Shampoo", ("shampoo", "shampoo bottle", "shampoobottle")),
    Product("appy_fizz", 4, "Appy Fizz", ("appy fizz", "appyfizz")),
    Product("cough_syrup", 5, "Cough Syrup", ("cough syrup", "coughsyrup", "syrup")),
    Product("coca_cola", 6, "Coca Cola", ("coca cola", "coke", "cocacola")),
    Product("tea_botx", 7, "Tea botx", ("tea", "tea box", "tea botx", "teabox")),
    Product("pringles", 8, "Pringles", ("pringles",)),
    Product("noodles", 9, "Noodles", ("noodles", "noodle")),
    Product("bar", 10, "Bar", ("bar", "chocolate bar")),
    Product("ponds", 11, "Ponds", ("ponds", "ponds cream")),
    Product("dove", 12, "Dove", ("dove", "dove soap")),
)

ORDER_REG_TOTAL_PARTS = 25
ORDER_REG_UNLOAD_ENABLE = 108

DO_HOME_POSITION = 2
DO_ORDER_FULFILLED = 1
DO_MASK_BUTTONS = 225
DI_ORDER_CONFIRMATION = 4
DI_ORDER_RECEIVED = 2

PRODUCT_BY_KEY = {p.key: p for p in PRODUCTS}
ALIAS_TO_KEY: dict[str, str] = {}
for product in PRODUCTS:
    ALIAS_TO_KEY[product.key] = product.key
    ALIAS_TO_KEY[product.description.lower()] = product.key
    for alias in product.aliases:
        ALIAS_TO_KEY[alias] = product.key

CURRENT_STATE = {
    "last_intent": None,
    "last_items": [],
    "last_updated": None,
}


class RegisterBackend:
    """Abstract register backend for simulation or real robot integration."""

    def write_register(self, index: int, value: int) -> bool:
        raise NotImplementedError

    def read_register(self, index: int) -> Optional[int]:
        raise NotImplementedError

    def close(self) -> None:
        """Optional backend cleanup hook."""



class SimulationRegisterBackend(RegisterBackend):
    def __init__(self) -> None:
        self._registers: dict[int, int] = {}

    def write_register(self, index: int, value: int) -> bool:
        self._registers[index] = int(value)
        return True

    def read_register(self, index: int) -> Optional[int]:
        return int(self._registers.get(index, 0))


class ExternalCommandRegisterBackend(RegisterBackend):
    """Bridge register reads/writes through shell commands.

    Use placeholders in templates:
    - write template: {index}, {value}
    - read template:  {index}
    """

    def __init__(self, write_template: str, read_template: Optional[str] = None) -> None:
        self._write_template = write_template
        self._read_template = read_template

    def write_register(self, index: int, value: int) -> bool:
        command = self._write_template.format(index=index, value=value)
        completed = subprocess.run(shlex.split(command), capture_output=True, text=True)
        if completed.returncode != 0:
            print(f"[ERROR] Register write failed for R[{index}] -> {value}: {completed.stderr.strip()}")
            return False
        return True

    def read_register(self, index: int) -> Optional[int]:
        if not self._read_template:
            return None

        command = self._read_template.format(index=index)
        completed = subprocess.run(shlex.split(command), capture_output=True, text=True)
        if completed.returncode != 0:
            print(f"[WARN] Register read failed for R[{index}]: {completed.stderr.strip()}")
            return None

        output = completed.stdout.strip()
        if not output:
            return None

        try:
            return int(float(output))
        except ValueError:
            print(f"[WARN] Could not parse register value for R[{index}]: {output!r}")
            return None


class OpcUaRegisterBackend(RegisterBackend):
    """Read/write FANUC-mapped holding registers over OPC UA."""

    def __init__(
        self,
        *,
        endpoint: str,
        namespace_index: int,
        node_template: str,
        register_offset: int,
        timeout_seconds: float,
        username: str = "",
        password: str = "",
    ) -> None:
        try:
            from opcua import Client
        except ImportError as exc:
            raise RuntimeError(
                "OPC UA client dependency is missing. Install with: "
                "python -m pip install opcua"
            ) from exc

        self._namespace_index = int(namespace_index)
        self._node_template = node_template
        self._register_offset = int(register_offset)
        self._node_cache: dict[int, object] = {}
        self._client = Client(endpoint, timeout=float(timeout_seconds))

        if username.strip():
            self._client.set_user(username.strip())
            self._client.set_password(password)

        self._client.connect()

    def _address_for_register(self, register_index: int) -> int:
        return self._register_offset + int(register_index)

    def _node_id_for_address(self, address: int) -> str:
        return self._node_template.format(ns=self._namespace_index, address=address)

    def _node_for_register(self, register_index: int):
        cache_key = int(register_index)
        if cache_key in self._node_cache:
            return self._node_cache[cache_key]

        address = self._address_for_register(register_index)
        node_id = self._node_id_for_address(address)
        node = self._client.get_node(node_id)
        self._node_cache[cache_key] = node
        return node

    def write_register(self, index: int, value: int) -> bool:
        try:
            node = self._node_for_register(index)
            node.set_value(int(value))
            return True
        except Exception as exc:
            print(f"[ERROR] OPC UA write failed for R[{index}]={value}: {exc}")
            return False

    def read_register(self, index: int) -> Optional[int]:
        try:
            node = self._node_for_register(index)
            value = node.get_value()
            return int(float(value))
        except Exception as exc:
            print(f"[WARN] OPC UA read failed for R[{index}]: {exc}")
            return None

    def close(self) -> None:
        try:
            self._client.disconnect()
        except Exception:
            pass


def _normalize_item(raw_item: str) -> Optional[str]:
    if not raw_item:
        return None

    normalized = raw_item.lower().strip().strip(".,;:!?")
    normalized = normalized.replace("_", " ")
    normalized = " ".join(part for part in normalized.split() if part)

    if normalized in ALIAS_TO_KEY:
        return ALIAS_TO_KEY[normalized]

    return None


def _build_schema() -> dict:
    return {
        "intent": "string",
        "items": [
            {
                "item": "string",
                "quantity": 1,
            }
        ],
        "notes": "string",
    }


def _schema_prompt() -> str:
    return """You interpret natural-language warehouse order instructions for FANUC TP register updates.

Available product targets (canonical keys):
- nuttiess_choclae
- nivea
- shampoo
- appy_fizz
- cough_syrup
- coca_cola
- tea_botx
- pringles
- noodles
- bar
- ponds
- dove

Return ONLY JSON with this shape:
{
  "intent": "set_order",
  "items": [{"item": "nivea", "quantity": 2}],
  "notes": "short summary"
}

Intent rules:
- set_order: replace current order with provided items/quantities.
- add_order: add quantities to existing order.
- clear_order: clear all product quantities.
- status: user asks to inspect current order status.

Parsing rules:
1. Parse the full utterance, including multiple products.
2. Convert spoken numbers to integers.
3. Ignore filler words.
4. Use canonical key names only.
5. If user asks to clear/reset order, return intent=clear_order and items=[].
6. If user asks status/current order, return intent=status and items=[].
7. If user provides products with no quantity, assume quantity=1.
8. Quantity must be integer >= 1 for set_order/add_order.
"""


def _parse_llm_output(llm_output: dict) -> tuple[str, list[tuple[str, int]]]:
    parsed: dict = {}
    if isinstance(llm_output.get("normalized_output"), dict):
        parsed = llm_output["normalized_output"]
    elif isinstance(llm_output.get("parsed_output"), dict):
        parsed = llm_output["parsed_output"]

    raw_intent = str(parsed.get("intent", "set_order")).lower().strip()
    intent = raw_intent if raw_intent in {"set_order", "add_order", "clear_order", "status"} else "set_order"

    items: list[tuple[str, int]] = []
    raw_items = parsed.get("items", [])
    if isinstance(raw_items, list):
        for raw_entry in raw_items:
            if not isinstance(raw_entry, dict):
                continue
            item_key = _normalize_item(str(raw_entry.get("item", "")))
            if item_key is None:
                continue

            quantity = raw_entry.get("quantity", 1)
            try:
                qty_int = int(float(quantity))
            except (TypeError, ValueError):
                qty_int = 1

            if qty_int < 1:
                continue
            items.append((item_key, qty_int))

    return intent, items


def _all_product_registers() -> list[int]:
    return [p.register for p in PRODUCTS]


def _read_order_state(backend: RegisterBackend) -> dict[str, int]:
    state: dict[str, int] = {}
    for product in PRODUCTS:
        value = backend.read_register(product.register)
        state[product.key] = int(value or 0)
    return state


def _write_product_register(backend: RegisterBackend, product_key: str, quantity: int) -> bool:
    product = PRODUCT_BY_KEY[product_key]
    return backend.write_register(product.register, quantity)


def _recompute_totals(backend: RegisterBackend) -> bool:
    total = 0
    for product in PRODUCTS:
        total += int(backend.read_register(product.register) or 0)

    if not backend.write_register(ORDER_REG_TOTAL_PARTS, total):
        return False

    # New order should start with unload disabled; TP enables it when item loops complete.
    if not backend.write_register(ORDER_REG_UNLOAD_ENABLE, 0):
        return False

    return True


def _execute_order_update(intent: str, items: list[tuple[str, int]], backend: RegisterBackend) -> dict:
    if intent == "status":
        state = _read_order_state(backend)
        total = int(backend.read_register(ORDER_REG_TOTAL_PARTS) or sum(state.values()))
        unload_enable = int(backend.read_register(ORDER_REG_UNLOAD_ENABLE) or 0)
        return {
            "success": True,
            "message": f"Current order total={total}, unload_enable={unload_enable}",
            "state": state,
        }

    if intent == "clear_order":
        for product in PRODUCTS:
            if not backend.write_register(product.register, 0):
                return {"success": False, "message": f"Failed clearing R[{product.register}]"}
        if not backend.write_register(ORDER_REG_TOTAL_PARTS, 0):
            return {"success": False, "message": f"Failed writing R[{ORDER_REG_TOTAL_PARTS}]"}
        if not backend.write_register(ORDER_REG_UNLOAD_ENABLE, 0):
            return {"success": False, "message": f"Failed writing R[{ORDER_REG_UNLOAD_ENABLE}]"}
        return {
            "success": True,
            "message": "Order cleared: R[1..12]=0, R[25]=0, R[108]=0",
            "state": _read_order_state(backend),
        }

    if intent in {"set_order", "add_order"} and not items:
        return {
            "success": False,
            "message": "No valid items were parsed from command.",
        }

    if intent == "set_order":
        for product in PRODUCTS:
            if not backend.write_register(product.register, 0):
                return {"success": False, "message": f"Failed resetting R[{product.register}]"}

    state = _read_order_state(backend)
    for item_key, quantity in items:
        if intent == "add_order":
            new_value = state[item_key] + quantity
        else:
            new_value = quantity

        if not _write_product_register(backend, item_key, new_value):
            register_index = PRODUCT_BY_KEY[item_key].register
            return {"success": False, "message": f"Failed writing R[{register_index}] for {item_key}"}
        state[item_key] = new_value

    if not _recompute_totals(backend):
        return {
            "success": False,
            "message": f"Failed recomputing totals in R[{ORDER_REG_TOTAL_PARTS}] / R[{ORDER_REG_UNLOAD_ENABLE}]",
        }

    total = sum(state.values())
    return {
        "success": True,
        "message": f"Order updated ({intent}). total_parts={total}",
        "state": state,
    }


def _validate_robot_signals(io_client: Optional[FanucIOClient]) -> None:
    if io_client is None:
        return

    try:
        home = io_client.read_io("DO", DO_HOME_POSITION)
        order_done = io_client.read_io("DO", DO_ORDER_FULFILLED)
        confirm = io_client.read_io("DI", DI_ORDER_CONFIRMATION)
        received = io_client.read_io("DI", DI_ORDER_RECEIVED)
        print(
            "[IO] "
            f"DO[{DO_HOME_POSITION}] home={home}, "
            f"DO[{DO_ORDER_FULFILLED}] order_fulfilled={order_done}, "
            f"DI[{DI_ORDER_CONFIRMATION}] confirmation={confirm}, "
            f"DI[{DI_ORDER_RECEIVED}] order_received={received}"
        )
    except Exception as exc:
        print(f"[WARN] Could not read TP-related IO signals: {exc}")


def _print_state_table(state: dict[str, int]) -> None:
    print("\nRegisters (R1..R12 inferred from TP):")
    for product in PRODUCTS:
        value = state.get(product.key, 0)
        print(f"  R[{product.register:>3}] {product.description:<18} = {value}")


def _process_command(
    user_input: str,
    args: argparse.Namespace,
    backend: RegisterBackend,
    io_client: Optional[FanucIOClient],
    schema: dict,
    schema_prompt: str,
) -> bool:
    if not user_input:
        return False

    lowered = user_input.strip().lower()
    if lowered in {"exit", "quit"}:
        print("Goodbye!")
        return True

    parts = user_input.split()
    if parts and parts[0].lower() == "readreg":
        if len(parts) != 2:
            print("Usage: readreg <register_index>")
            return False
        try:
            register_index = int(parts[1])
        except ValueError:
            print("Register index must be an integer.")
            return False
        value = backend.read_register(register_index)
        if value is None:
            print(f"[ERROR] Could not read R[{register_index}]")
        else:
            print(f"R[{register_index}] = {value}")
        return False

    if parts and parts[0].lower() == "writereg":
        if len(parts) != 3:
            print("Usage: writereg <register_index> <value>")
            return False
        try:
            register_index = int(parts[1])
            value = int(parts[2])
        except ValueError:
            print("Register index and value must be integers.")
            return False
        success = backend.write_register(register_index, value)
        if success:
            print(f"[OK] Wrote R[{register_index}] = {value}")
        else:
            print(f"[ERROR] Write failed for R[{register_index}]")
        return False

    if parts and parts[0].lower() == "probe":
        if len(parts) != 3:
            print("Usage: probe <register_index> <value>")
            return False
        try:
            register_index = int(parts[1])
            value = int(parts[2])
        except ValueError:
            print("Register index and value must be integers.")
            return False

        if not backend.write_register(register_index, value):
            print(f"[ERROR] Probe write failed for R[{register_index}] = {value}")
            return False

        readback = backend.read_register(register_index)
        if readback is None:
            print(f"[ERROR] Probe readback failed for R[{register_index}]")
            return False

        if readback != value:
            print(f"[WARN] Probe mismatch for R[{register_index}]: wrote={value}, read={readback}")
            return False

        print(f"[OK] Probe success for R[{register_index}]: wrote={value}, read={readback}")
        return False

    if lowered == "status":
        result = _execute_order_update("status", [], backend)
        print(result["message"])
        _print_state_table(result.get("state", {}))
        _validate_robot_signals(io_client)
        return False

    try:
        llm_result = RobotControlLLM.TextCommand(
            model_name=args.model,
            model_parameters={
                "temperature": args.temperature,
                "stream": False,
                "timeout_seconds": args.timeout,
                "num_predict": 1024,
                "top_k": 40,
                "top_p": 0.9,
            },
            output_json=schema,
            prompt=schema_prompt + f"\nUser input: {user_input}\nOutput:",
        )

        intent, items = _parse_llm_output(llm_result)
        print(f"[PARSED] intent={intent}, items={items}")
        result = _execute_order_update(intent, items, backend)
        print(result["message"])

        if result.get("state"):
            _print_state_table(result["state"])

        if result.get("success"):
            CURRENT_STATE["last_intent"] = intent
            CURRENT_STATE["last_items"] = items
            CURRENT_STATE["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")

        _validate_robot_signals(io_client)

    except ConnectionError as exc:
        print(f"[ERROR] Connection error: {exc}")
        print("Hint: run 'ollama serve' in another terminal.")
    except Exception as exc:
        print(f"[ERROR] Failed to process command: {exc}")

    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM order fulfilment controller (TP register mapped)")
    parser.add_argument("model", nargs="?", default="llama3.1:8b", help="Ollama model name")
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--simulation", action="store_true", help="Use in-memory register simulation")
    parser.add_argument(
        "--register-writer-cmd",
        default="",
        help="Shell template to write a register, e.g. 'fanuc_reg_cli set {index} {value}'",
    )
    parser.add_argument(
        "--register-reader-cmd",
        default="",
        help="Shell template to read a register, e.g. 'fanuc_reg_cli get {index}'",
    )
    parser.add_argument("--opc-ua-endpoint", default="", help="OPC UA endpoint, e.g. opc.tcp://192.168.1.10:4840")
    parser.add_argument(
        "--opc-ua-namespace-index",
        type=int,
        default=2,
        help="Namespace index used in OPC UA node IDs",
    )
    parser.add_argument(
        "--opc-ua-node-template",
        default="ns={ns};s=Modbus.HoldingRegister[{address}]",
        help="Node ID template with placeholders {ns} and {address}",
    )
    parser.add_argument(
        "--opc-ua-register-offset",
        type=int,
        default=0,
        help="Holding-register address offset applied as address=offset+R[index]",
    )
    parser.add_argument(
        "--opc-ua-timeout",
        type=float,
        default=5.0,
        help="OPC UA connect/operation timeout in seconds",
    )
    parser.add_argument("--opc-ua-username", default="", help="Optional OPC UA username")
    parser.add_argument("--opc-ua-password", default="", help="Optional OPC UA password")
    parser.add_argument(
        "--opc-ua-probe-register",
        type=int,
        default=None,
        help="Optional startup probe register index (R[index])",
    )
    parser.add_argument(
        "--opc-ua-probe-value",
        type=int,
        default=1,
        help="Value to write for startup OPC UA probe",
    )
    parser.add_argument(
        "--opc-ua-probe-only",
        action="store_true",
        help="Run startup probe and exit without entering chat loop",
    )

    parser.add_argument("--voice", action="store_true", help="Enable voice input")
    parser.add_argument(
        "--voice-engine",
        choices=["whisper", "sphinx", "google"],
        default="sphinx",
    )
    parser.add_argument("--voice-trigger-key", default="r")
    parser.add_argument("--push-to-talk", action="store_true")
    parser.add_argument("--wake-word", default="crx")
    parser.add_argument("--wake-wait-seconds", type=float, default=2.5)
    parser.add_argument("--whisper-model", default="small")
    parser.add_argument("--whisper-compute-type", default="int8")
    parser.add_argument("--whisper-device", default="cpu")
    parser.add_argument("--whisper-language", default="en")
    parser.add_argument("--whisper-beam-size", type=int, default=3)

    args = parser.parse_args()

    if args.opc_ua_endpoint.strip():
        try:
            backend = OpcUaRegisterBackend(
                endpoint=args.opc_ua_endpoint.strip(),
                namespace_index=args.opc_ua_namespace_index,
                node_template=args.opc_ua_node_template,
                register_offset=args.opc_ua_register_offset,
                timeout_seconds=args.opc_ua_timeout,
                username=args.opc_ua_username,
                password=args.opc_ua_password,
            )
        except RuntimeError as exc:
            print(f"[ERROR] {exc}")
            raise SystemExit(1)
        except Exception as exc:
            print(f"[ERROR] OPC UA connection failed: {exc}")
            raise SystemExit(1)
        backend_mode = "OPC_UA"
    elif args.simulation or not args.register_writer_cmd.strip():
        backend: RegisterBackend = SimulationRegisterBackend()
        backend_mode = "SIMULATION"
    else:
        backend = ExternalCommandRegisterBackend(
            write_template=args.register_writer_cmd.strip(),
            read_template=args.register_reader_cmd.strip() or None,
        )
        backend_mode = "EXTERNAL_REGISTER_BRIDGE"

    io_client = None
    if not args.simulation:
        if ROS2_AVAILABLE and FANUC_IO_AVAILABLE:
            try:
                rclpy.init()
                io_client = FanucIOClient()
            except Exception as exc:
                print(f"[WARN] Could not initialize FANUC IO client: {exc}")
                io_client = None
        elif fanuc_import_error is not None:
            print(f"[WARN] ROS2 I/O unavailable: {fanuc_import_error}")

    schema = _build_schema()
    prompt = _schema_prompt()

    print("\n" + "=" * 78)
    print("  LLM Order Fulfilment Controller (TP Register Logic)")
    print("=" * 78)
    print(f"Model: {args.model}")
    print(f"Register backend: {backend_mode}")
    if backend_mode == "OPC_UA":
        print(f"OPC UA endpoint: {args.opc_ua_endpoint}")
        print(f"OPC UA node template: {args.opc_ua_node_template}")
        print(
            "OPC UA mapping: "
            f"address = {args.opc_ua_register_offset} + R[index], ns={args.opc_ua_namespace_index}"
        )
    print(f"Robot I/O client: {'ENABLED' if io_client is not None else 'DISABLED'}")
    print("\nMapped product registers:")
    for product in PRODUCTS:
        print(f"  R[{product.register:>3}] {product.description}")
    print(f"  R[{ORDER_REG_TOTAL_PARTS}] total parts")
    print(f"  R[{ORDER_REG_UNLOAD_ENABLE}] unload enable")
    print("\nExamples:")
    print("  • set order: 2 nivea, 1 dove, 3 pringles")
    print("  • add 1 shampoo and 2 noodles")
    print("  • clear order")
    print("  • status")
    print("  • readreg 25")
    print("  • writereg 25 3")
    print("  • probe 25 3")
    print("Type 'exit' to quit.")

    if args.opc_ua_probe_register is not None:
        probe_register = int(args.opc_ua_probe_register)
        probe_value = int(args.opc_ua_probe_value)
        print(f"\n[PROBE] Writing R[{probe_register}]={probe_value} then reading back...")
        probe_ok = backend.write_register(probe_register, probe_value)
        readback = backend.read_register(probe_register) if probe_ok else None
        if not probe_ok or readback is None:
            print(f"[ERROR] Startup probe failed for R[{probe_register}]")
        elif readback != probe_value:
            print(f"[WARN] Startup probe mismatch: wrote={probe_value}, read={readback}")
        else:
            print(f"[OK] Startup probe success: R[{probe_register}]={readback}")

        if args.opc_ua_probe_only:
            backend.close()
            return

    exit_requested = threading.Event()
    configured_wake_word = args.wake_word.strip().lower()
    wake_lock = threading.Lock()
    wake_active = False
    wake_deadline = 0.0
    wake_buffer = ""

    def _extract_voice_command(text: str) -> Optional[str]:
        spoken = text.strip()
        if not spoken:
            return None
        if not configured_wake_word:
            return spoken

        lowered = spoken.lower().strip()
        if not lowered.startswith(configured_wake_word):
            print(f"[voice] Ignored. Start with wake word '{args.wake_word}'.")
            return None

        remainder = spoken[len(configured_wake_word) :].lstrip(" ,:;.-")
        if not remainder:
            print("[voice] Wake word heard, but no command followed.")
            return None

        return remainder

    def _append_running_text(existing: str, chunk: str) -> str:
        if not existing:
            return chunk.strip()
        if not chunk:
            return existing
        return f"{existing} {chunk.strip()}".strip()

    def _finalize_wake_command() -> None:
        nonlocal wake_active, wake_deadline, wake_buffer
        with wake_lock:
            command_text = wake_buffer.strip()
            wake_active = False
            wake_deadline = 0.0
            wake_buffer = ""

        if not command_text:
            print("[voice] Wake word heard, but no command captured.")
            return

        print(f"[voice] Executing: {command_text}")
        if _process_command(command_text, args, backend, io_client, schema, prompt):
            exit_requested.set()

    def _wake_monitor_loop() -> None:
        nonlocal wake_active, wake_deadline
        while not exit_requested.is_set():
            should_finalize = False
            with wake_lock:
                should_finalize = wake_active and wake_deadline > 0.0 and time.time() >= wake_deadline
            if should_finalize:
                _finalize_wake_command()
            time.sleep(0.1)

    wake_monitor_thread: threading.Thread | None = None

    def _on_voice_final(text: str) -> None:
        nonlocal wake_active, wake_deadline, wake_buffer
        print(f"\nFinal recognized text: {text}")

        if args.push_to_talk:
            command_text = _extract_voice_command(text)
            if command_text is None:
                return
            if _process_command(command_text, args, backend, io_client, schema, prompt):
                exit_requested.set()
            return

        lowered = text.strip().lower()
        if configured_wake_word and lowered.startswith(configured_wake_word):
            remainder = text[len(configured_wake_word) :].lstrip(" ,:;.-")
            with wake_lock:
                wake_active = True
                wake_buffer = remainder
                wake_deadline = time.time() + args.wake_wait_seconds
            if remainder:
                print(f"[voice] Wake accepted. Captured: {remainder}")
            else:
                print("[voice] Wake accepted. Listening for command...")
            return

        with wake_lock:
            if not wake_active:
                print(f"[voice] Ignored. Say wake word '{args.wake_word}' first.")
                return
            wake_buffer = _append_running_text(wake_buffer, text)
            wake_deadline = time.time() + args.wake_wait_seconds
            print(f"[voice] Capturing command: {wake_buffer}")

    def _on_voice_error(message: str) -> None:
        print(f"[voice] {message}")

    voice_controller: PressToTalkVoiceController | None = None

    if args.voice:
        always_listen = not args.push_to_talk
        try:
            voice_controller = PressToTalkVoiceController(
                trigger_key=args.voice_trigger_key,
                always_listen=always_listen,
                engine=args.voice_engine,
                on_final=_on_voice_final,
                on_error=_on_voice_error,
                whisper_model_size=args.whisper_model,
                whisper_device=args.whisper_device,
                whisper_compute_type=args.whisper_compute_type,
                whisper_beam_size=args.whisper_beam_size,
                whisper_language=None if args.whisper_language.lower() == "auto" else args.whisper_language,
            )
        except RuntimeError as exc:
            print(f"[ERROR] Voice setup failed: {exc}")
            raise SystemExit(1)

        if not args.push_to_talk:
            wake_monitor_thread = threading.Thread(target=_wake_monitor_loop, daemon=True)
            wake_monitor_thread.start()

        voice_controller.start()
        if args.push_to_talk:
            print(f"Voice mode: Hold {args.voice_trigger_key.upper()} to record.")
        else:
            print("Voice mode: always listening.")
            if configured_wake_word:
                print(f"Wake word: {args.wake_word}")

    try:
        while not exit_requested.is_set():
            if args.voice:
                time.sleep(0.2)
                continue

            user_input = input("\nYou> ").strip()
            if _process_command(user_input, args, backend, io_client, schema, prompt):
                break
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    finally:
        exit_requested.set()
        if voice_controller is not None:
            voice_controller.stop()
        backend.close()
        if io_client is not None:
            io_client.destroy_node()
            rclpy.try_shutdown()


if __name__ == "__main__":
    main()
