"""Single-joint movement action executor (simulator)."""

from __future__ import annotations

from typing import Any


def execute(parameters: dict[str, Any]) -> dict[str, Any]:
    joint = parameters["joint"]
    delta = parameters["delta"]
    print(f"[dispatcher] Executing joint_move: joint={joint}, delta={delta} deg")
    return {
        "accepted": True,
        "success": True,
        "message": f"Simulated joint {joint} move by {delta} degrees.",
    }
