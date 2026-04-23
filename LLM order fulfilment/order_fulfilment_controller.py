"""LLM + voice order controller mapped to FANUC TP order registers."""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse
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
    Product("nuttiess_choclae", 1, "Nuttiess Choclae", ("nutties", "nuttiess", "nutties chocolate", "nuttiess choclae", "nutties choclate", "nuttiess chocolate")),
    Product("nivea", 2, "NIVEA", ("nivea", "niva", "niviea")),
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

BUILD_VERSION = "2026-04-23-local-parser-v2"


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
    """Read/write FANUC registers using the local FANUC OPC UA helper."""

    def __init__(
        self,
        *,
        ip: str,
        port: int,
    ) -> None:
        try:
            import fanuc_register_opcua as fanuc_opcua
        except ImportError as exc:
            raise RuntimeError(
                "fanuc_register_opcua.py is required in this folder for FANUC OPC UA register access."
            ) from exc

        self._fanuc = fanuc_opcua
        self._client = self._fanuc.connect(ip=ip, port=int(port))

    def write_register(self, index: int, value: int) -> bool:
        try:
            self._fanuc.write_register(self._client, int(index), int(value))
            return True
        except Exception as exc:
            print(f"[ERROR] OPC UA write failed for R[{index}]={value}: {exc}")
            return False

    def read_register(self, index: int) -> Optional[int]:
        try:
            value = self._fanuc.read_register(self._client, int(index))
            return int(value)
        except Exception as exc:
            print(f"[WARN] OPC UA read failed for R[{index}]: {exc}")
            return None

    def close(self) -> None:
        try:
            self._fanuc.disconnect(self._client)
        except Exception:
            pass


def _opcua_target_from_args(args: argparse.Namespace) -> tuple[str, int] | None:
    """Derive OPC UA target from endpoint string or explicit ip/port args."""
    if args.opc_ua_endpoint.strip():
        parsed = urlparse(args.opc_ua_endpoint.strip())
        host = parsed.hostname
        port = parsed.port
        if not host or not port:
            raise ValueError("--opc-ua-endpoint must include host and port, e.g. opc.tcp://192.168.1.5:4880")
        return host, int(port)

    if args.opc_ua_ip.strip():
        return args.opc_ua_ip.strip(), int(args.opc_ua_port)

    return None


def _normalize_item(raw_item: str) -> Optional[str]:
    if not raw_item:
        return None

    normalized = raw_item.lower().strip().strip(".,;:!?")
    normalized = normalized.replace("_", " ")
    normalized = " ".join(part for part in normalized.split() if part)
    for suffix in (" please", " pls", " kindly", " now"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)].strip()

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


_NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
}


def _as_positive_int(raw_qty: object) -> Optional[int]:
    try:
        qty = int(float(raw_qty))
    except (TypeError, ValueError):
        text = str(raw_qty).strip().lower()
        qty = _NUMBER_WORDS.get(text, -1)
    if qty < 1:
        return None
    return qty


def _extract_items_from_container(container: dict) -> list[tuple[str, int]]:
    items: list[tuple[str, int]] = []
    raw_items = container.get("items", [])
    if not isinstance(raw_items, list):
        return items

    for raw_entry in raw_items:
        if not isinstance(raw_entry, dict):
            continue
        item_key = _normalize_item(str(raw_entry.get("item", "")))
        if item_key is None:
            continue
        qty = _as_positive_int(raw_entry.get("quantity", 1))
        if qty is None:
            continue
        items.append((item_key, qty))

    return items


def _extract_items_from_text(user_text: str) -> list[tuple[str, int]]:
    text = user_text.lower().strip()
    if not text:
        return []

    # Capture phrases like "4 nutties" or "three nivea" separated by comma/and/end.
    pattern = r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)\s+([a-z_ ]+?)(?=\s*(?:,|and|&|$))"
    matches = re.findall(pattern, text)
    extracted: list[tuple[str, int]] = []

    for raw_qty, raw_item in matches:
        qty = _as_positive_int(raw_qty)
        if qty is None:
            continue
        item_key = _normalize_item(raw_item)
        if item_key is None:
            continue
        extracted.append((item_key, qty))

    return extracted


def _derive_intent_from_text(user_text: str) -> str:
    lowered = user_text.lower()
    if any(token in lowered for token in ("status", "current order", "show order")):
        return "status"
    if any(token in lowered for token in ("clear order", "reset order", "remove all", "clear all")):
        return "clear_order"
    if any(token in lowered for token in ("add", "plus", "increase")):
        return "add_order"
    return "set_order"


def _parse_llm_output(llm_output: dict, user_text: str) -> tuple[str, list[tuple[str, int]]]:
    candidate_containers: list[dict] = []
    normalized_candidate = llm_output.get("normalized_output")
    parsed_candidate = llm_output.get("parsed_output")
    if isinstance(normalized_candidate, dict):
        candidate_containers.append(normalized_candidate)
    if isinstance(parsed_candidate, dict):
        candidate_containers.append(parsed_candidate)

    intent = "set_order"
    items: list[tuple[str, int]] = []

    for container in candidate_containers:
        raw_intent = str(container.get("intent", "set_order")).lower().strip()
        parsed_intent = raw_intent if raw_intent in {"set_order", "add_order", "clear_order", "status"} else "set_order"
        parsed_items = _extract_items_from_container(container)

        # Keep the best signal: explicit status/clear intent or any non-empty items list.
        if parsed_intent in {"status", "clear_order"}:
            intent = parsed_intent
            items = parsed_items
            break
        if parsed_items:
            intent = parsed_intent
            items = parsed_items
            break

    if not items and intent in {"set_order", "add_order"}:
        text_items = _extract_items_from_text(user_text)
        if text_items:
            items = text_items
            # If user says add/increase, preserve add_order behavior.
            lowered = user_text.lower()
            if any(token in lowered for token in ("add", "plus", "increase")):
                intent = "add_order"

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
        recomputed_total = sum(state.values())
        total_reg = backend.read_register(ORDER_REG_TOTAL_PARTS)
        total = int(total_reg) if total_reg is not None else recomputed_total
        unload_enable = int(backend.read_register(ORDER_REG_UNLOAD_ENABLE) or 0)
        mismatch_note = ""
        if total != recomputed_total:
            mismatch_note = f" (mismatch: R[{ORDER_REG_TOTAL_PARTS}]={total}, recomputed={recomputed_total})"
        return {
            "success": True,
            "message": f"Current order total={total}, unload_enable={unload_enable}{mismatch_note}",
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

    if lowered.startswith("python3 ") or lowered.startswith("python "):
        print("You are inside the app prompt. Type register/order commands here, or type 'exit' and run shell commands in terminal.")
        return False

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

    # Deterministic local parse first for phrases like "3 nivea and 4 nutties".
    local_intent = _derive_intent_from_text(user_input)
    local_items = _extract_items_from_text(user_input)
    if local_intent in {"status", "clear_order"} or local_items:
        print(f"[PARSED:LOCAL] intent={local_intent}, items={local_items}")
        result = _execute_order_update(local_intent, local_items, backend)
        print(result["message"])
        if result.get("state"):
            _print_state_table(result["state"])
        if result.get("success"):
            CURRENT_STATE["last_intent"] = local_intent
            CURRENT_STATE["last_items"] = local_items
            CURRENT_STATE["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
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

        intent, items = _parse_llm_output(llm_result, user_input)
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
    parser.add_argument("--opc-ua-ip", default="", help="FANUC controller IP for OPC UA, e.g. 192.168.1.5")
    parser.add_argument("--opc-ua-port", type=int, default=4880, help="FANUC OPC UA port (default 4880)")
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

    opcua_target = None
    try:
        opcua_target = _opcua_target_from_args(args)
    except ValueError as exc:
        print(f"[ERROR] {exc}")
        raise SystemExit(1)

    if opcua_target is not None:
        try:
            opcua_ip, opcua_port = opcua_target
            backend = OpcUaRegisterBackend(
                ip=opcua_ip,
                port=opcua_port,
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
    # OPC UA register mode does not require ROS2 IO dependencies.
    if not args.simulation and backend_mode != "OPC_UA":
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
    print(f"Build: {BUILD_VERSION}")
    print(f"Model: {args.model}")
    print(f"Register backend: {backend_mode}")
    if backend_mode == "OPC_UA":
        if args.opc_ua_endpoint.strip():
            print(f"OPC UA endpoint: {args.opc_ua_endpoint}")
        else:
            print(f"OPC UA endpoint: opc.tcp://{args.opc_ua_ip}:{args.opc_ua_port}/FANUC/NanoUaServer")
        print("OPC UA mapping: FANUC default HoldingRegisters -> R[1..]")
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
