"""Ollama-backed LLM interface implementation for local command parsing."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config import (
    FALLBACK_MODEL_NAMES,
    MODEL_NAME,
    OLLAMA_API_URL,
    OLLAMA_STREAM,
    OLLAMA_TEMPERATURE,
    OLLAMA_TIMEOUT_SECONDS,
)
from core.parser import safely_parse_json
from llm.base_interface import LLMInterface
from llm.prompt_builder import build_prompt


class OllamaInterface(LLMInterface):
    """LLM adapter that sends parsing prompts to a local Ollama server."""

    def _build_prompt(self, text: str) -> str:
        return build_prompt(text)

    def _call_ollama(self, model_name: str, prompt: str) -> str:
        payload = {
            "model": model_name,
            "prompt": prompt,
            "stream": OLLAMA_STREAM,
            "options": {"temperature": OLLAMA_TEMPERATURE},
        }

        request = Request(
            OLLAMA_API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urlopen(request, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
                return response.read().decode("utf-8")
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Ollama HTTP {exc.code} for model '{model_name}': {error_body}"
            ) from exc
        except URLError as exc:
            raise ConnectionError(f"Failed to reach Ollama at {OLLAMA_API_URL}: {exc}") from exc

    def parse(self, text: str) -> dict[str, Any]:
        prompt = self._build_prompt(text)
        models_to_try: list[str] = [MODEL_NAME]
        models_to_try.extend([name for name in FALLBACK_MODEL_NAMES if name != MODEL_NAME])

        raw_body = ""
        errors: list[str] = []

        for model_name in models_to_try:
            try:
                raw_body = self._call_ollama(model_name, prompt)
                break
            except RuntimeError as exc:
                message = str(exc)
                if "not found" in message.lower():
                    errors.append(message)
                    continue
                raise
        else:
            joined = " | ".join(errors) if errors else "No model attempts were made."
            raise RuntimeError(f"No usable Ollama model found. Attempted {models_to_try}. {joined}")

        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Ollama returned malformed JSON envelope: {exc}") from exc

        llm_text = body.get("response", "")
        if not isinstance(llm_text, str) or not llm_text.strip():
            raise RuntimeError("Ollama response did not include a valid 'response' field.")

        return safely_parse_json(llm_text)
