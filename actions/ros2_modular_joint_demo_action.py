"""ROS2 modular_joint_demo executor via SSH into Linux VM."""

from __future__ import annotations

import os
import shlex
import subprocess
from typing import Any

DEFAULT_TARGET_DEG: dict[str, float] = {
    "joint_1": 0.0,
    "joint_2": -20.0,
    "joint_3": 35.0,
    "joint_4": 0.0,
    "joint_5": 10.0,
    "joint_6": 0.0,
}


def _as_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _as_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _build_target_deg(parameters: dict[str, Any]) -> dict[str, float]:
    target_deg = dict(DEFAULT_TARGET_DEG)

    candidate_target = parameters.get("target_deg")
    if isinstance(candidate_target, dict):
        for idx in range(1, 7):
            key = f"joint_{idx}"
            if key in candidate_target:
                target_deg[key] = _as_float(candidate_target[key], target_deg[key])
        return target_deg

    joint_index = _as_int(parameters.get("joint"), 0)
    if 1 <= joint_index <= 6 and "delta" in parameters:
        key = f"joint_{joint_index}"
        target_deg[key] = target_deg[key] + _as_float(parameters.get("delta"), 0.0)

    return target_deg


def _build_remote_ros2_cmd(parameters: dict[str, Any]) -> str:
    ros_distro = os.getenv("FANUC_VM_ROS_DISTRO", "humble")
    ws_root = os.getenv("FANUC_VM_WS_ROOT", "/home/jihanrj/ws_fanuc")
    package_name = os.getenv("FANUC_VM_PACKAGE", "fanuc_tools")
    executable_name = os.getenv("FANUC_VM_EXECUTABLE", "modular_joint_demo")

    planning_group_raw = str(parameters.get("planning_group", "manipulator")).strip()
    planning_group = planning_group_raw or "manipulator"
    vel = _as_float(parameters.get("vel"), 0.2)
    acc = _as_float(parameters.get("acc"), 0.2)
    startup_delay = _as_float(parameters.get("startup_delay"), 2.0)
    target_deg = _build_target_deg(parameters)

    ros_parts = [
        "ros2",
        "run",
        package_name,
        executable_name,
        "--ros-args",
        "-p",
        f"planning_group:={planning_group}",
        "-p",
        f"vel:={vel}",
        "-p",
        f"acc:={acc}",
        "-p",
        f"startup_delay:={startup_delay}",
    ]

    for idx in range(1, 7):
        key = f"joint_{idx}"
        ros_parts.extend(["-p", f"target_deg.{key}:={target_deg[key]}"])

    ros_run_cmd = " ".join(shlex.quote(part) for part in ros_parts)
    sourced_cmd = (
        f"source /opt/ros/{shlex.quote(ros_distro)}/setup.bash"
        f" && source {shlex.quote(ws_root)}/install/setup.bash"
        f" && {ros_run_cmd}"
    )
    return f"bash -lc {shlex.quote(sourced_cmd)}"


def execute(parameters: dict[str, Any]) -> dict[str, Any]:
    host = os.getenv("FANUC_VM_HOST", "192.168.64.9")
    user = os.getenv("FANUC_VM_USER", "jihanrj")
    port = str(os.getenv("FANUC_VM_PORT", "22"))
    timeout_seconds = _as_float(os.getenv("FANUC_VM_TIMEOUT", "120"), 120.0)
    key_path = os.getenv("FANUC_VM_SSH_KEY", "").strip()

    remote_cmd = _build_remote_ros2_cmd(parameters)

    ssh_cmd = [
        "ssh",
        "-p",
        port,
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
    ]

    if key_path:
        ssh_cmd.extend(["-i", key_path, "-o", "IdentitiesOnly=yes"])

    ssh_cmd.extend([f"{user}@{host}", remote_cmd])

    try:
        completed = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "accepted": False,
            "success": False,
            "message": f"SSH command timed out after {timeout_seconds:.0f}s.",
            "data": {
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
                "exit_code": None,
                "executed_command": ssh_cmd,
            },
        }

    stdout_text = completed.stdout.strip()
    stderr_text = completed.stderr.strip()

    if completed.returncode == 255 and "Permission denied" in stderr_text:
        return {
            "accepted": False,
            "success": False,
            "message": (
                "SSH authentication failed. Configure key-based auth for non-interactive mode "
                "or set FANUC_VM_SSH_KEY to a valid private key path."
            ),
            "data": {
                "stdout": stdout_text,
                "stderr": stderr_text,
                "exit_code": completed.returncode,
                "executed_command": ssh_cmd,
            },
        }

    succeeded = completed.returncode == 0
    return {
        "accepted": succeeded,
        "success": succeeded,
        "message": (
            "ROS2 modular_joint_demo executed successfully in VM."
            if succeeded
            else "ROS2 modular_joint_demo execution failed in VM."
        ),
        "data": {
            "stdout": stdout_text,
            "stderr": stderr_text,
            "exit_code": completed.returncode,
            "executed_command": ssh_cmd,
        },
    }
