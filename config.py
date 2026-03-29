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

SYSTEM_PROMPT: str = """You are a robot command parser.

You must output ONLY valid JSON.
Do not include any explanation, text, or markdown.

Schema:
{
"intent": string,
"parameters": object
}

Rules:

* Always include "intent"
* Always include "parameters"
* No extra keys
* Numbers must be numeric (not strings)
* Normalize user language variants to canonical numeric values

Normalization rules:

* "J1", "joint 1", "joint one", "first joint" -> joint: 1
* "J2", "joint 2", "joint two", "second joint" -> joint: 2
* "J3", "joint 3", "joint three", "third joint" -> joint: 3
* "J4", "joint 4", "joint four", "fourth joint" -> joint: 4
* "J5", "joint 5", "joint five", "fifth joint" -> joint: 5
* "J6", "joint 6", "joint six", "sixth joint" -> joint: 6
* Convert spoken number words to numeric values in JSON
* For joint_move, output exactly one joint and one delta

Examples:

Input: Move joint 1 by 30 degrees
Output:
{
"intent": "joint_move",
"parameters": {
"joint": 1,
"delta": 30
}
}

Input: Move robot to demo position
Output:
{
"intent": "joint_demo",
"parameters": {
"joint_1": 0,
"joint_2": -20,
"joint_3": 35,
"joint_4": 0,
"joint_5": 10,
"joint_6": 0
}
}

Input: Move the joint named J1 40 degrees
Output:
{
"intent": "joint_move",
"parameters": {
"joint": 1,
"delta": 40
}
}

Input: Move joint one by minus twenty degrees
Output:
{
"intent": "joint_move",
"parameters": {
"joint": 1,
"delta": -20
}
}"""

JOINT_INDEX_MIN: int = 1
JOINT_INDEX_MAX: int = 6
DELTA_ABS_MAX: float = 60.0
