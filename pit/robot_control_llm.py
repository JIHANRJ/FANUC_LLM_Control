"""Professional, minimal abstraction for local structured LLM text commands."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config import OLLAMA_API_URL, OLLAMA_STREAM, OLLAMA_TEMPERATURE, OLLAMA_TIMEOUT_SECONDS
from core.parser import safely_parse_json


def _schema_as_text(output_json: dict[str, Any] | str) -> str:
    if isinstance(output_json, dict):
        return json.dumps(output_json, indent=2)
    return output_json


def _build_text_command_prompt(output_json: dict[str, Any] | str, prompt: str) -> str:
    schema_text = _schema_as_text(output_json)
    return (
        "You are a robot command parser.\n"
        "Return ONLY valid JSON. No markdown. No explanation.\n"
        "Match this output JSON schema exactly:\n"
        f"{schema_text}\n\n"
        f"Input: {prompt}\n"
        "Output:"
    )


def _call_ollama(
    model_name: str,
    model_parameters: dict[str, Any] | None,
    prompt: str,
) -> str:
    params = dict(model_parameters or {})

    api_url = str(params.pop("api_url", OLLAMA_API_URL))
    stream = bool(params.pop("stream", OLLAMA_STREAM))
    temperature = float(params.pop("temperature", OLLAMA_TEMPERATURE))
    timeout_seconds = float(params.pop("timeout_seconds", OLLAMA_TIMEOUT_SECONDS))

    ollama_options: dict[str, Any] = {"temperature": temperature}
    ollama_options.update(params)

    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": stream,
        "options": ollama_options,
    }

    request = Request(
        api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw_body = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise ConnectionError(f"Failed to reach Ollama at {api_url}: {exc}") from exc

    envelope = json.loads(raw_body)
    llm_response_text = envelope.get("response", "")
    if not isinstance(llm_response_text, str) or not llm_response_text.strip():
        raise RuntimeError("Ollama response missing usable 'response' text.")

    return llm_response_text


class RobotControlLLM:
    """Simple SDK-style entrypoint for structured local Ollama calls."""

    @staticmethod
    def TextCommand(
        model_name: str,
        model_parameters: dict[str, Any] | None,
        output_json: dict[str, Any] | str,
        prompt: str,
    ) -> dict[str, Any]:
        """Run one local Ollama call and return structured JSON output.

        Args:
            model_name: Ollama model tag, for example 'llama3.1:8b'.
            model_parameters: Extra model options. Supports:
                - temperature (float)
                - stream (bool)
                - timeout_seconds (float)
                - api_url (str)
                - any extra Ollama options keys (passed through)
            output_json: Expected JSON schema or schema-like text.
            prompt: User instruction text.
        """
        full_prompt = _build_text_command_prompt(output_json=output_json, prompt=prompt)
        llm_response_text = _call_ollama(
            model_name=model_name,
            model_parameters=model_parameters,
            prompt=full_prompt,
        )
        return safely_parse_json(llm_response_text)

    @staticmethod
    def PromptCommand(
        model_name: str,
        model_parameters: dict[str, Any] | None,
        prompt: str,
        output_json: dict[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        """Run one Ollama call with a fully composed prompt and parse JSON response."""
        final_prompt = prompt
        if output_json is not None:
            schema_text = _schema_as_text(output_json)
            final_prompt = (
                f"{prompt}\n\n"
                "Strict output requirement:\n"
                "Return ONLY valid JSON matching this schema exactly:\n"
                f"{schema_text}\n"
            )

        llm_response_text = _call_ollama(
            model_name=model_name,
            model_parameters=model_parameters,
            prompt=final_prompt,
        )
        return safely_parse_json(llm_response_text)


# Alias kept intentionally for user-requested naming style.
class RobotControlLMM(RobotControlLLM):
    """Compatibility alias for RobotControlLLM."""
