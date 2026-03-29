"""Validation layer that enforces strict command and safety constraints."""

from __future__ import annotations

from typing import Any

from config import DELTA_ABS_MAX, JOINT_INDEX_MAX, JOINT_INDEX_MIN
from intents.registry import INTENTS


class ValidationError(ValueError):
    """Raised when a command fails schema or safety validation."""


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_command(command: dict[str, Any]) -> tuple[bool, str]:
    """Validate an intent command using registry + per-intent safety rules."""
    required_top_keys = {"intent", "parameters"}
    if set(command.keys()) != required_top_keys:
        return False, "Command must contain only 'intent' and 'parameters'."

    intent = command.get("intent")
    parameters = command.get("parameters")

    if not isinstance(intent, str) or intent not in INTENTS:
        return False, f"Unsupported intent: {intent!r}"

    if not isinstance(parameters, dict):
        return False, "'parameters' must be an object."

    required_params = set(INTENTS[intent])
    provided_params = set(parameters.keys())

    missing = required_params - provided_params
    extras = provided_params - required_params

    if missing:
        return False, f"Missing required parameters: {sorted(missing)}"

    if extras:
        return False, f"Unexpected parameters for intent {intent!r}: {sorted(extras)}"

    if intent == "joint_move":
        joint = parameters.get("joint")
        delta = parameters.get("delta")

        if not isinstance(joint, int):
            return False, "'joint' must be an integer from 1 to 6."

        if not (JOINT_INDEX_MIN <= joint <= JOINT_INDEX_MAX):
            return False, f"'joint' must be in range [{JOINT_INDEX_MIN}, {JOINT_INDEX_MAX}]."

        if not _is_number(delta):
            return False, "'delta' must be numeric."

        if abs(float(delta)) > DELTA_ABS_MAX:
            return False, f"'delta' exceeds max allowed magnitude of {DELTA_ABS_MAX}."

    if intent == "joint_demo":
        for key in INTENTS["joint_demo"]:
            value = parameters.get(key)
            if not _is_number(value):
                return False, f"{key!r} must be numeric."

    return True, "Command is valid."
