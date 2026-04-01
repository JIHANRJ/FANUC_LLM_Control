"""Output schema registry for modular LLM response formats."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OutputSchema:
    """Declarative schema specification used to build model prompts."""

    name: str
    description: str
    json_schema: dict[str, Any]
    rules: tuple[str, ...]
    examples: tuple[tuple[str, dict[str, Any]], ...]

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "config" / "schemas"


def _read_schema_file(schema_name: str) -> dict[str, Any]:
    """Load a schema JSON file by schema name."""
    schema_path = SCHEMA_DIR / f"{schema_name}.json"
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")

    with schema_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _parse_examples(raw_examples: list[dict[str, Any]]) -> tuple[tuple[str, dict[str, Any]], ...]:
    """Validate and convert JSON examples into prompt-builder format."""
    parsed: list[tuple[str, dict[str, Any]]] = []
    for item in raw_examples:
        user_input = item.get("input")
        output = item.get("output")
        if not isinstance(user_input, str) or not isinstance(output, dict):
            raise ValueError("Each example must contain string 'input' and object 'output'.")
        parsed.append((user_input, output))
    return tuple(parsed)


def get_output_schema(schema_name: str) -> OutputSchema:
    """Return the configured schema or raise a clear error."""
    try:
        raw = _read_schema_file(schema_name)
    except FileNotFoundError as exc:
        available = ", ".join(list_available_schemas())
        raise KeyError(f"Unknown output schema '{schema_name}'. Available: {available}") from exc

    name = raw.get("name", schema_name)
    description = raw.get("description", "")
    json_schema = raw.get("json_schema")
    rules = raw.get("rules")
    examples = raw.get("examples")

    if not isinstance(name, str):
        raise ValueError("Schema 'name' must be a string.")
    if not isinstance(description, str):
        raise ValueError("Schema 'description' must be a string.")
    if not isinstance(json_schema, dict):
        raise ValueError("Schema 'json_schema' must be an object.")
    if not isinstance(rules, list) or not all(isinstance(rule, str) for rule in rules):
        raise ValueError("Schema 'rules' must be a list of strings.")
    if not isinstance(examples, list):
        raise ValueError("Schema 'examples' must be a list.")

    return OutputSchema(
        name=name,
        description=description,
        json_schema=json_schema,
        rules=tuple(rules),
        examples=_parse_examples(examples),
    )


def list_available_schemas() -> list[str]:
    """Return all schema names available as JSON files."""
    names = [path.stem for path in SCHEMA_DIR.glob("*.json")]
    return sorted(names)
