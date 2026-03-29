"""Prompt composition utilities based on declarative output schemas."""

from __future__ import annotations

import json

from config import ACTIVE_OUTPUT_SCHEMA
from schemas.registry import get_output_schema


def build_prompt(user_text: str, schema_name: str | None = None) -> str:
    """Build the full model prompt from the selected schema definition."""
    schema = get_output_schema(schema_name or ACTIVE_OUTPUT_SCHEMA)

    lines: list[str] = [
        "You are a robot command parser.",
        "",
        "You must output ONLY valid JSON.",
        "Do not include any explanation, text, or markdown.",
        "",
        f"Active output schema: {schema.name}",
        f"Description: {schema.description}",
        "",
        "Schema:",
        json.dumps(schema.json_schema, indent=2),
        "",
        "Rules:",
    ]

    lines.extend([f"* {rule}" for rule in schema.rules])
    lines.append("")
    lines.append("Examples:")

    for input_text, output_payload in schema.examples:
        lines.append("")
        lines.append(f"Input: {input_text}")
        lines.append("Output:")
        lines.append(json.dumps(output_payload, indent=2))

    lines.append("")
    lines.append(f"Input: {user_text}")
    lines.append("Output:")

    return "\n".join(lines)
