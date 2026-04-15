"""Standalone press-to-talk voice capture test harness."""

from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from voice import PressToTalkVoiceController


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Standalone voice capture test")
    parser.add_argument(
        "--engine",
        choices=["whisper", "sphinx", "google"],
        default="whisper",
        help="Speech recognition engine for voice capture.",
    )
    parser.add_argument(
        "--whisper-model",
        default="small",
        help="Whisper model size (tiny, base, small, medium, large-v3, etc.).",
    )
    parser.add_argument(
        "--whisper-compute-type",
        default="int8",
        help="Whisper compute type (int8, float16, float32).",
    )
    parser.add_argument(
        "--whisper-device",
        default="cpu",
        help="Whisper device (cpu or cuda).",
    )
    parser.add_argument(
        "--whisper-language",
        default="en",
        help="Language hint for Whisper (set to auto for no hint).",
    )
    parser.add_argument(
        "--trigger-key",
        default="r",
        help="Press-and-hold key used to record audio.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    exit_requested = threading.Event()

    def handle_final(text: str) -> None:
        print(f"\nFinal recognized text: {text}")
        if text.strip().lower() in {"exit", "quit"}:
            exit_requested.set()

    controller = PressToTalkVoiceController(
        trigger_key=args.trigger_key,
        engine=args.engine,
        whisper_model_size=args.whisper_model,
        whisper_compute_type=args.whisper_compute_type,
        whisper_device=args.whisper_device,
        whisper_language=None if args.whisper_language.lower() == "auto" else args.whisper_language,
        on_recording_start=lambda: print("\nRecording... release key to send"),
        on_partial=lambda text: print(f"\nRecognized: {text}"),
        on_error=lambda err: print(f"\n[voice] {err}"),
        on_final=handle_final,
    )

    controller.start()
    print("Voice capture test started.")
    print(f"Engine: {args.engine}")
    print(f"Trigger key: {args.trigger_key}")
    print("Press and hold trigger key to record. Say or type 'exit' to quit.")

    try:
        while not exit_requested.is_set():
            user_text = input("\nText fallback> ").strip()
            if user_text.lower() in {"exit", "quit"}:
                break
            if user_text:
                print(f"Typed text: {user_text}")
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    finally:
        controller.stop()


if __name__ == "__main__":
    main()
