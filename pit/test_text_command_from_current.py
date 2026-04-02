"""Interactive chat: parse command and move from current robot state."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from actions import ros2_move_from_current_action
from llm.robot_control_llm import RobotControlLLM


OUTPUT_SCHEMA: dict[str, object] = {
    "command_name": "string",
    "parameters": {
                "mode": "string (single_joint_delta | multi_joint_delta | all_joints_zero)",
                "joints": "JSON array of integers",
        "delta": "number",
        "planning_group": "string",
        "vel": "number",
        "acc": "number",
        "startup_delay": "number",
    },
}


PROMPT_PREFIX = """
You are a robot motion command parser for a current-state move action.

Your job:
- Read the user command.
- Fill in the JSON fields below.
- Return ONLY valid JSON.
- Do not add markdown, explanation, or extra keys.

Fill rules:
- If the user names one joint, put that joint in `joint` or `joints`.
- Always prefer `joints` as a JSON array of integers.
- If the user names one joint, set `joints` to a one-item array like [2].
- If the user names multiple joints, put them in `joints` as a JSON array of integers.
- If the user says "all joints" or "back to zero", set `mode` to `all_joints_zero` and set `joints` to [1,2,3,4,5,6].
- If the user says move specific joints by the same amount, use `mode` = `multi_joint_delta` and list those joints in `joints`.
- If the user says move one joint by some degrees, use `mode` = `single_joint_delta` and set `joints` to a one-item array.
- Use `delta` in degrees.
- Use `planning_group` = `manipulator` unless the user says otherwise.
- If the user gives speed/acceleration, fill `vel` and `acc`; otherwise use safe defaults.
- Never infer `vel` or `acc` from the move amount. If the user only says how far to move, keep `vel` and `acc` at safe defaults.
- Keep `vel` and `acc` in the range 0.0 to 1.0.

Examples:
- "move joint 2 by 3 degrees" -> mode=single_joint_delta, joints=[2], delta=3
- "move joints 1, 2 and 3 by 60 degrees" -> mode=multi_joint_delta, joints=[1,2,3], delta=60
- "rotate joint 1, 2, 3 by 180" -> mode=multi_joint_delta, joints=[1,2,3], delta=180
- "move all joints back to zero degrees" -> mode=all_joints_zero, joints=[1,2,3,4,5,6], delta=0

Output contract:
{
    "command_name": "string",
    "parameters": {
        "mode": "single_joint_delta | multi_joint_delta | all_joints_zero",
        "joints": "array of integers",
        "delta": "number",
        "planning_group": "string",
        "vel": "number",
        "acc": "number",
        "startup_delay": "number"
    }
}
""".strip()


def _resolve_timeout(model: str, requested_timeout: float | None) -> float:
    if requested_timeout is not None:
        return requested_timeout
    lowered = model.lower()
    if "gpt-oss" in lowered or "20b" in lowered:
        return 240.0
    return 100.0


def _run_once(model: str, prompt: str, temperature: float, timeout: float) -> None:
    try:
        result = RobotControlLLM.TextCommand(
            model_name=model,
            model_parameters={"temperature": temperature, "stream": False, "timeout_seconds": timeout},
            output_json=OUTPUT_SCHEMA,
            prompt=f"{PROMPT_PREFIX}\n\nUser command: {prompt}",
        )
    except ConnectionError as exc:
        print(f"\nLLM connection error: {exc}")
        print("Hint: run 'ollama serve' in another terminal, or export OLLAMA_API_URL if Ollama is remote.")
        return
    except TimeoutError as exc:
        print(f"\nLLM timeout: {exc}")
        print("Hint: use a higher timeout, e.g. --timeout 300 for heavier models.")
        return
    except Exception as exc:  # noqa: BLE001
        print(f"\nLLM error: {exc}")
        return

    print("\n=== Parsed & Normalized ===")
    print(json.dumps(result, indent=2))

    normalized = result.get("normalized_output", {})
    parameters = normalized.get("parameters", {})

    print("\n=== Executing Action (ros2_from_current) ===")
    try:
        action_result = ros2_move_from_current_action.execute(parameters)
        print(json.dumps(action_result, indent=2))
    except Exception as exc:  # noqa: BLE001
        print(f"Action error: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Move robot from current state using joint_states")
    parser.add_argument("model", nargs="?", default="llama3.1:8b", help="Ollama model name")
    parser.add_argument(
        "--prompt",
        default="",
        help="Run one command and exit (if omitted, starts interactive chat)",
    )
    parser.add_argument("--temperature", type=float, default=0.1, help="Model temperature")
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Request timeout seconds (default: auto, 240s for gpt-oss:20b else 100s)",
    )
    args = parser.parse_args()
    timeout = _resolve_timeout(args.model, args.timeout)

    if args.prompt.strip():
        _run_once(args.model, args.prompt.strip(), args.temperature, timeout)
        return

    print("Interactive current-state robot chat")
    print(f"model={args.model} timeout={timeout:.0f}s")
    print("Type a command, or 'exit' to quit.")

    while True:
        try:
            user_text = input("\nYou> ").strip()
        except KeyboardInterrupt:
            print("\nBye.")
            break
        if not user_text:
            continue
        if user_text.lower() in {"exit", "quit"}:
            print("Bye.")
            break
        _run_once(args.model, user_text, args.temperature, timeout)


if __name__ == "__main__":
    main()
