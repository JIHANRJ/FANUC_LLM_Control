"""Quick playground for calling RobotControlLMM.TextCommand(...) directly."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from pit.robot_control_llm import RobotControlLMM
except ModuleNotFoundError:
    # Support direct execution: python pit/test_text_command.py
    from robot_control_llm import RobotControlLMM


def main() -> None:
    output_schema = {
        "intent": "string",
        "parameters": {
            "joint": "integer",
            "delta": "number",
        },
    }

    try:
        result = RobotControlLMM.TextCommand(
            model_name="llama3.1:8b",
            model_parameters={
                "temperature": 0.1,
                "stream": False,
                "timeout_seconds": 20,
            },
            output_json=output_schema,
            prompt="move joint one by 30 degrees",
        )
        print(json.dumps(result, indent=2))
    except ConnectionError as exc:
        print(f"[pit-test] {exc}")
        print("[pit-test] Start Ollama first: ollama serve")


if __name__ == "__main__":
    main()
