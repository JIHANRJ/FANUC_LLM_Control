"""Load and expose local tool definitions for function-calling prompts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ToolDefinition:
    """Single tool metadata used by prompt composition and dispatch planning."""

    name: str
    intent: str
    description: str
    parameters: dict[str, Any]
    prompt_pack: str
    simulator_only: bool


def load_tool_registry(registry_path: str) -> list[ToolDefinition]:
    """Load a JSON tool registry file and return typed tool definitions."""
    path = Path(registry_path)
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    raw_tools = data.get("tools", [])
    if not isinstance(raw_tools, list):
        raise ValueError("Tool registry must provide a 'tools' array.")

    tools: list[ToolDefinition] = []
    for raw in raw_tools:
        if not isinstance(raw, dict):
            raise ValueError("Each tool entry must be an object.")

        name = raw.get("name")
        intent = raw.get("intent")
        description = raw.get("description")
        parameters = raw.get("parameters")
        prompt_pack = raw.get("prompt_pack")
        simulator_only = raw.get("simulator_only", True)

        if not isinstance(name, str) or not name:
            raise ValueError("Tool 'name' must be a non-empty string.")
        if not isinstance(intent, str) or not intent:
            raise ValueError(f"Tool {name!r}: 'intent' must be a non-empty string.")
        if not isinstance(description, str):
            raise ValueError(f"Tool {name!r}: 'description' must be a string.")
        if not isinstance(parameters, dict):
            raise ValueError(f"Tool {name!r}: 'parameters' must be an object.")
        if not isinstance(prompt_pack, str) or not prompt_pack:
            raise ValueError(f"Tool {name!r}: 'prompt_pack' must be a non-empty string.")
        if not isinstance(simulator_only, bool):
            raise ValueError(f"Tool {name!r}: 'simulator_only' must be boolean.")

        tools.append(
            ToolDefinition(
                name=name,
                intent=intent,
                description=description,
                parameters=parameters,
                prompt_pack=prompt_pack,
                simulator_only=simulator_only,
            )
        )

    return tools
