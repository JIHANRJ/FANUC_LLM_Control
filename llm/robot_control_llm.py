"""Simple SDK-style abstraction for structured LLM command calls."""

from __future__ import annotations

import json
from time import perf_counter
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config import OLLAMA_API_URL, OLLAMA_STREAM, OLLAMA_TEMPERATURE, OLLAMA_TIMEOUT_SECONDS
from core.normalizer import normalize_command
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


def _build_dialogue_prompt(context: dict[str, Any]) -> str:
    return (
        "You are CRX, a warm and helpful warehouse assistant speaking to a human customer.\n"
        "Tone: friendly, natural, conversational, and concise.\n"
        "Use 1 to 2 short sentences, max 40 words.\n"
        "Do NOT sound robotic and do NOT use phrases like 'systems', 'parameters', 'processing', or 'non-zero'.\n"
        "Do NOT use quotation marks around your reply.\n"
        "Never mention JSON, registers, code, prompts, or internal systems.\n"
        "Only reference products from available_products and keep names exactly as provided.\n"
        "Do not mention prices, currency, discounts, or inventory quantities unless explicitly present in context.\n"
        "Do not invent facts that are not in the context.\n"
        "If no valid order was understood, ask one short clarification question.\n\n"
        f"Context: {json.dumps(context, ensure_ascii=True)}\n\n"
        "CRX reply:"
    )


def _call_ollama(model_name: str, model_parameters: dict[str, Any] | None, prompt: str) -> str:
    params = dict(model_parameters or {})

    api_url = str(params.pop("api_url", OLLAMA_API_URL))
    stream = bool(params.pop("stream", OLLAMA_STREAM))
    temperature = float(params.pop("temperature", OLLAMA_TEMPERATURE))
    timeout_seconds = float(params.pop("timeout_seconds", OLLAMA_TIMEOUT_SECONDS))

    ollama_options: dict[str, Any] = {"temperature": temperature}
    # Set default num_predict to 1024 to allow longer output sequences
    if "num_predict" not in params:
        params["num_predict"] = 1024
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
    except TimeoutError as exc:
        raise TimeoutError(
            f"Ollama request timed out after {timeout_seconds}s for model {model_name!r}. "
            "Increase timeout_seconds for heavier models."
        ) from exc
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise ConnectionError(
            f"Failed to reach Ollama at {api_url}: {exc}. "
            "Start Ollama with 'ollama serve' or set OLLAMA_API_URL to the reachable endpoint."
        ) from exc

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
        """Parse user prompt with Ollama and return parsed + normalized output.
        
        Returns:
            {
                "parsed_output": <raw parsed JSON>,
                "normalized_output": <canonicalized command>,
                "model": <model_name>,
                "elapsed_ms": <ms taken>
            }
        """
        full_prompt = _build_text_command_prompt(output_json=output_json, prompt=prompt)
        started = perf_counter()
        llm_response_text = _call_ollama(
            model_name=model_name,
            model_parameters=model_parameters,
            prompt=full_prompt,
        )
        parsed_output = safely_parse_json(llm_response_text)
        normalized_output = normalize_command(parsed_output)

        return {
            "parsed_output": parsed_output,
            "normalized_output": normalized_output,
            "model": model_name,
            "elapsed_ms": round((perf_counter() - started) * 1000.0, 2),
        }

    @staticmethod
    def DialogueResponse(
        model_name: str,
        model_parameters: dict[str, Any] | None,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate a natural conversational response from structured context."""
        full_prompt = _build_dialogue_prompt(context=context)
        started = perf_counter()
        llm_response_text = _call_ollama(
            model_name=model_name,
            model_parameters=model_parameters,
            prompt=full_prompt,
        )

        cleaned = " ".join(llm_response_text.strip().split())
        return {
            "response": cleaned,
            "model": model_name,
            "elapsed_ms": round((perf_counter() - started) * 1000.0, 2),
        }


class RobotControlLMM(RobotControlLLM):
    """Compatibility alias for RobotControlLLM."""
