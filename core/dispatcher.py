"""Command dispatcher that maps validated commands to executable actions."""

from __future__ import annotations

from config import ACTIVE_ACTION_CATALOG
from core.action_catalog import load_action_catalog
from core.action_registry import get_action_handler

_ACTION_MAP = {item.command_name: item for item in load_action_catalog(ACTIVE_ACTION_CATALOG)}


def _get_command_name(command: dict[str, object]) -> str:
    raw = command.get("command_name", command.get("intent"))
    if not isinstance(raw, str):
        raise ValueError("Command payload is missing a string 'command_name'.")
    return raw


def dispatch_command(command: dict[str, object]) -> dict[str, object]:
    """Route validated commands to corresponding action handlers via catalog."""
    command_name = _get_command_name(command)
    parameters = command["parameters"]
    if not isinstance(parameters, dict):
        raise ValueError("Command 'parameters' must be an object.")

    action_def = _ACTION_MAP.get(command_name)
    if action_def is None:
        raise ValueError(f"No dispatcher route configured for command: {command_name}")

    handler = get_action_handler(action_def.handler)
    return handler(parameters)
