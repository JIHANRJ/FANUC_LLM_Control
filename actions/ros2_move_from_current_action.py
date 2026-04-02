"""ROS2 move action that computes target from current joint states over SSH."""

from __future__ import annotations

import math
import os
import shlex
import subprocess
import ast
from typing import Any

from actions import ros2_modular_joint_demo_action


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


def _coerce_joint_list(value: Any) -> list[int]:
    if isinstance(value, int):
        return [value]

    if isinstance(value, list):
        items: list[int] = []
        for item in value:
            try:
                items.append(int(item))
            except (TypeError, ValueError):
                continue
        return items

    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.lower() in {"all", "all_joints"}:
            return [1, 2, 3, 4, 5, 6]
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = ast.literal_eval(stripped)
            except (ValueError, SyntaxError):
                return []
            return _coerce_joint_list(parsed)
        try:
            return [int(stripped)]
        except ValueError:
            return []

    return []


def _ssh_prefix() -> list[str]:
    host = os.getenv("FANUC_VM_HOST", "192.168.64.9")
    user = os.getenv("FANUC_VM_USER", "jihanrj")
    port = str(os.getenv("FANUC_VM_PORT", "22"))
    key_path = os.getenv("FANUC_VM_SSH_KEY", "").strip()

    cmd = [
        "ssh",
        "-p",
        port,
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
    ]
    if key_path:
        cmd.extend(["-i", key_path, "-o", "IdentitiesOnly=yes"])
    cmd.append(f"{user}@{host}")
    return cmd


def _source_prefix() -> str:
    ros_distro = os.getenv("FANUC_VM_ROS_DISTRO", "humble")
    ws_root = os.getenv("FANUC_VM_WS_ROOT", "/home/jihanrj/ws_fanuc")
    return (
        f"source /opt/ros/{shlex.quote(ros_distro)}/setup.bash"
        f" && source {shlex.quote(ws_root)}/install/setup.bash"
    )


def _run_remote(cmd_text: str, timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    ssh_cmd = _ssh_prefix()
    full_cmd = ssh_cmd + [f"bash -lc {shlex.quote(cmd_text)}"]
    return subprocess.run(
        full_cmd,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


def _parse_list_block(text: str, field_name: str) -> list[str]:
    lines = text.splitlines()

    for idx, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line.startswith(f"{field_name}:"):
            continue

        remainder = line[len(field_name) + 1 :].strip()
        if remainder.startswith("[") and remainder.endswith("]"):
            payload = remainder[1:-1]
            return [item.strip().strip("\"'") for item in payload.split(",") if item.strip()]

        items: list[str] = []
        cursor = idx + 1
        while cursor < len(lines):
            child = lines[cursor].strip()
            if not child.startswith("-"):
                break
            items.append(child[1:].strip().strip("\"'"))
            cursor += 1
        return items

    return []


def _joint_index_from_name(name: str) -> int | None:
    lowered = name.strip().lower().replace("_", "")
    for idx in range(1, 7):
        token1 = f"joint{idx}"
        token2 = f"j{idx}"
        if token1 in lowered or token2 in lowered:
            return idx
    return None


def _safe_planning_group(value: Any) -> str:
    if not isinstance(value, str):
        return "manipulator"
    cleaned = value.strip().lower()
    if cleaned in {"", "manipulator", "default", "all"}:
        return "manipulator"
    return "manipulator"


def _read_current_joint_deg(timeout_seconds: float) -> tuple[dict[str, float], dict[str, Any]]:
    source_cmd = _source_prefix()
    read_cmd = f"{source_cmd} && ros2 topic echo /joint_states --once"
    completed = _run_remote(read_cmd, timeout_seconds=timeout_seconds)

    stdout_text = completed.stdout.strip()
    stderr_text = completed.stderr.strip()

    if completed.returncode != 0:
        raise RuntimeError(
            "Failed to read /joint_states over SSH. "
            f"exit={completed.returncode}, stderr={stderr_text or '<empty>'}"
        )

    names = _parse_list_block(stdout_text, "name")
    positions = _parse_list_block(stdout_text, "position")

    if not names or not positions:
        raise RuntimeError("Could not parse name/position from /joint_states output.")

    joint_deg: dict[str, float] = {}
    for name, pos_text in zip(names, positions):
        idx = _joint_index_from_name(name)
        if idx is None:
            continue
        pos_rad = _as_float(pos_text, float("nan"))
        if math.isnan(pos_rad):
            continue
        joint_deg[f"joint_{idx}"] = math.degrees(pos_rad)

    if len(joint_deg) < 6:
        missing = [f"joint_{i}" for i in range(1, 7) if f"joint_{i}" not in joint_deg]
        raise RuntimeError(f"Missing joints in /joint_states parse: {missing}")

    debug = {
        "stdout": stdout_text,
        "stderr": stderr_text,
        "command": read_cmd,
    }
    return joint_deg, debug


def execute(parameters: dict[str, Any]) -> dict[str, Any]:
    timeout_seconds = _as_float(os.getenv("FANUC_VM_TIMEOUT", "120"), 120.0)

    delta = _as_float(parameters.get("delta"), float("nan"))
    mode = str(parameters.get("mode", "")).strip().lower()
    selected_joints = _coerce_joint_list(parameters.get("joints")) or _coerce_joint_list(parameters.get("joint"))

    # Support "move all joints to zero" style payloads.
    if mode in {"all_joints_zero", "all_joints_to_zero"} or (
        not selected_joints and not math.isnan(delta) and abs(delta) < 1e-9 and _as_int(parameters.get("joint"), 0) == 0
    ):
        forward_parameters: dict[str, Any] = {
            "planning_group": _safe_planning_group(parameters.get("planning_group", "manipulator")),
            "vel": _as_float(parameters.get("vel"), 0.2),
            "acc": _as_float(parameters.get("acc"), 0.2),
            "startup_delay": _as_float(parameters.get("startup_delay"), 2.0),
            "target_deg": {
                "joint_1": 0.0,
                "joint_2": 0.0,
                "joint_3": 0.0,
                "joint_4": 0.0,
                "joint_5": 0.0,
                "joint_6": 0.0,
            },
        }
        result = ros2_modular_joint_demo_action.execute(forward_parameters)
        data = result.get("data")
        if not isinstance(data, dict):
            data = {}
        data["mode"] = "all_joints_to_zero"
        result["data"] = data
        return result

    if not selected_joints:
        return {
            "accepted": False,
            "success": False,
            "message": "Expected 'joint' or 'joints' in range 1..6 for move-from-current action.",
        }
    if math.isnan(delta):
        return {
            "accepted": False,
            "success": False,
            "message": "Expected numeric 'delta' for move-from-current action.",
        }
    invalid_joints = [joint for joint in selected_joints if joint < 1 or joint > 6]
    if invalid_joints:
        return {
            "accepted": False,
            "success": False,
            "message": f"Invalid joint(s) requested: {invalid_joints}. Use joints in range 1..6.",
        }

    try:
        current_deg, read_debug = _read_current_joint_deg(timeout_seconds=timeout_seconds)
    except Exception as exc:  # noqa: BLE001
        return {
            "accepted": False,
            "success": False,
            "message": f"Could not read current joint state: {exc}",
        }

    target_deg = dict(current_deg)
    for joint_index in selected_joints:
        key = f"joint_{joint_index}"
        target_deg[key] = target_deg[key] + delta

    forward_parameters: dict[str, Any] = {
        "planning_group": _safe_planning_group(parameters.get("planning_group", "manipulator")),
        "vel": _as_float(parameters.get("vel"), 0.2),
        "acc": _as_float(parameters.get("acc"), 0.2),
        "startup_delay": _as_float(parameters.get("startup_delay"), 2.0),
        "target_deg": target_deg,
    }

    result = ros2_modular_joint_demo_action.execute(forward_parameters)

    data = result.get("data")
    if not isinstance(data, dict):
        data = {}
    data["current_deg"] = current_deg
    data["applied_delta"] = {"joints": selected_joints, "delta": delta}
    data["target_deg"] = target_deg
    data["joint_state_read"] = read_debug
    result["data"] = data
    return result
