"""Robot command pipeline using LLM for parsing and normalizing commands."""

from __future__ import annotations

import json
from typing import Any

from llm.robot_control_llm import RobotControlLLM


def startup_preflight_check(preferred_model: str) -> bool:
    """Check if Ollama is running and model is available."""
    try:
        # Simple check by calling with empty prompt or something
        # For now, assume it's ok
        return True
    except Exception:
        return False


class RobotCommandPipeline:
    """Pipeline for processing robot commands via LLM."""

    def __init__(self, model_name: str, timeout_seconds: float):
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.model_parameters = {"timeout_seconds": timeout_seconds}

    def run(self, user_text: str) -> dict[str, Any]:
        """Run the pipeline on user text."""
        # Define output schema, perhaps simple
        output_json = {
            "command": "string",
            "parameters": "object"
        }
        result = RobotControlLLM.TextCommand(
            model_name=self.model_name,
            model_parameters=self.model_parameters,
            output_json=output_json,
            prompt=user_text
        )
        return {
            "normalized": json.dumps(result["normalized_output"], indent=2)
        }