"""
Integrated LLM-based I/O controller for FANUC robot.
Combines natural language understanding with robot I/O control.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path
from typing import Optional

# Add parent directory and demo directory to path for imports
DEMO_ROOT = Path(__file__).resolve().parent
REPO_ROOT = DEMO_ROOT.parents[0]
for path in (str(DEMO_ROOT), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from llm.robot_control_llm import RobotControlLLM

# Import fanuc_io_control only if ROS2 is available
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


# Box/Target configuration
BOX_CONFIG = {
    "red": {"output": "RO", "pin": 1, "description": "Red Box"},
    "blue": {"output": "RO", "pin": 2, "description": "Blue Box"},
    "home": {"output": None, "pin": None, "description": "Home Position (all RO off)"},
}

# Track current state
CURRENT_STATE = {"active_output": None, "active_pin": None}

# Color keywords to recognize
COLOR_KEYWORDS = {
    "red": ["red", "rouge"],
    "blue": ["blue", "bleu"],
    "home": ["home", "start", "initial", "rest"],
}


def _normalize_target(raw_target: str) -> Optional[str]:
    """
    Extract target name from raw LLM output.
    Handles variations like "red_box", "red box", "red", etc.
    """
    if not raw_target:
        return None
    
    target = raw_target.lower().strip().strip(".,;:!?")
    
    # Direct match
    if target in BOX_CONFIG:
        return target
    
    # Remove common suffixes
    for suffix in ["_box", " box", "_pin", " pin", " position", "_position"]:
        if target.endswith(suffix):
            target = target[: -len(suffix)].strip()
    
    # Try again after removing suffix
    if target in BOX_CONFIG:
        return target
    
    # Exact keyword matching only; the LLM should do the semantic interpretation.
    for color, keywords in COLOR_KEYWORDS.items():
        for keyword in keywords:
            if target == keyword and color in BOX_CONFIG:
                return color
    
    return None


def _build_io_schema() -> dict:
    """Build JSON schema for LLM to understand box targets."""
    return {
        "commands": [
            {
                "target": "string",  # ONLY: red, blue, or home - nothing else
                "description": "string",
            }
        ]
    }


def _get_io_schema_prompt() -> str:
        """Get detailed prompt to help LLM understand targets."""
        return """You are the primary natural-language interpreter for a FANUC I/O controller.

Your job is to read a normal English sentence and infer ALL intended robot destinations mentioned in the complete input.

CRITICAL: Sequences can repeat. For example:
- "red then blue then home then blue then home again" means: go to red, go to blue, go home, go to blue AGAIN, go home AGAIN.
You MUST return ALL five commands in order: [red, blue, home, blue, home]

Do not require the user to speak in keywords. Understand phrases like:
- "move to the red box on the side"
- "go to blue"
- "take me home"
- "send it to the red station"

Supported destinations are only: red, blue, home.

CRITICAL PARSING RULES:
1. Parse the ENTIRE input from start to finish. NEVER stop early.
2. Return ALL destinations mentioned, INCLUDING repeats, in the order they appear.
3. When you see "then" or "next", there's ANOTHER command coming - keep parsing.
4. Commands CAN repeat. Red can appear twice, blue twice, or any combination.
5. Use the meaning of the sentence, not just exact words.
6. Map red destination to "red", blue to "blue", return/reset to "home".
7. Ignore filler words like "the", "box", "side", "robot", "please".
8. EXHAUST the entire input before returning JSON.

Return only valid JSON in this exact shape:
{
    "commands": [
        {
            "target": "red",
            "description": "short natural-language summary of the user's intent"
        }
    ]
}

Examples (including repeats):
- "red" → {"commands":[{"target":"red"}]}
- "red then blue" → {"commands":[{"target":"red"},{"target":"blue"}]}
- "red then blue then home" → {"commands":[{"target":"red"},{"target":"blue"},{"target":"home"}]}
- "red then blue then home then blue" → {"commands":[{"target":"red"},{"target":"blue"},{"target":"home"},{"target":"blue"}]}
- "red then blue then home then blue then home" → {"commands":[{"target":"red"},{"target":"blue"},{"target":"home"},{"target":"blue"},{"target":"home"}]}
- "red then blue then home then blue then home again" → {"commands":[{"target":"red"},{"target":"blue"},{"target":"home"},{"target":"blue"},{"target":"home"}]}
- "move to red, then go to blue, then home, then back to blue, then home again" → {"commands":[{"target":"red"},{"target":"blue"},{"target":"home"},{"target":"blue"},{"target":"home"}]}
- "blue red home red blue" → {"commands":[{"target":"blue"},{"target":"red"},{"target":"home"},{"target":"red"},{"target":"blue"}]}
"""


def _validate_io_connection(io_client: FanucIOClient) -> tuple[bool, str]:
    """Validate the ROS2 FANUC I/O connection before chat begins."""
    try:
        test_value = io_client.read_io("RO", 1)
        if test_value is None:
            return False, "Unable to read RO1 from FANUC I/O service."
        return True, "FANUC I/O service is available."
    except Exception as exc:
        return False, f"FANUC I/O validation failed: {exc}"


def _execute_io_command(target: str, io_client: Optional[FanucIOClient] = None) -> dict:
    """
    Execute I/O command based on target.
    Returns status dictionary.
    """
    target = target.lower().strip()
    
    # Parse target (e.g., "red_box" -> "red")
    target_key = target.replace("_box", "").replace(" box", "").strip()
    
    if target_key not in BOX_CONFIG:
        return {
            "success": False,
            "message": f"Unknown target: {target}. Available: {', '.join(BOX_CONFIG.keys())}",
        }
    
    config = BOX_CONFIG[target_key]
    
    # Home position: turn off all RO outputs
    if target_key == "home":
        if not ROS2_AVAILABLE or io_client is None:
            # Simulation mode
            CURRENT_STATE["active_output"] = None
            CURRENT_STATE["active_pin"] = None
            return {
                "success": True,
                "message": "[HOME] Home position set (all RO outputs OFF) [SIM MODE]",
                "current_state": CURRENT_STATE.copy(),
            }
        else:
            # Real mode - turn off both RO1 and RO2
            try:
                io_client.write_io("RO", 1, False)
                io_client.write_io("RO", 2, False)
                CURRENT_STATE["active_output"] = None
                CURRENT_STATE["active_pin"] = None
                return {
                    "success": True,
                    "message": "[HOME] Home position set (all RO outputs OFF)",
                    "current_state": CURRENT_STATE.copy(),
                }
            except Exception as e:
                return {
                    "success": False,
                    "message": f"Failed to set home position: {e}",
                }
    
    # Box target: activate only one output at a time
    output_type = config["output"]
    pin = config["pin"]
    description = config["description"]
    
    if not ROS2_AVAILABLE or io_client is None:
        # Simulation mode
        CURRENT_STATE["active_output"] = f"{output_type}{pin}"
        CURRENT_STATE["active_pin"] = pin
        return {
            "success": True,
            "message": f"[OK] Moving to {description} ({output_type}{pin} ON) [SIM MODE]",
            "current_state": CURRENT_STATE.copy(),
        }
    else:
        # Real mode - turn off previous output, turn on new output
        try:
            # Turn off all other RO pins first (ensure only one is active)
            for key, cfg in BOX_CONFIG.items():
                if key != "home" and cfg["pin"] is not None and cfg["pin"] != pin:
                    io_client.write_io("RO", cfg["pin"], False)
            
            # Turn on the target output
            io_client.write_io(output_type, pin, True)
            
            CURRENT_STATE["active_output"] = f"{output_type}{pin}"
            CURRENT_STATE["active_pin"] = pin
            
            return {
                "success": True,
                "message": f"[OK] Moving to {description} ({output_type}{pin} ON)",
                "current_state": CURRENT_STATE.copy(),
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Failed to execute I/O command: {e}",
            }


def _parse_llm_response(llm_output: dict) -> list[str]:
    """
    Extract targets from LLM response.
    Returns list of normalized targets.
    """
    targets = []
    
    try:
        normalized = llm_output.get("normalized_output", {})
        
        # Handle new schema format (commands list)
        if isinstance(normalized, dict):
            commands = normalized.get("commands", [])
            if isinstance(commands, list):
                for cmd in commands:
                    if isinstance(cmd, dict):
                        raw_target = cmd.get("target")
                        normalized_target = _normalize_target(raw_target)
                        if normalized_target:
                            targets.append(normalized_target)
            else:
                # Single target format
                raw_target = normalized.get("target")
                normalized_target = _normalize_target(raw_target)
                if normalized_target:
                    targets.append(normalized_target)
        
        # Fallback to parsed output
        if not targets:
            parsed = llm_output.get("parsed_output", {})
            if isinstance(parsed, dict):
                # Try commands format
                commands = parsed.get("commands", [])
                if isinstance(commands, list):
                    for cmd in commands:
                        if isinstance(cmd, dict):
                            raw_target = cmd.get("target")
                            normalized_target = _normalize_target(raw_target)
                            if normalized_target:
                                targets.append(normalized_target)
                else:
                    # Single target format
                    raw_target = parsed.get("target")
                    normalized_target = _normalize_target(raw_target)
                    if normalized_target:
                        targets.append(normalized_target)
    except Exception as e:
        print(f"Debug: Error parsing LLM response: {e}")
    
    return targets


def _process_command(
    user_input: str,
    args: argparse.Namespace,
    io_client: Optional[FanucIOClient],
    schema: dict,
    schema_prompt: str,
) -> bool:
    if not user_input:
        return False

    if user_input.lower() in {"exit", "quit"}:
        print("Goodbye!")
        return True

    if user_input.lower() == "status":
        print(f"Current state: {CURRENT_STATE}")
        print(f"Active output: {CURRENT_STATE['active_output'] or 'None'}")
        return False

    print("[INFO] Processing with LLM...")
    try:
        llm_result = RobotControlLLM.TextCommand(
            model_name=args.model,
            model_parameters={
                "temperature": args.temperature,
                "stream": False,
                "timeout_seconds": args.timeout,
                "num_predict": 1024,  # Allow longer sequences with multiple commands
                "top_k": 40,  # Control diversity in generation
                "top_p": 0.9,  # Nucleus sampling for better quality
            },
            output_json=schema,
            prompt=schema_prompt + f"\nUser input: {user_input}\nOutput:",
        )

        targets = _parse_llm_response(llm_result)
        if not targets:
            print("[ERROR] Could not parse any targets from your command.")
            print("Please try: 'move to red box', 'go to blue box', 'move home'")
            print("Or combine: 'red then blue then home'")
            return False

        print(f"\n[PARSED] {len(targets)} target(s): {', '.join(targets)}")
        for i, target in enumerate(targets, 1):
            if len(targets) > 1:
                print(f"\n  Step {i}/{len(targets)}: Moving to {target}")
            result = _execute_io_command(target, io_client)
            print(result["message"])
            if not result["success"]:
                print(f"  Error: {result.get('message', 'Unknown error')}")
                break
            # Wait between commands to allow robot to execute
            if i < len(targets):
                time.sleep(args.command_delay)

    except ConnectionError as exc:
        print(f"[ERROR] Connection error: {exc}")
        print("Hint: Ensure 'ollama serve' is running in another terminal.")
    except Exception as exc:
        print(f"[ERROR] Error: {exc}")

    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM-based I/O controller for FANUC robot")
    parser.add_argument("model", nargs="?", default="llama3.1:8b", help="Ollama model name")
    parser.add_argument("--temperature", type=float, default=0.1, help="Model temperature")
    parser.add_argument("--timeout", type=float, default=60.0, help="Request timeout seconds")
    parser.add_argument("--simulation", action="store_true", help="Run in simulation mode (no ROS2)")
    parser.add_argument("--voice", action="store_true", help="Enable press-and-hold R voice input")
    parser.add_argument("--command-delay", type=float, default=2.0, help="Delay in seconds between command executions")
    args = parser.parse_args()

    # Initialize ROS2 and I/O client if not in simulation mode
    io_client = None
    if not args.simulation:
        if not ROS2_AVAILABLE:
            print("[ERROR] ROS2 is not available in this Python environment.")
            if fanuc_import_error is not None:
                print(f"Import error: {fanuc_import_error}")
            print("Run with --simulation if you do not have a ROS2 FANUC I/O connection.")
            raise SystemExit(1)

        if not FANUC_IO_AVAILABLE:
            print("[ERROR] FANUC I/O client import failed.")
            if fanuc_import_error is not None:
                print(f"Import error: {fanuc_import_error}")
            print("Ensure the demo folder can import fanuc_io_control and its dependencies.")
            print("Run with --simulation if you want to use the demo without ROS2.")
            raise SystemExit(1)

        try:
            rclpy.init()
            io_client = FanucIOClient()
        except Exception as e:
            print(f"[ERROR] Could not initialize ROS2 I/O client: {e}")
            print("Ensure ROS2 is running and FANUC I/O services are available.")
            print("Run with --simulation if you want to use the demo without ROS2.")
            raise SystemExit(1)

        valid, message = _validate_io_connection(io_client)
        if not valid:
            print(f"[ERROR] {message}")
            print("Ensure the FANUC I/O service is available and reachable before starting the chat.")
            print("Run with --simulation to continue without real hardware.")
            raise SystemExit(1)
        print(f"[OK] {message}")

    schema = _build_io_schema()
    schema_prompt = _get_io_schema_prompt()

    print("\n" + "=" * 70)
    print("  LLM-based FANUC I/O Controller")
    print("=" * 70)
    print(f"Model: {args.model}")
    print(f"Mode: {'SIMULATION' if args.simulation else 'REAL'}")
    print("\nAvailable targets:")
    for key, config in BOX_CONFIG.items():
        print(f"  • {key}: {config['description']}")
    print("\nExample commands:")
    print("  • Move to red box")
    print("  • Go to blue box in the corner")
    print("  • Move to red then blue then home")
    print("  • Red box and then blue box, finally home")
    print("-" * 70)
    print("Type 'status' to see current state, 'exit' to quit.")
    if args.voice:
        print("Press and hold R to record voice, release to send.")
    print()

    voice_listener = None
    exit_requested = threading.Event()

    if args.voice:
        try:
            import speech_recognition as sr
            from pynput import keyboard
        except ImportError as exc:
            print("[ERROR] Voice mode requires SpeechRecognition and pynput.")
            print("Install with: python3 -m pip install SpeechRecognition pynput")
            raise SystemExit(1)

        try:
            recognizer = sr.Recognizer()
            microphone = sr.Microphone(sample_rate=16000)
        except Exception as exc:
            print(f"[ERROR] Could not initialize microphone: {exc}")
            raise SystemExit(1)

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
                        if chunk_text:
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
                    partial_transcript = []
                    stop_recording.clear()
                    print("\nRecording... release R to send")
                    recording_thread = threading.Thread(target=record_audio, daemon=True)
                    recording_thread.start()
            except AttributeError:
                pass

        def on_release(key):
            nonlocal recording, recording_thread
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
                    if _process_command(full_text, args, io_client, schema, schema_prompt):
                        exit_requested.set()
            except AttributeError:
                pass

        voice_listener = keyboard.Listener(on_press=on_press, on_release=on_release, suppress=True)
        voice_listener.start()

    try:
        while True:
            if exit_requested.is_set():
                break

            user_input = input("You> ").strip()
            if _process_command(user_input, args, io_client, schema, schema_prompt):
                break

            if exit_requested.is_set():
                break

    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
    finally:
        if voice_listener is not None:
            stop_recording.set()
            voice_listener.stop()
            if recording_thread is not None:
                recording_thread.join(timeout=1)

        if io_client is not None:
            try:
                io_client.destroy_node()
                rclpy.try_shutdown()
            except Exception as e:
                print(f"Cleanup warning: {e}")


if __name__ == "__main__":
    main()
