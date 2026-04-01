"""Validation layer that enforces strict command and safety constraints."""

from __future__ import annotations

from typing import Any

from config import ACTIVE_ACTION_CATALOG
from core.action_catalog import ActionDefinition, load_action_catalog


class ValidationError(ValueError):
    """Raised when a command fails schema or safety validation."""


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _load_action_map() -> dict[str, ActionDefinition]:
    items = load_action_catalog(ACTIVE_ACTION_CATALOG)
    return {item.command_name: item for item in items}


def _get_command_name(command: dict[str, Any]) -> str | None:
    raw = command.get("command_name", command.get("intent"))
    if isinstance(raw, str) and raw:
        return raw
    return None


def validate_command(command: dict[str, Any]) -> tuple[bool, str]:
    """Validate a command using action catalog metadata and safety constraints."""
    if "parameters" not in command:
        return False, "Command must include 'parameters'."

    command_name = _get_command_name(command)
    parameters = command.get("parameters")

    action_map = _load_action_map()
    if command_name is None or command_name not in action_map:
        return False, f"Unsupported command: {command_name!r}"

    if not isinstance(parameters, dict):
        return False, "'parameters' must be an object."

    action = action_map[command_name]
    required_params = {
        key for key, meta in action.parameters.items() if isinstance(meta, dict) and meta.get("required")
    }
    allowed_params = set(action.parameters.keys())
    provided_params = set(parameters.keys())

    missing = required_params - provided_params
    extras = provided_params - allowed_params

    if missing:
        return False, f"Missing required parameters: {sorted(missing)}"

    if extras:
        return False, f"Unexpected parameters for command {command_name!r}: {sorted(extras)}"

    for key, meta in action.parameters.items():
        if key not in parameters:
            continue
        value = parameters[key]
        if not isinstance(meta, dict):
            continue

        expected_type = meta.get("type")
        if expected_type == "integer" and not isinstance(value, int):
            return False, f"{key!r} must be an integer."
        if expected_type == "number" and not _is_number(value):
            return False, f"{key!r} must be numeric."

        minimum = meta.get("minimum")
        maximum = meta.get("maximum")
        if _is_number(value):
            numeric = float(value)
            if isinstance(minimum, (int, float)) and numeric < float(minimum):
                return False, f"{key!r} must be >= {minimum}."
            if isinstance(maximum, (int, float)) and numeric > float(maximum):
                return False, f"{key!r} must be <= {maximum}."

    return True, "Command is valid."
