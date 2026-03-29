"""Robust JSON parsing helpers for handling imperfect LLM responses."""

from __future__ import annotations

import json
from typing import Any, Mapping


class ParseError(ValueError):
    """Raised when JSON extraction/parsing fails."""


def _extract_first_json_object(text: str) -> str:
    """Extract the first balanced JSON object from arbitrary text."""
    start = text.find("{")
    if start == -1:
        raise ParseError("No JSON object start found in model output.")

    depth = 0
    in_string = False
    escaped = False

    for idx in range(start, len(text)):
        char = text[idx]

        if escaped:
            escaped = False
            continue

        if char == "\\":
            escaped = True
            continue

        if char == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]

    if depth > 0 and not in_string:
        # Ollama can occasionally truncate the closing braces; repair minimal balance.
        return text[start:] + ("}" * depth)

    raise ParseError("Unbalanced JSON object in model output.")


def safely_parse_json(raw: str | Mapping[str, Any]) -> dict[str, Any]:
    """Parse a model response into a dictionary.

    Accepts either a JSON string or an existing mapping for pipeline safety.
    """
    if isinstance(raw, Mapping):
        return dict(raw)

    candidate = raw.strip()
    if not candidate:
        raise ParseError("Empty model response; expected JSON object.")

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        extracted = _extract_first_json_object(candidate)
        try:
            parsed = json.loads(extracted)
        except json.JSONDecodeError as exc:
            raise ParseError(f"Malformed JSON in model output: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ParseError("Parsed JSON is not an object.")

    return parsed
