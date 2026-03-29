"""Entry point for the modular voice-command to robot-action pipeline."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from config import FALLBACK_MODEL_NAMES, MODEL_NAME, OLLAMA_API_URL
from core.dispatcher import dispatch_command
from core.normalizer import normalize_command
from core.parser import ParseError, safely_parse_json
from core.validator import validate_command
from llm.ollama_interface import OllamaInterface


def _build_tags_url() -> str:
    if OLLAMA_API_URL.endswith("/generate"):
        return OLLAMA_API_URL[: -len("/generate")] + "/tags"
    return OLLAMA_API_URL.rsplit("/", 1)[0] + "/tags"


def startup_preflight_check() -> bool:
    """Check Ollama availability and model presence before accepting commands."""
    tags_url = _build_tags_url()
    expected_models = [MODEL_NAME]
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
    return True


def run_pipeline(user_text: str) -> dict[str, object]:
    """Execute the complete NLP-to-action safety pipeline."""
    llm = OllamaInterface()

    # 1) Read user input (provided as user_text)
    # 2) Call LLM
    llm_output = llm.parse(user_text)

    # 3) Parse JSON safely
    parsed = safely_parse_json(llm_output)

    # 4) Normalize
    normalized = normalize_command(parsed)

    # 5) Validate
    is_valid, message = validate_command(normalized)
    if not is_valid:
        raise ValueError(f"Validation failed: {message}")

    # 6) Dispatch action
    result = dispatch_command(normalized)

    return {
        "parsed": parsed,
        "normalized": normalized,
        "dispatch_result": result,
    }


def main() -> None:
    print("Local LLM Robot Interface (type 'exit' to quit)")
    ready = startup_preflight_check()
    if not ready:
        print("[startup-check] Preflight failed. Commands may not run until this is fixed.")

    while True:
        user_text = input("\nCommand> ").strip()
        if not user_text:
            continue

        if user_text.lower() in {"exit", "quit"}:
            print("Exiting.")
            break

        try:
            result = run_pipeline(user_text)
            print("\nStructured command:")
            print(result["normalized"])
            print("\nDispatch result:")
            print(result["dispatch_result"])
        except ParseError as exc:
            print(f"[error] Could not parse LLM output: {exc}")
        except Exception as exc:  # noqa: BLE001
            print(f"[error] {exc}")


if __name__ == "__main__":
    main()
