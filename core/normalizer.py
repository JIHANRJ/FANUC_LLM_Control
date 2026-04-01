"""Normalization utilities for command intent and parameter aliases."""

from __future__ import annotations

import re
from typing import Any

ALIAS_MAP: dict[str, str] = {
    "joint_number": "joint",
    "angle": "delta",
}

INTENT_ALIAS_MAP: dict[str, str] = {
    "move": "joint_move",
    "move_joint": "joint_move",
    "jointmove": "joint_move",
}

_CARDINAL_WORDS: dict[str, int] = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}

_TENS_WORDS: dict[str, int] = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}

_ORDINAL_TO_CARDINAL: dict[str, str] = {
    "first": "one",
    "second": "two",
    "third": "three",
    "fourth": "four",
    "fifth": "five",
    "sixth": "six",
}


def _parse_number_words(text: str) -> int | None:
    """Parse simple spoken numbers, including negatives, into integers."""
    lowered = text.lower().replace("-", " ")
    for ordinal, cardinal in _ORDINAL_TO_CARDINAL.items():
        lowered = re.sub(rf"\b{ordinal}\b", cardinal, lowered)

    tokens = [token for token in re.findall(r"[a-z]+", lowered) if token != "and"]
    if not tokens:
        return None

    sign = -1 if any(token in {"minus", "negative"} for token in tokens) else 1
    filtered = [token for token in tokens if token not in {"minus", "negative"}]
    if not filtered:
        return None

    total = 0
    used = False
    idx = 0
    while idx < len(filtered):
        token = filtered[idx]

        if token in _CARDINAL_WORDS:
            total += _CARDINAL_WORDS[token]
            used = True
            idx += 1
            continue

        if token in _TENS_WORDS:
            value = _TENS_WORDS[token]
            if idx + 1 < len(filtered) and filtered[idx + 1] in _CARDINAL_WORDS:
                value += _CARDINAL_WORDS[filtered[idx + 1]]
                idx += 1
            total += value
            used = True
            idx += 1
            continue

        return None

    if not used:
        return None

    return sign * total


def _coerce_numeric(value: Any) -> Any:
    """Convert numeric-like strings into numbers while preserving other values."""
    if isinstance(value, (int, float)):
        return value

    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return value

        try:
            if "." in stripped:
                return float(stripped)
            return int(stripped)
        except ValueError:
            return value

    return value


def _extract_joint_index(value: Any) -> Any:
    """Extract joint index from values like 1, 'J1', 'joint one', or 'first joint'."""
    if isinstance(value, int):
        return value

    if isinstance(value, float):
        return int(value) if value.is_integer() else value

    if not isinstance(value, str):
        return value

    stripped = value.strip()
    if not stripped:
        return value

    direct_numeric = _coerce_numeric(stripped)
    if isinstance(direct_numeric, (int, float)):
        if isinstance(direct_numeric, float) and not direct_numeric.is_integer():
            return value
        return int(direct_numeric)

    lowered = stripped.lower()
    digit_match = re.search(r"\b(?:j|joint)\s*([1-9])\b", lowered)
    if digit_match:
        return int(digit_match.group(1))

    word_match = re.search(r"\b(?:j|joint)\s+([a-z\-]+)\b", lowered)
    if word_match:
        parsed = _parse_number_words(word_match.group(1))
        if parsed is not None:
            return parsed

    parsed_full = _parse_number_words(lowered)
    if parsed_full is not None:
        return parsed_full

    return value


def _extract_delta(value: Any) -> Any:
    """Extract a delta value from numeric strings or spoken number words."""
    numeric = _coerce_numeric(value)
    if isinstance(numeric, (int, float)):
        return numeric

    if isinstance(value, str):
        parsed = _parse_number_words(value)
        if parsed is not None:
            return parsed

    return value


def normalize_command(command: dict[str, Any]) -> dict[str, Any]:
    """Normalize command shape, intent format, and parameter naming."""
    raw_command_name = command.get("command_name", command.get("intent", ""))
    command_name = str(raw_command_name).strip().lower()
    command_name = INTENT_ALIAS_MAP.get(command_name, command_name)

    raw_parameters = command.get("parameters", {})
    parameters: dict[str, Any] = {}

    if isinstance(raw_parameters, dict):
        for key, value in raw_parameters.items():
            normalized_key = ALIAS_MAP.get(str(key), str(key))
            if normalized_key == "joint":
                parameters[normalized_key] = _extract_joint_index(value)
            elif normalized_key == "delta":
                parameters[normalized_key] = _extract_delta(value)
            else:
                parameters[normalized_key] = _coerce_numeric(value)

    return {
        "command_name": command_name,
        "intent": command_name,
        "parameters": parameters,
    }
