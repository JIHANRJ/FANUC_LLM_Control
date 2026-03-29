"""ROS2-style dummy action implementation for a modular joint demo move."""

from __future__ import annotations

import logging
import math
import time
from typing import Any

_LOGGER_NAME = "modular_joint_demo"


def _get_logger() -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [joint_demo] %(message)s", "%H:%M:%S")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def _simulate_wait_for_server(logger: logging.Logger, timeout_s: float = 2.0) -> bool:
    logger.info("Waiting for action server 'follow_joint_trajectory'...")
    time.sleep(min(timeout_s, 0.8))
    logger.info("Action server is available.")
    return True


def _simulate_goal_result(logger: logging.Logger, accepted: bool) -> dict[str, Any]:
    if not accepted:
        logger.error("Goal rejected by action server.")
        return {"accepted": False, "success": False, "message": "Goal rejected"}

    logger.info("Goal accepted. Executing trajectory...")
    time.sleep(0.7)
    logger.info("Trajectory execution completed successfully.")
    return {"accepted": True, "success": True, "message": "Execution success"}


def modular_joint_demo(
    joint_1: float,
    joint_2: float,
    joint_3: float,
    joint_4: float,
    joint_5: float,
    joint_6: float,
    vel: float = 0.2,
    acc: float = 0.2,
) -> dict[str, Any]:
    """Simulate a ROS2 action client flow for joint-space motion."""
    logger = _get_logger()

    logger.info("Creating ROS2 node: modular_joint_demo_client")
    logger.info("Loading motion parameters: vel=%.3f, acc=%.3f", vel, acc)
    logger.info("Initializing communications and waiting for startup delay...")
    time.sleep(0.5)

    joints_deg = [joint_1, joint_2, joint_3, joint_4, joint_5, joint_6]
    joints_rad = [math.radians(value) for value in joints_deg]

    logger.info("Input joint targets (deg): %s", [round(v, 3) for v in joints_deg])
    logger.info("Converted joint targets (rad): %s", [round(v, 4) for v in joints_rad])

    if vel <= 0 or acc <= 0:
        logger.error("Velocity and acceleration must be positive.")
        return {"accepted": False, "success": False, "message": "Invalid dynamics limits"}

    if not _simulate_wait_for_server(logger):
        return {"accepted": False, "success": False, "message": "Server timeout"}

    logger.info("Sending trajectory goal with 6 joints...")

    # Reject goals that exceed realistic industrial joint limits for this demo.
    accepted = all(abs(value) <= 180.0 for value in joints_deg)
    result = _simulate_goal_result(logger, accepted=accepted)

    logger.info("Shutting down dummy node cleanly.")
    return result
