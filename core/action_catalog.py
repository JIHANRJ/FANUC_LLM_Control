"""Load and expose local action definitions for command routing and prompts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ActionDefinition:
    """Single action metadata used by prompt composition and runtime validation."""

    name: str
    command_name: str
    description: str
    handler: str
    parameters: dict[str, Any]
    prompt_pack: str
    simulator_only: bool


def load_action_catalog(catalog_path: str) -> list[ActionDefinition]:
    """Load a JSON action catalog file and return typed action definitions."""
    path = Path(catalog_path)
    if not path.is_absolute():
        path = REPO_ROOT / path
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    raw_actions = data.get("actions", [])
    if not isinstance(raw_actions, list):
        raise ValueError("Action catalog must provide an 'actions' array.")

    actions: list[ActionDefinition] = []
    for raw in raw_actions:
        if not isinstance(raw, dict):
            raise ValueError("Each action entry must be an object.")

        name = raw.get("name")
        command_name = raw.get("command_name") or raw.get("intent")
        description = raw.get("description")
        handler = raw.get("handler")
        parameters = raw.get("parameters")
        prompt_pack = raw.get("prompt_pack")
        simulator_only = raw.get("simulator_only", True)

        if not isinstance(name, str) or not name:
            raise ValueError("Action 'name' must be a non-empty string.")
        if not isinstance(command_name, str) or not command_name:
            raise ValueError(f"Action {name!r}: 'command_name' must be a non-empty string.")
        if not isinstance(description, str):
            raise ValueError(f"Action {name!r}: 'description' must be a string.")
        if not isinstance(handler, str) or not handler:
            raise ValueError(f"Action {name!r}: 'handler' must be a non-empty string.")
        if not isinstance(parameters, dict):
            raise ValueError(f"Action {name!r}: 'parameters' must be an object.")
        if not isinstance(prompt_pack, str) or not prompt_pack:
            raise ValueError(f"Action {name!r}: 'prompt_pack' must be a non-empty string.")
        if not isinstance(simulator_only, bool):
            raise ValueError(f"Action {name!r}: 'simulator_only' must be boolean.")

        actions.append(
            ActionDefinition(
                name=name,
                command_name=command_name,
                description=description,
                handler=handler,
                parameters=parameters,
                prompt_pack=prompt_pack,
                simulator_only=simulator_only,
            )
        )

    return actions
