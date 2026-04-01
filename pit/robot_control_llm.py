"""Compatibility bridge for imports that still point to pit.robot_control_llm."""

from llm.robot_control_llm import RobotControlLLM, RobotControlLMM

__all__ = ["RobotControlLLM", "RobotControlLMM"]
