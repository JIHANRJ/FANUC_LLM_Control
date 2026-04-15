"""Entry point for the modular voice-command to robot-action pipeline."""

from __future__ import annotations

import argparse
import threading

from config import MODEL_NAME
from core.parser import ParseError
from core.robot_pipeline import RobotCommandPipeline, startup_preflight_check
from voice import PressToTalkVoiceController


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
    parser.add_argument(
        "--voice",
        dest="voice_enabled",
        action="store_true",
        help="Enable press-and-hold voice input (default).",
    )
    parser.add_argument(
        "--no-voice",
        dest="voice_enabled",
        action="store_false",
        help="Disable voice input and use text-only command entry.",
    )
    parser.set_defaults(voice_enabled=True)
    parser.add_argument(
        "--voice-engine",
        choices=["google", "sphinx"],
        default="google",
        help="Speech recognition engine to use for voice input.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    pipeline = RobotCommandPipeline(model_name=args.model, timeout_seconds=args.timeout)

    print("Local LLM Robot Interface")
    if args.voice_enabled:
        print("Press and hold 'R' to record voice, type 'exit' to quit")
    else:
        print("Text-only mode enabled, type 'exit' to quit")
    print(f"[runtime] model={args.model} timeout={args.timeout}s")
    ready = startup_preflight_check(preferred_model=args.model)
    if not ready:
        print("[startup-check] Preflight failed. Commands may not run until this is fixed.")

    exit_requested = threading.Event()
    voice_controller: PressToTalkVoiceController | None = None

    def process_command(user_text: str) -> bool:
        if user_text.lower() in {"exit", "quit"}:
            print("Exiting.")
            return True
        try:
            result = pipeline.run(user_text)
            print("\nStructured command:")
            print(result["normalized"])
            if "dispatch_result" in result:
                print("\nDispatch result:")
                print(result["dispatch_result"])
        except ParseError as exc:
            print(f"[error] Could not parse LLM output: {exc}")
        except Exception as exc:  # noqa: BLE001
            print(f"[error] {exc}")
        return False

    if args.voice_enabled:
        try:
            voice_controller = PressToTalkVoiceController(
                engine=args.voice_engine,
                on_recording_start=lambda: print("\nRecording... release R to send"),
                on_partial=lambda text: print(f"\nRecognized: {text}"),
                on_error=lambda err: print(f"\n[voice] {err}"),
                on_final=lambda text: (
                    print(f"\nFinal recognized text: {text}"),
                    exit_requested.set() if process_command(text) else None,
                ),
            )
            voice_controller.start()
            print(f"[voice] enabled (engine={args.voice_engine}, hold 'R' to speak)")
        except Exception as exc:  # noqa: BLE001
            print(f"[voice] disabled due to setup failure: {exc}")
            voice_controller = None

    # Fallback text input
    try:
        while True:
            if exit_requested.is_set():
                break
            user_text = input("\nCommand> ").strip()
            if not user_text:
                continue
            if process_command(user_text):
                break
    finally:
        if voice_controller is not None:
            voice_controller.stop()


if __name__ == "__main__":
    main()
