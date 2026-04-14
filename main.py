"""Entry point for the modular voice-command to robot-action pipeline."""

from __future__ import annotations

import argparse
import threading

import speech_recognition as sr
from pynput import keyboard

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

    print("Local LLM Robot Interface (press and hold 'R' to record voice, type 'exit' to quit)")
    print(f"[runtime] model={args.model} timeout={args.timeout}s")
    ready = startup_preflight_check(preferred_model=args.model)
    if not ready:
        print("[startup-check] Preflight failed. Commands may not run until this is fixed.")

    # Voice setup
    recognizer = sr.Recognizer()
    microphone = sr.Microphone(sample_rate=16000)
    partial_transcript: list[str] = []
    recording = False
    recording_thread: threading.Thread | None = None
    stop_recording = threading.Event()

    def record_audio() -> None:
        nonlocal partial_transcript
        with microphone as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            while recording and not stop_recording.is_set():
                try:
                    audio = recognizer.listen(source, timeout=0.5, phrase_time_limit=3)
                except sr.WaitTimeoutError:
                    continue

                try:
                    chunk_text = recognizer.recognize_google(audio)
                    partial_transcript.append(chunk_text)
                    print(f"\nRecognized: {' '.join(partial_transcript)}")
                except sr.UnknownValueError:
                    continue
                except sr.RequestError as exc:
                    print(f"\n[voice] recognition request failed: {exc}")
                    break

    def on_press(key):
        nonlocal recording, recording_thread, partial_transcript
        try:
            if key.char == "r" and not recording:
                recording = True
                stop_recording.clear()
                partial_transcript = []
                print("\nRecording... release R to send")
                recording_thread = threading.Thread(target=record_audio, daemon=True)
                recording_thread.start()
        except AttributeError:
            pass

    def on_release(key):
        nonlocal recording, recording_thread, partial_transcript
        try:
            if key.char == "r" and recording:
                recording = False
                stop_recording.set()
                if recording_thread is not None:
                    recording_thread.join()
                full_text = " ".join(partial_transcript).strip()
                if not full_text:
                    print("\nCould not understand audio")
                    return
                print(f"\nFinal recognized text: {full_text}")
                process_command(full_text)
        except AttributeError:
            pass

    listener = keyboard.Listener(on_press=on_press, on_release=on_release, suppress=True)
    listener.start()

    def process_command(user_text):
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

    # Fallback text input
    while True:
        user_text = input("\nCommand> ").strip()
        if not user_text:
            continue
        if process_command(user_text):
            break


if __name__ == "__main__":
    main()
