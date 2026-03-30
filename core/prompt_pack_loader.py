"""Utilities for loading per-action curated prompt packs."""

from __future__ import annotations

from pathlib import Path


def load_prompt_pack(prompt_pack_dir: str, filename: str) -> str:
    """Load one prompt pack markdown/text file by filename."""
    path = Path(prompt_pack_dir) / filename
    if not path.exists():
        raise FileNotFoundError(f"Prompt pack not found: {path}")

    content = path.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError(f"Prompt pack is empty: {path}")

    return content
