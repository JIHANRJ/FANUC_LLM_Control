"""Interactive chat loop for RobotControlLLM.TextCommand."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from actions import move_joint_action
from actions import ros2_modular_joint_demo_action
from llm.robot_control_llm import RobotControlLLM


def _build_output_schema(action: str) -> dict[str, object]:
    if action == "ros2_demo":
        return {
            "command_name": "string",
            "parameters": {
                "joint": "integer",
                "delta": "number",
                "planning_group": "string",
                "vel": "number",
                "acc": "number",
                "startup_delay": "number",
                "target_deg": {
                    "joint_1": "number",
                    "joint_2": "number",
                    "joint_3": "number",
                    "joint_4": "number",
                    "joint_5": "number",
                    "joint_6": "number",
                },
            },
        }

    return {
        "command_name": "string",
        "parameters": {"joint": "integer", "delta": "number"},
    }


def _execute_action(action: str, parameters: dict[str, object]) -> dict[str, object]:
    if action == "ros2_demo":
        return ros2_modular_joint_demo_action.execute(parameters)
    return move_joint_action.execute(parameters)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactive RobotControlLLM chat")
    parser.add_argument("model", nargs="?", default="llama3.1:8b", help="Ollama model name")
    parser.add_argument(
        "--action",
        choices=["move_joint", "ros2_demo"],
        default="move_joint",
        help="Action target: local simulator or ROS2 VM modular demo",
    )
    parser.add_argument("--temperature", type=float, default=0.1, help="Model temperature")
    parser.add_argument("--timeout", type=float, default=60.0, help="Request timeout seconds")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    output_schema = _build_output_schema(args.action)

    print("Interactive Robot Chat")
    print(f"model={args.model} action={args.action}")
    print("Type a command, or 'exit' to quit.")

    while True:
        user_text = input("\nYou> ").strip()
        if not user_text:
            continue
        if user_text.lower() in {"exit", "quit"}:
            print("Bye.")
            break

        try:
            result = RobotControlLLM.TextCommand(
                model_name=args.model,
                model_parameters={
                    "temperature": args.temperature,
                    "stream": False,
                    "timeout_seconds": args.timeout,
                },
                output_json=output_schema,
                prompt=user_text,
            )

            normalized = result.get("normalized_output", {})
            parameters = normalized.get("parameters", {})
            if not isinstance(parameters, dict):
                raise ValueError("normalized_output.parameters must be an object")

            action_result = _execute_action(args.action, parameters)
            print("\nParsed:")
            print(json.dumps(result.get("normalized_output", {}), indent=2))
            print("\nExecution:")
            print(json.dumps(action_result, indent=2))
        except ConnectionError as exc:
            print(f"Error: {exc}")
            print("Hint: run 'ollama serve' in another terminal, or export OLLAMA_API_URL if Ollama is remote.")
        except Exception as exc:  # noqa: BLE001
            print(f"Error: {exc}")


if __name__ == "__main__":
    main()
