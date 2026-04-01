"""Action handler registry used by dispatcher."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from actions import move_joint_action
from actions.joint_demo import modular_joint_demo

ActionHandler = Callable[[dict[str, Any]], dict[str, Any]]


def _joint_demo_adapter(parameters: dict[str, Any]) -> dict[str, Any]:
    return modular_joint_demo(**parameters)


_ACTION_HANDLERS: dict[str, ActionHandler] = {
    "move_joint": move_joint_action.execute,
    "joint_demo": _joint_demo_adapter,
}


def get_action_handler(handler_name: str) -> ActionHandler:
    try:
        return _ACTION_HANDLERS[handler_name]
    except KeyError as exc:
        raise ValueError(f"No action handler configured for: {handler_name!r}") from exc
