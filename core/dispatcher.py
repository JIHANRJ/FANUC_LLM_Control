"""Intent dispatcher that maps validated commands to executable actions."""

from __future__ import annotations

from typing import Any

from actions.joint_demo import modular_joint_demo


def _execute_joint_move(parameters: dict[str, Any]) -> dict[str, Any]:
    """Dummy single-joint move action for first-stage integration testing."""
    joint = parameters["joint"]
    delta = parameters["delta"]
    print(f"[dispatcher] Executing joint_move: joint={joint}, delta={delta} deg")
    return {
        "accepted": True,
        "success": True,
        "message": f"Simulated joint {joint} move by {delta} degrees.",
    }


def dispatch_command(command: dict[str, Any]) -> dict[str, Any]:
    """Route validated commands to their corresponding action handlers."""
    intent = command["intent"]
    parameters = command["parameters"]

    if intent == "joint_demo":
        return modular_joint_demo(**parameters)

    if intent == "joint_move":
        return _execute_joint_move(parameters)

    raise ValueError(f"No dispatcher route configured for intent: {intent}")
