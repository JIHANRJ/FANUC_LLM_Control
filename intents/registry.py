"""Intent definitions and required parameters."""

from __future__ import annotations

INTENTS: dict[str, list[str]] = {
    "joint_move": ["joint", "delta"],
    "joint_demo": [
        "joint_1",
        "joint_2",
        "joint_3",
        "joint_4",
        "joint_5",
        "joint_6",
    ],
}
