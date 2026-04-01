"""Simple playground for RobotControlLMM.TextCommand with optional execution."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from llm.robot_control_llm import RobotControlLMM
    from actions import move_joint_action
    from core.dispatcher import dispatch_command
except ModuleNotFoundError:
    # Support direct execution from inside pit folder.
    from robot_control_llm import RobotControlLMM


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PIT test for RobotControlLMM.TextCommand")
    parser.add_argument("model", nargs="?", default="llama3.1:8b", help="Ollama model name")
    parser.add_argument(
        "--function",
        choices=["none", "dispatcher", "move_joint"],
        default="none",
        help="How to execute after parsing: none (parse only), dispatcher (route by command_name), move_joint (call move_joint directly)",
    )
    parser.add_argument(
        "--prompt",
        default="move joint one by 30 degrees",
        help="Input prompt text",
    )
    return parser.parse_args()


def _build_execute_fn(mode: str):
    if mode == "none":
        return None

    if mode == "dispatcher":
        return dispatch_command

    if mode == "move_joint":
        def _run_move_joint(command: dict[str, object]) -> dict[str, object]:
            parameters = command.get("parameters")
            if not isinstance(parameters, dict):
                raise ValueError("Expected command with object 'parameters'.")
            return move_joint_action.execute(parameters)

        return _run_move_joint

    raise ValueError(f"Unsupported function mode: {mode}")


def main() -> None:
    args = _parse_args()
    execute_fn = _build_execute_fn(args.function)

    output_schema = {
        "command_name": "string",
        "parameters": {
            "joint": "integer",
            "delta": "number",
        },
    }

    try:
        result = RobotControlLMM.TextCommand(
            model_name=args.model,
            model_parameters={
                "temperature": 0.1,
                "stream": False,
                "timeout_seconds": 60,
            },
            output_json=output_schema,
            prompt=args.prompt,
            execute=execute_fn,
        )
        print(json.dumps(result, indent=2))
    except TimeoutError as exc:
        print(f"[pit-test] {exc}")
        print("[pit-test] Hint: use a higher timeout_seconds for heavier models.")
    except ConnectionError as exc:
        print(f"[pit-test] {exc}")
        print("[pit-test] Start Ollama first: ollama serve")


if __name__ == "__main__":
    main()
