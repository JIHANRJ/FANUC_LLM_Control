"""Orchestrates startup checks and end-to-end command execution."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from config import (
    ACTIVE_ACTION_CATALOG,
    ACTIVE_OUTPUT_SCHEMA,
    FALLBACK_MODEL_NAMES,
    MODEL_NAME,
    OLLAMA_API_URL,
    OLLAMA_TEMPERATURE,
    OLLAMA_TIMEOUT_SECONDS,
    PROMPT_PACK_DIR,
)
from core.action_catalog import load_action_catalog
from core.dispatcher import dispatch_command
from core.normalizer import normalize_command
from core.prompt_pack_loader import load_prompt_pack
from core.validator import validate_command
from llm.prompt_builder import build_prompt
from llm.robot_control_llm import RobotControlLLM
from schemas.registry import get_output_schema


def _build_tags_url() -> str:
    if OLLAMA_API_URL.endswith("/generate"):
        return OLLAMA_API_URL[: -len("/generate")] + "/tags"
    return OLLAMA_API_URL.rsplit("/", 1)[0] + "/tags"


def startup_preflight_check(preferred_model: str | None = None) -> bool:
    """Check Ollama availability and model/schema/tool assets."""
    tags_url = _build_tags_url()
    expected_models = [preferred_model or MODEL_NAME]
    expected_models.extend([name for name in FALLBACK_MODEL_NAMES if name != MODEL_NAME])

    try:
        with urlopen(tags_url, timeout=5.0) as response:
            raw = response.read().decode("utf-8")
    except URLError as exc:
        print("[startup-check] Ollama is not reachable.")
        print(f"[startup-check] Endpoint: {OLLAMA_API_URL}")
        print("[startup-check] Fix: start server with 'ollama serve'.")
        print(f"[startup-check] Details: {exc}")
        return False
    except HTTPError as exc:
        print(f"[startup-check] Ollama returned HTTP {exc.code} at {tags_url}.")
        print("[startup-check] Fix: verify Ollama server is healthy and accessible.")
        return False

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print("[startup-check] Could not parse Ollama model list response.")
        print(f"[startup-check] Details: {exc}")
        return False

    available_models = {
        item.get("name", "")
        for item in data.get("models", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }

    selected = next((name for name in expected_models if name in available_models), None)
    if selected is None:
        print("[startup-check] No compatible model is available locally.")
        print(f"[startup-check] Expected one of: {expected_models}")
        print("[startup-check] Fix: pull model with 'ollama pull llama3.1:8b' or update config.")
        if available_models:
            print(f"[startup-check] Available models: {sorted(available_models)}")
        return False

    print(f"[startup-check] Ollama reachable. Using model route: {selected}")

    try:
        schema = get_output_schema(ACTIVE_OUTPUT_SCHEMA)
        print(f"[startup-check] Loaded output schema: {schema.name}")
    except Exception as exc:  # noqa: BLE001
        print(f"[startup-check] Failed to load output schema {ACTIVE_OUTPUT_SCHEMA!r}: {exc}")
        return False

    try:
        actions = load_action_catalog(ACTIVE_ACTION_CATALOG)
        print(f"[startup-check] Loaded action catalog: {ACTIVE_ACTION_CATALOG} ({len(actions)} action(s))")
    except Exception as exc:  # noqa: BLE001
        print(f"[startup-check] Failed to load action catalog {ACTIVE_ACTION_CATALOG!r}: {exc}")
        return False

    try:
        for action in actions:
            load_prompt_pack(PROMPT_PACK_DIR, action.prompt_pack)
        print(f"[startup-check] Loaded prompt packs from: {PROMPT_PACK_DIR}")
    except Exception as exc:  # noqa: BLE001
        print(f"[startup-check] Failed to load prompt packs from {PROMPT_PACK_DIR!r}: {exc}")
        return False

    return True


class RobotCommandPipeline:
    """High-level pipeline that converts text into validated dispatch actions."""

    def __init__(self, model_name: str | None = None, timeout_seconds: float | None = None) -> None:
        self.model_name = model_name or MODEL_NAME
        self.timeout_seconds = timeout_seconds or OLLAMA_TIMEOUT_SECONDS

    def run(self, user_text: str) -> dict[str, object]:
        prompt = build_prompt(user_text)
        schema = get_output_schema(ACTIVE_OUTPUT_SCHEMA)

        parsed = RobotControlLLM.PromptCommand(
            model_name=self.model_name,
            model_parameters={
                "temperature": OLLAMA_TEMPERATURE,
                "stream": False,
                "timeout_seconds": self.timeout_seconds,
            },
            prompt=prompt,
            output_json=schema.json_schema,
        )

        normalized = normalize_command(parsed)
        is_valid, message = validate_command(normalized)
        if not is_valid:
            raise ValueError(f"Validation failed: {message}")

        result = dispatch_command(normalized)
        return {
            "parsed": parsed,
            "normalized": normalized,
            "dispatch_result": result,
        }
