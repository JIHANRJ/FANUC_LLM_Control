"""Simple playground for testing RobotControlLLM.TextCommand"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from llm.robot_control_llm import RobotControlLLM
from actions import move_joint_action
from actions import ros2_modular_joint_demo_action


def main() -> None:
    parser = argparse.ArgumentParser(description="Test RobotControlLLM.TextCommand")
    parser.add_argument("model", nargs="?", default="llama3.1:8b", help="Ollama model name")
    parser.add_argument("--prompt", default="move joint 1 by 30 degrees", help="Input prompt")
    parser.add_argument(
        "--action",
        choices=["move_joint", "ros2_demo"],
        default="move_joint",
        help="Action target: local simulator or ROS2 VM modular demo",
    )
    args = parser.parse_args()

    if args.action == "ros2_demo":
        output_schema = {
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
    else:
        output_schema = {
            "command_name": "string",
            "parameters": {"joint": "integer", "delta": "number"},
        }

    # Call TextCommand to parse and normalize
    result = RobotControlLLM.TextCommand(
        model_name=args.model,
        model_parameters={"temperature": 0.1, "stream": False, "timeout_seconds": 60},
        output_json=output_schema,
        prompt=args.prompt,
    )

    # Print parsing result
    print("\n=== Parsed & Normalized ===")
    print(json.dumps(result, indent=2))

    # Call action directly
    normalized = result.get("normalized_output", {})
    parameters = normalized.get("parameters", {})
    
    print(f"\n=== Executing Action ({args.action}) ===")
    try:
        if args.action == "ros2_demo":
            action_result = ros2_modular_joint_demo_action.execute(parameters)
        else:
            action_result = move_joint_action.execute(parameters)
        print(json.dumps(action_result, indent=2))
    except Exception as e:
        print(f"Action error: {e}")


if __name__ == "__main__":
    main()
