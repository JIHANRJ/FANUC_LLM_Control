"""Central configuration for the local LLM-to-robot pipeline."""

from __future__ import annotations

import os

MODEL_NAME: str = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
FALLBACK_MODEL_NAMES: tuple[str, ...] = (
    "llama3.1:latest",
)
OLLAMA_API_URL: str = "http://localhost:11434/api/generate"
OLLAMA_TEMPERATURE: float = 0.1
OLLAMA_STREAM: bool = False
OLLAMA_TIMEOUT_SECONDS: float = 20.0

# Select which output structure definition to use from schemas/*.json
ACTIVE_OUTPUT_SCHEMA: str = os.getenv("OUTPUT_SCHEMA", "robot_command_v1")

JOINT_INDEX_MIN: int = 1
JOINT_INDEX_MAX: int = 6
DELTA_ABS_MAX: float = 60.0
