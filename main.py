"""Entry point for the modular voice-command to robot-action pipeline."""

from __future__ import annotations

import argparse

from config import MODEL_NAME
from core.parser import ParseError
from core.robot_pipeline import RobotCommandPipeline, startup_preflight_check


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local LLM Robot Interface")
    parser.add_argument(
        "--model",
        default=MODEL_NAME,
        help=f"Ollama model tag to use (default: {MODEL_NAME})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Ollama request timeout in seconds (default: 20.0)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    pipeline = RobotCommandPipeline(model_name=args.model, timeout_seconds=args.timeout)

    print("Local LLM Robot Interface (type 'exit' to quit)")
    print(f"[runtime] model={args.model} timeout={args.timeout}s")
    ready = startup_preflight_check(preferred_model=args.model)
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
            result = pipeline.run(user_text)
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
