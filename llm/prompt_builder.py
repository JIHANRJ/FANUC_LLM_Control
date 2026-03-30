"""Prompt composition utilities based on declarative output schemas."""

from __future__ import annotations

import json

from config import ACTIVE_OUTPUT_SCHEMA, ACTIVE_TOOL_REGISTRY, PROMPT_PACK_DIR
from core.prompt_pack_loader import load_prompt_pack
from core.tool_registry import load_tool_registry
from schemas.registry import get_output_schema


def build_prompt(user_text: str, schema_name: str | None = None) -> str:
    """Build the full model prompt from the selected schema definition."""
    schema = get_output_schema(schema_name or ACTIVE_OUTPUT_SCHEMA)
    tools = load_tool_registry(ACTIVE_TOOL_REGISTRY)

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
    lines.append("Available Tools (Increment 1):")
    for tool in tools:
        lines.append(f"- Tool: {tool.name}")
        lines.append(f"  Intent: {tool.intent}")
        lines.append(f"  Description: {tool.description}")
        lines.append(f"  Parameters: {json.dumps(tool.parameters)}")

        curated_prompt = load_prompt_pack(PROMPT_PACK_DIR, tool.prompt_pack)
        lines.append("  Curated Prompt Pack:")
        lines.append(curated_prompt)

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
