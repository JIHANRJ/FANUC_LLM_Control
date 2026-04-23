"""LLM + voice order controller mapped to FANUC TP order registers."""

from __future__ import annotations

import argparse
import csv
import re
import shlex
import subprocess
import sys
import threading
import time
import uuid
from urllib.parse import urlparse
from dataclasses import dataclass
from datetime import datetime, timezone
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
    Product("appy_fizz", 4, "Appy Fizz", ("appy fizz", "appyfizz", "fizz", "fizzes", "appy fizzes", "appy fiz", "fizzy drink", "fizzy")),
    Product("cough_syrup", 5, "Cough Syrup", ("cough syrup", "coughsyrup", "syrup")),
    Product("coca_cola", 6, "Coca Cola", ("coca cola", "coke", "cocacola")),
    Product("tea_botx", 7, "Tea botx", ("tea", "tea box", "tea botx", "teabox")),
    Product("pringles", 8, "Pringles", ("pringles",)),
    Product("noodles", 9, "Noodles", ("noodles", "noodle")),
    Product("bar", 10, "Bar", ("bar", "chocolate bar")),
    Product("ponds", 11, "Ponds", ("ponds", "ponds cream")),
    Product("dove", 12, "Dove", ("dove", "dove soap", "soap")),
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

BUILD_VERSION = "2026-04-23-telemetry-v1"

VOICE_LABEL_BY_KEY = {
    "nuttiess_choclae": "Nuttiess Choclae",
    "nivea": "NIVEA",
    "shampoo": "Shampoo",
    "appy_fizz": "Appy Fizz",
    "cough_syrup": "Cough Syrup",
    "coca_cola": "Coca Cola",
    "tea_botx": "Tea botx",
    "pringles": "Pringles",
    "noodles": "Noodles",
    "bar": "Chocolate Bar",
    "ponds": "Ponds",
    "dove": "Dove soap",
}

TELEMETRY_HEADERS = [
    "timestamp_utc",
    "session_id",
    "command_id",
    "model_parser",
    "model_dialogue",
    "voice_engine",
    "wake_word",
    "raw_recognized_text",
    "spoken_text",
    "spoken_text_chars",
    "spoken_text_words",
    "reply_text",
    "reply_chars",
    "reply_words",
    "intent",
    "items_count",
    "success",
    "recording_start_ts",
    "first_chunk_ts",
    "wake_accept_ts",
    "execute_start_ts",
    "parse_start_ts",
    "parse_end_ts",
    "parse_ms",
    "llm_parse_ms",
    "local_parse_ms",
    "execute_end_ts",
    "execute_ms",
    "reply_start_ts",
    "reply_end_ts",
    "reply_ms",
    "dialogue_llm_ms",
    "total_recording_to_execute_ms",
    "total_recording_to_reply_ms",
]


def _default_telemetry_csv_path() -> Path:
    return MODULE_ROOT / "logs" / "voice_metrics.csv"


def _ensure_telemetry_csv(csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if csv_path.exists() and csv_path.stat().st_size > 0:
        try:
            with csv_path.open("r", encoding="utf-8") as handle:
                first_line = handle.readline().strip()
            expected_header = ",".join(TELEMETRY_HEADERS)
            if first_line == expected_header:
                return
            backup_path = csv_path.with_suffix(csv_path.suffix + f".schema_backup_{int(time.time())}")
            csv_path.rename(backup_path)
            print(f"[telemetry] Existing CSV schema changed, rotated old log to: {backup_path}")
        except Exception as exc:
            print(f"[WARN] Could not validate telemetry schema, recreating file: {exc}")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TELEMETRY_HEADERS)
        writer.writeheader()


def _append_telemetry_row(csv_path: Path, row: dict[str, object]) -> None:
    with csv_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TELEMETRY_HEADERS)
        writer.writerow({key: row.get(key, "") for key in TELEMETRY_HEADERS})


def _elapsed_ms(start_ts: Optional[float], end_ts: Optional[float]) -> Optional[float]:
    if start_ts is None or end_ts is None:
        return None
    return round(max(0.0, (end_ts - start_ts) * 1000.0), 3)


def _word_count(text: str) -> int:
    return len([part for part in text.strip().split() if part])


def _dialogue_model_name(args: argparse.Namespace) -> str:
    return args.dialogue_model.strip() or args.model


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
    for prefix in ("of ", "the ", "a ", "an "):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):].strip()
    for suffix in (" please", " pls", " kindly", " now"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)].strip()

    if normalized in ALIAS_TO_KEY:
        return ALIAS_TO_KEY[normalized]

    # Basic singularization/plural normalization for voice-text variability.
    plural_candidates = [normalized]
    if normalized.endswith("es"):
        plural_candidates.append(normalized[:-2].strip())
    if normalized.endswith("s"):
        plural_candidates.append(normalized[:-1].strip())

    for candidate in plural_candidates:
        if candidate in ALIAS_TO_KEY:
            return ALIAS_TO_KEY[candidate]

    # Contains-match fallback for phrases like "appy fizzes" or "nivea cream".
    for alias, key in ALIAS_TO_KEY.items():
        if alias and (alias in normalized or normalized in alias):
            return key

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
    "intent": "add_order",
  "items": [{"item": "nivea", "quantity": 2}],
  "notes": "short summary"
}

Intent rules:
- set_order: replace current order with provided items/quantities.
- add_order: add quantities to existing order.
- remove_order: subtract quantities from existing order (floor at 0).
- clear_order: clear all product quantities.
- status: user asks to inspect current order status.
- product_list: user asks what products are available / for sale.
- vend_order: user asks to execute/checkout/confirm vend for current cart.

Parsing rules:
1. Parse the full utterance, including multiple products.
2. Convert spoken numbers to integers.
3. Ignore filler words.
4. Use canonical key names only.
5. If user asks to clear/reset order, return intent=clear_order and items=[].
6. If user asks status/current order, return intent=status and items=[].
7. If user asks for available products/menu/list, return intent=product_list and items=[].
8. If user provides products with no quantity, assume quantity=1.
9. Quantity must be integer >= 1 for set_order/add_order/remove_order.
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

    qty_token = (
        r"\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
        r"fifteen|sixteen|seventeen|eighteen|nineteen|twenty"
    )

    # Capture phrases like "4 nutties", "three nivea", "6 of appy fizz", etc.
    pattern = (
        rf"({qty_token})\s+([a-z_ ]+?)(?=\s*(?:,|and|&|plus|with|then|(?:{qty_token})|$))"
    )
    implied_one_pattern = rf"(?:\ba\b|\ban\b|\bsome\b)\s+([a-z_ ]+?)(?=\s*(?:,|and|&|plus|with|then|(?:{qty_token})|$))"
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

    for raw_item in re.findall(implied_one_pattern, text):
        item_key = _normalize_item(raw_item)
        if item_key is None:
            continue
        extracted.append((item_key, 1))

    # Fallback for bare item mentions like "fizzy drink" without an explicit quantity.
    if not extracted:
        seen_keys: set[str] = set()
        for alias in sorted(ALIAS_TO_KEY.keys(), key=len, reverse=True):
            if not alias:
                continue
            if re.search(rf"\b{re.escape(alias)}\b", text):
                key = ALIAS_TO_KEY[alias]
                if key in seen_keys:
                    continue
                extracted.append((key, 1))
                seen_keys.add(key)

    if not extracted:
        return []

    aggregated: dict[str, int] = {}
    for item_key, qty in extracted:
        aggregated[item_key] = aggregated.get(item_key, 0) + qty

    return [(item_key, qty) for item_key, qty in aggregated.items()]


def _derive_intent_from_text(user_text: str) -> str:
    lowered = user_text.lower()
    if any(
        token in lowered
        for token in (
            "ready to vend",
            "vend now",
            "execute vend",
            "execute order",
            "checkout",
            "place order",
            "confirm order",
            "go ahead",
            "proceed",
        )
    ):
        return "vend_order"

    if any(
        token in lowered
        for token in (
            "recommend",
            "suggest",
            "what should i get",
            "which one",
            "which would you",
        )
    ):
        return "product_list"

    if any(
        token in lowered
        for token in (
            "product list",
            "products list",
            "show products",
            "show product",
            "show me your product list",
            "what products",
            "what all products",
            "products do you have",
            "items do you have",
            "for sale",
            "menu",
            "catalog",
        )
    ):
        return "product_list"

    if any(
        token in lowered
        for token in (
            "status",
            "current order",
            "show order",
            "what's my order",
            "whats my order",
            "my order",
            "what do we have",
            "what are now",
            "amount of items",
            "how many items",
            "how much items",
            "items are present",
        )
    ):
        return "status"
    has_clear_phrase = any(token in lowered for token in ("clear order", "reset order", "remove all", "clear all", "new order", "reset"))
    has_replace_phrase = any(token in lowered for token in ("replace", "instead", "actually"))
    has_add_phrase = any(token in lowered for token in ("add", "plus", "increase", "also", "another", "too", "get me", "i want", "i need", "bring me"))
    has_remove_phrase = any(token in lowered for token in ("remove", "delete", "take out", "minus", "reduce", "drop", "cancel"))
    has_set_phrase = any(token in lowered for token in ("set order", "replace order", "new order", "start new order"))
    has_order_request = bool(_extract_items_from_text(lowered))

    if has_clear_phrase and not has_order_request:
        return "clear_order"
    if has_clear_phrase and has_order_request:
        return "set_order"
    if has_remove_phrase:
        return "remove_order"
    if has_replace_phrase:
        return "set_order"
    if has_set_phrase:
        return "set_order"
    if has_add_phrase:
        return "add_order"
    if has_order_request:
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
        parsed_intent = raw_intent if raw_intent in {"set_order", "add_order", "remove_order", "clear_order", "status", "product_list", "vend_order"} else "set_order"
        parsed_items = _extract_items_from_container(container)

        # Keep the best signal: explicit status/clear intent or any non-empty items list.
        if parsed_intent in {"status", "clear_order", "product_list", "vend_order"}:
            intent = parsed_intent
            items = parsed_items
            break
        if parsed_items:
            intent = parsed_intent
            items = parsed_items
            break

    if not items and intent in {"set_order", "add_order", "remove_order"}:
        text_items = _extract_items_from_text(user_text)
        if text_items:
            items = text_items
            # If user says add/increase, preserve add_order behavior.
            lowered = user_text.lower()
            if any(token in lowered for token in ("add", "plus", "increase", "also", "another", "too")):
                intent = "add_order"
            if any(token in lowered for token in ("remove", "delete", "take out", "minus", "reduce", "drop", "cancel")):
                intent = "remove_order"

    # Reconcile LLM intent with deterministic text intent when possible.
    derived_intent = _derive_intent_from_text(user_text)
    if derived_intent in {"status", "clear_order", "product_list", "vend_order"}:
        # Safety: never let LLM-invented items trigger register writes for query intents.
        return derived_intent, []

    if items and derived_intent in {"set_order", "add_order", "remove_order"}:
        intent = derived_intent

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
    if intent == "product_list":
        return {
            "success": True,
            "message": "Available products requested.",
            "state": _read_order_state(backend),
        }

    if intent == "vend_order":
        state = _read_order_state(backend)
        total = sum(state.values())
        if total < 1:
            return {
                "success": False,
                "message": "Cart is empty. Add items before vending.",
                "state": state,
            }
        if not backend.write_register(ORDER_REG_TOTAL_PARTS, total):
            return {"success": False, "message": f"Failed writing R[{ORDER_REG_TOTAL_PARTS}]"}
        if not backend.write_register(ORDER_REG_UNLOAD_ENABLE, 1):
            return {"success": False, "message": f"Failed writing R[{ORDER_REG_UNLOAD_ENABLE}]"}
        return {
            "success": True,
            "message": f"Vend requested. R[{ORDER_REG_UNLOAD_ENABLE}]=1 with total_parts={total}",
            "state": state,
        }

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

    if intent in {"set_order", "add_order", "remove_order"} and not items:
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
        elif intent == "remove_order":
            new_value = max(0, state[item_key] - quantity)
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


def _validate_robot_signals(io_client: Optional[object]) -> None:
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


def _spoken_list(items: list[tuple[str, int]]) -> str:
    parts: list[str] = []
    for item_key, qty in items:
        label = VOICE_LABEL_BY_KEY.get(item_key, item_key.replace("_", " ").title())
        parts.append(f"{qty} {label}")
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def _build_crx_reply_template(intent: str, items: list[tuple[str, int]], result: dict) -> str:
    if not result.get("success"):
        if intent == "vend_order":
            return "Your cart is empty right now. Add items first, then say ready to vend."
        return "I didn't quite catch that, but I'm here to help. Could you say it one more time?"

    if intent == "status":
        state = result.get("state", {})
        total = sum(int(v or 0) for v in state.values())
        item_word = "item" if total == 1 else "items"
        non_zero = []
        for product in PRODUCTS:
            qty = int(state.get(product.key, 0) or 0)
            if qty > 0:
                label = VOICE_LABEL_BY_KEY.get(product.key, product.description)
                non_zero.append(f"{qty} {label}")
        if non_zero:
            listed = ", ".join(non_zero)
            return f"You currently have {total} {item_word} in your order: {listed}. Want me to add anything else?"
        return "Your order is currently empty. Tell me what you'd like, and I'll grab it for you."

    if intent == "product_list":
        product_names = [VOICE_LABEL_BY_KEY.get(product.key, product.description) for product in PRODUCTS]
        return (
            "Great question. I can fetch: "
            + ", ".join(product_names)
            + ". If you want a recommendation, I can suggest by snack, drink, or skincare."
        )

    if intent == "clear_order":
        return "Done, your order is cleared and we're starting fresh. Tell me what you'd like next."

    if intent == "add_order":
        state = result.get("state", {})
        total = sum(int(v or 0) for v in state.values())
        item_word = "item" if total == 1 else "items"
        if len(items) == 1:
            item_key, qty = items[0]
            label = VOICE_LABEL_BY_KEY.get(item_key, item_key.replace("_", " ").title())
            return f"Added to cart: {qty} {label}. Your cart now has {total} {item_word}."
        return f"Added to cart: {_spoken_list(items)}. Your cart now has {total} {item_word}."

    if intent == "remove_order":
        state = result.get("state", {})
        total = sum(int(v or 0) for v in state.values())
        item_word = "item" if total == 1 else "items"
        if len(items) == 1:
            item_key, qty = items[0]
            label = VOICE_LABEL_BY_KEY.get(item_key, item_key.replace("_", " ").title())
            return f"Removed {qty} {label} from cart. Your cart now has {total} {item_word}."
        return f"Updated cart: removed {_spoken_list(items)}. Your cart now has {total} {item_word}."

    if intent == "vend_order":
        return "Great, you're ready to vend. Executing your cart now."

    if len(items) == 1:
        item_key, qty = items[0]
        label = VOICE_LABEL_BY_KEY.get(item_key, item_key.replace("_", " ").title())
        qty_text = f"{qty} " if qty > 1 else ""
        return f"Absolutely. I'll grab your {qty_text}{label} right away."

    return f"Lovely choice. I'll fetch {_spoken_list(items)} for you right now."


def _build_crx_reply(
    intent: str,
    items: list[tuple[str, int]],
    result: dict,
    args: argparse.Namespace,
    user_input: str,
) -> tuple[str, Optional[float]]:
    if args.no_dialogue_llm:
        return _build_crx_reply_template(intent, items, result), None

    try:
        state = result.get("state", {}) if isinstance(result.get("state", {}), dict) else {}
        dialogue_context = {
            "user_input": user_input,
            "intent": intent,
            "items": [
                {
                    "item": VOICE_LABEL_BY_KEY.get(item_key, item_key),
                    "quantity": qty,
                }
                for item_key, qty in items
            ],
            "success": bool(result.get("success", False)),
            "message": str(result.get("message", "")),
            "order_total": sum(int(v or 0) for v in state.values()) if state else 0,
            "non_zero_order_items": [
                {
                    "item": VOICE_LABEL_BY_KEY.get(product.key, product.description),
                    "quantity": int(state.get(product.key, 0) or 0),
                }
                for product in PRODUCTS
                if int(state.get(product.key, 0) or 0) > 0
            ],
            "available_products": [VOICE_LABEL_BY_KEY.get(product.key, product.description) for product in PRODUCTS],
        }

        dialogue_result = RobotControlLLM.DialogueResponse(
            model_name=_dialogue_model_name(args),
            model_parameters={
                "temperature": args.dialogue_temperature,
                "stream": False,
                "timeout_seconds": args.dialogue_timeout,
                "num_predict": args.dialogue_max_tokens,
                "top_k": 40,
                "top_p": 0.92,
            },
            context=dialogue_context,
        )
        reply_text = str(dialogue_result.get("response", "")).strip()
        if reply_text:
            return reply_text, float(dialogue_result.get("elapsed_ms", 0.0))
    except Exception:
        pass

    return _build_crx_reply_template(intent, items, result), None


def _finalize_and_respond(
    *,
    intent: str,
    items: list[tuple[str, int]],
    backend: RegisterBackend,
    io_client: Optional[object],
    args: argparse.Namespace,
    user_input: str,
    telemetry_ctx: Optional[dict[str, object]] = None,
) -> None:
    execute_start_ts = time.monotonic()
    if telemetry_ctx is not None:
        telemetry_ctx["execute_start_ts"] = execute_start_ts

    result = _execute_order_update(intent, items, backend)
    execute_end_ts = time.monotonic()
    if telemetry_ctx is not None:
        telemetry_ctx["execute_end_ts"] = execute_end_ts
        telemetry_ctx["execute_ms"] = _elapsed_ms(execute_start_ts, execute_end_ts)

    print(result["message"])
    if result.get("state"):
        _print_state_table(result["state"])
    if result.get("success"):
        CURRENT_STATE["last_intent"] = intent
        CURRENT_STATE["last_items"] = items
        CURRENT_STATE["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")

    reply_start_ts = time.monotonic()
    reply_text, dialogue_llm_ms = _build_crx_reply(intent, items, result, args, user_input)
    reply_end_ts = time.monotonic()
    print(f"CRX> {reply_text}")
    _validate_robot_signals(io_client)

    if telemetry_ctx is None:
        return

    telemetry_ctx["reply_start_ts"] = reply_start_ts
    telemetry_ctx["reply_end_ts"] = reply_end_ts
    telemetry_ctx["reply_ms"] = _elapsed_ms(reply_start_ts, reply_end_ts)
    telemetry_ctx["intent"] = intent
    telemetry_ctx["items_count"] = len(items)
    telemetry_ctx["success"] = bool(result.get("success", False))
    telemetry_ctx["reply_text"] = reply_text
    telemetry_ctx["dialogue_llm_ms"] = dialogue_llm_ms if dialogue_llm_ms is not None else ""

    spoken_text = str(telemetry_ctx.get("spoken_text", ""))
    recording_start_ts = telemetry_ctx.get("recording_start_ts")
    if not isinstance(recording_start_ts, (int, float)):
        recording_start_ts = None

    row = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "session_id": telemetry_ctx.get("session_id", ""),
        "command_id": telemetry_ctx.get("command_id", ""),
        "model_parser": args.model,
        "model_dialogue": _dialogue_model_name(args) if not args.no_dialogue_llm else "template_fallback",
        "voice_engine": args.voice_engine if args.voice else "text",
        "wake_word": args.wake_word if args.voice else "",
        "raw_recognized_text": telemetry_ctx.get("raw_recognized_text", ""),
        "spoken_text": spoken_text,
        "spoken_text_chars": len(spoken_text),
        "spoken_text_words": _word_count(spoken_text),
        "reply_text": reply_text,
        "reply_chars": len(reply_text),
        "reply_words": _word_count(reply_text),
        "intent": telemetry_ctx.get("intent", ""),
        "items_count": telemetry_ctx.get("items_count", 0),
        "success": telemetry_ctx.get("success", False),
        "recording_start_ts": telemetry_ctx.get("recording_start_ts", ""),
        "first_chunk_ts": telemetry_ctx.get("first_chunk_ts", ""),
        "wake_accept_ts": telemetry_ctx.get("wake_accept_ts", ""),
        "execute_start_ts": telemetry_ctx.get("execute_start_ts", ""),
        "parse_start_ts": telemetry_ctx.get("parse_start_ts", ""),
        "parse_end_ts": telemetry_ctx.get("parse_end_ts", ""),
        "parse_ms": telemetry_ctx.get("parse_ms", ""),
        "llm_parse_ms": telemetry_ctx.get("llm_parse_ms", ""),
        "local_parse_ms": telemetry_ctx.get("local_parse_ms", ""),
        "execute_end_ts": telemetry_ctx.get("execute_end_ts", ""),
        "execute_ms": telemetry_ctx.get("execute_ms", ""),
        "reply_start_ts": telemetry_ctx.get("reply_start_ts", ""),
        "reply_end_ts": telemetry_ctx.get("reply_end_ts", ""),
        "reply_ms": telemetry_ctx.get("reply_ms", ""),
        "dialogue_llm_ms": telemetry_ctx.get("dialogue_llm_ms", ""),
        "total_recording_to_execute_ms": _elapsed_ms(recording_start_ts, execute_end_ts),
        "total_recording_to_reply_ms": _elapsed_ms(recording_start_ts, reply_end_ts),
    }

    try:
        if args.telemetry_enabled:
            _append_telemetry_row(Path(args.telemetry_csv), row)
    except Exception as exc:
        print(f"[WARN] Telemetry logging failed: {exc}")


def _print_state_table(state: dict[str, int]) -> None:
    print("\nRegisters (R1..R12 inferred from TP):")
    for product in PRODUCTS:
        value = state.get(product.key, 0)
        print(f"  R[{product.register:>3}] {product.description:<18} = {value}")


def _process_command(
    user_input: str,
    args: argparse.Namespace,
    backend: RegisterBackend,
    io_client: Optional[object],
    schema: dict,
    schema_prompt: str,
    telemetry_ctx: Optional[dict[str, object]] = None,
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

    if lowered in {"status", "products", "product list", "show products", "show product list", "menu", "ready to vend", "vend", "vend now", "checkout", "place order", "confirm order"}:
        if lowered in {"ready to vend", "vend", "vend now", "checkout", "place order", "confirm order"}:
            quick_intent = "vend_order"
        else:
            quick_intent = "product_list" if "product" in lowered or lowered in {"products", "menu"} else "status"
        _finalize_and_respond(
            intent=quick_intent,
            items=[],
            backend=backend,
            io_client=io_client,
            args=args,
            user_input=user_input,
            telemetry_ctx=telemetry_ctx,
        )
        return False

    # Deterministic local parse first for phrases like "3 nivea and 4 nutties".
    local_intent = _derive_intent_from_text(user_input)
    local_parse_start = time.monotonic()
    local_items = _extract_items_from_text(user_input)
    local_parse_end = time.monotonic()
    if telemetry_ctx is not None:
        telemetry_ctx["local_parse_ms"] = _elapsed_ms(local_parse_start, local_parse_end)
    if local_intent in {"status", "clear_order", "product_list"} or local_items:
        print(f"[PARSED:LOCAL] intent={local_intent}, items={local_items}")
        if telemetry_ctx is not None:
            telemetry_ctx["parse_start_ts"] = local_parse_start
            telemetry_ctx["parse_end_ts"] = local_parse_end
            telemetry_ctx["parse_ms"] = _elapsed_ms(local_parse_start, local_parse_end)
        _finalize_and_respond(
            intent=local_intent,
            items=local_items,
            backend=backend,
            io_client=io_client,
            args=args,
            user_input=user_input,
            telemetry_ctx=telemetry_ctx,
        )
        return False

    try:
        llm_parse_start = time.monotonic()
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
        llm_parse_end = time.monotonic()

        intent, items = _parse_llm_output(llm_result, user_input)
        print(f"[PARSED] intent={intent}, items={items}")
        if telemetry_ctx is not None:
            telemetry_ctx["parse_start_ts"] = llm_parse_start
            telemetry_ctx["parse_end_ts"] = llm_parse_end
            telemetry_ctx["parse_ms"] = _elapsed_ms(llm_parse_start, llm_parse_end)
            telemetry_ctx["llm_parse_ms"] = _elapsed_ms(llm_parse_start, llm_parse_end)
        _finalize_and_respond(
            intent=intent,
            items=items,
            backend=backend,
            io_client=io_client,
            args=args,
            user_input=user_input,
            telemetry_ctx=telemetry_ctx,
        )

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
    parser.add_argument("--dialogue-model", default="", help="Optional model for conversational CRX replies (defaults to parser model)")
    parser.add_argument("--dialogue-temperature", type=float, default=0.7)
    parser.add_argument("--dialogue-timeout", type=float, default=8.0)
    parser.add_argument("--dialogue-max-tokens", type=int, default=120)
    parser.add_argument("--no-dialogue-llm", action="store_true", help="Disable dialogue LLM and use deterministic template replies")
    parser.add_argument("--telemetry-enabled", action="store_true", default=True, help="Enable per-command telemetry CSV logging")
    parser.add_argument("--telemetry-csv", default=str(_default_telemetry_csv_path()), help="CSV path for telemetry rows")

    args = parser.parse_args()
    session_id = uuid.uuid4().hex

    if args.telemetry_enabled:
        try:
            _ensure_telemetry_csv(Path(args.telemetry_csv))
            print(f"Telemetry CSV: {args.telemetry_csv}")
        except Exception as exc:
            print(f"[WARN] Could not initialize telemetry CSV: {exc}")
            args.telemetry_enabled = False

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
    print("  • add to cart: 2 nivea, 1 dove, 3 pringles")
    print("  • add 1 shampoo and 2 noodles")
    print("  • remove 1 dove")
    print("  • clear order")
    print("  • ready to vend")
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
    current_telemetry_ctx: dict[str, object] | None = None

    def _start_telemetry_context(*, raw_text: str, spoken_text: str) -> dict[str, object]:
        now_ts = time.monotonic()
        return {
            "session_id": session_id,
            "command_id": uuid.uuid4().hex,
            "raw_recognized_text": raw_text,
            "spoken_text": spoken_text,
            "first_chunk_ts": now_ts,
        }

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
        nonlocal wake_active, wake_deadline, wake_buffer, current_telemetry_ctx
        with wake_lock:
            command_text = wake_buffer.strip()
            wake_active = False
            wake_deadline = 0.0
            wake_buffer = ""

        if not command_text:
            print("[voice] Wake word heard, but no command captured.")
            return

        print(f"[voice] Executing: {command_text}")
        telemetry_ctx = current_telemetry_ctx
        current_telemetry_ctx = None
        if telemetry_ctx is not None:
            telemetry_ctx["execute_start_ts"] = time.monotonic()

        if _process_command(command_text, args, backend, io_client, schema, prompt, telemetry_ctx=telemetry_ctx):
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
        nonlocal wake_active, wake_deadline, wake_buffer, current_telemetry_ctx
        print(f"\nFinal recognized text: {text}")

        if args.push_to_talk:
            command_text = _extract_voice_command(text)
            if command_text is None:
                return
            telemetry_ctx = _start_telemetry_context(raw_text=text, spoken_text=command_text)
            telemetry_ctx["recording_start_ts"] = telemetry_ctx["first_chunk_ts"]
            telemetry_ctx["wake_accept_ts"] = telemetry_ctx["first_chunk_ts"]
            telemetry_ctx["execute_start_ts"] = time.monotonic()
            if _process_command(command_text, args, backend, io_client, schema, prompt, telemetry_ctx=telemetry_ctx):
                exit_requested.set()
            return

        lowered = text.strip().lower()
        if configured_wake_word and lowered.startswith(configured_wake_word):
            remainder = text[len(configured_wake_word) :].lstrip(" ,:;.-")
            now_ts = time.monotonic()
            with wake_lock:
                wake_active = True
                wake_buffer = remainder
                wake_deadline = time.time() + args.wake_wait_seconds
                current_telemetry_ctx = _start_telemetry_context(raw_text=text, spoken_text=remainder)
                current_telemetry_ctx["wake_accept_ts"] = now_ts
                current_telemetry_ctx["recording_start_ts"] = now_ts
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
            if current_telemetry_ctx is not None:
                current_telemetry_ctx["spoken_text"] = wake_buffer
                existing_raw = str(current_telemetry_ctx.get("raw_recognized_text", "")).strip()
                current_telemetry_ctx["raw_recognized_text"] = f"{existing_raw} | {text}" if existing_raw else text
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
            telemetry_ctx = _start_telemetry_context(raw_text=user_input, spoken_text=user_input)
            telemetry_ctx["recording_start_ts"] = telemetry_ctx["first_chunk_ts"]
            telemetry_ctx["wake_accept_ts"] = telemetry_ctx["first_chunk_ts"]
            telemetry_ctx["execute_start_ts"] = time.monotonic()
            if _process_command(user_input, args, backend, io_client, schema, prompt, telemetry_ctx=telemetry_ctx):
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
