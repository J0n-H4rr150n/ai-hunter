"""
Local LLM client (llama.cpp / llama-server).

Talks to an OpenAI-compatible /v1/chat/completions endpoint served by llama-server,
so no cloud provider or credentials are involved. The public surface intentionally
mirrors the small slice of the Vertex AI SDK the agents used before:

    model = LocalModel("qwen38-27b-q8", system_instruction="...")
    resp = model.generate_content([text, Part.from_data(jpeg, "image/jpeg")],
                                  generation_config={"response_mime_type": "application/json"})
    resp.text

That keeps agents/ unchanged apart from the import, and leaves one place to adjust
when the served model changes.
"""

import base64
import json
import re
import time
from typing import Any, Dict, List, Optional

import requests

from config.config import Config


class Part:
    """An inline binary prompt part (screenshots). Mirrors vertexai's Part.from_data."""

    def __init__(self, data: bytes, mime_type: str):
        self.data = data
        self.mime_type = mime_type

    @classmethod
    def from_data(cls, data: bytes, mime_type: str) -> "Part":
        return cls(data, mime_type)

    def to_data_uri(self) -> str:
        return f"data:{self.mime_type};base64,{base64.b64encode(self.data).decode()}"


class LocalResponse:
    """Minimal stand-in for the SDK response object: `.text` plus token usage."""

    def __init__(self, text: str, usage: Optional[Dict[str, Any]] = None, raw: Any = None):
        self.text = text
        self.usage = usage or {}
        self.raw = raw

    @property
    def prompt_token_count(self) -> int:
        return self.usage.get("prompt_tokens", 0)

    @property
    def candidates_token_count(self) -> int:
        return self.usage.get("completion_tokens", 0)


# Reasoning models (Qwen3 included) may emit a visible thinking block. llama-server
# usually splits it into `reasoning_content`, but strip it inline too as a fallback.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def _strip_reasoning(text: str) -> str:
    text = _THINK_RE.sub("", text)
    # An unterminated <think> means the model ran out of budget mid-thought.
    if "<think>" in text.lower():
        text = re.split(r"</?think>", text, flags=re.IGNORECASE)[-1]
    return text.strip()


def _extract_json(text: str) -> str:
    """
    Pull a JSON object out of a model response.

    Local models are less obedient than hosted ones about pure-JSON output, so peel
    off reasoning blocks and code fences, then fall back to brace matching.
    """
    text = _strip_reasoning(text)

    fenced = _FENCE_RE.match(text)
    if fenced:
        text = fenced.group(1).strip()

    if text.startswith("{") or text.startswith("["):
        return text

    # Brace-match the first balanced object, ignoring braces inside strings.
    start = text.find("{")
    if start == -1:
        return text

    depth = 0
    in_string = False
    escaped = False
    for i, ch in enumerate(text[start:], start):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return text[start:]


class LocalModel:
    """A chat model served by llama-server."""

    def __init__(
        self,
        model: Optional[str] = None,
        system_instruction: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ):
        self.model = model or Config.LLM_MODEL
        self.system_instruction = system_instruction
        self.base_url = (base_url or Config.LLM_BASE_URL).rstrip("/")
        self.temperature = Config.LLM_TEMPERATURE if temperature is None else temperature
        self.max_tokens = max_tokens or Config.LLM_MAX_TOKENS
        self.timeout = timeout or Config.LLM_TIMEOUT
        self.supports_vision = Config.LLM_SUPPORTS_VISION
        self._endpoint = f"{self.base_url}/chat/completions"

    # -- prompt assembly ---------------------------------------------------

    def _build_content(self, parts: Any) -> List[Dict[str, Any]]:
        """Flatten a Gemini-style parts list into OpenAI content blocks."""
        if not isinstance(parts, (list, tuple)):
            parts = [parts]

        content: List[Dict[str, Any]] = []
        text_buffer: List[str] = []

        def flush():
            if text_buffer:
                joined = "\n".join(t for t in text_buffer if t)
                if joined.strip():
                    content.append({"type": "text", "text": joined})
                text_buffer.clear()

        for part in parts:
            if isinstance(part, Part):
                if not self.supports_vision:
                    text_buffer.append("[screenshot omitted: model has no vision support]")
                    continue
                flush()
                content.append({
                    "type": "image_url",
                    "image_url": {"url": part.to_data_uri()},
                })
            elif isinstance(part, bytes):
                flush()
                content.append({
                    "type": "image_url",
                    "image_url": {"url": Part(part, "image/jpeg").to_data_uri()},
                })
            elif part is not None:
                text_buffer.append(str(part))

        flush()
        return content or [{"type": "text", "text": ""}]

    # -- generation --------------------------------------------------------

    def generate_content(
        self,
        parts: Any,
        generation_config: Optional[Dict[str, Any]] = None,
        safety_settings: Any = None,   # accepted and ignored: no content filter locally
        **kwargs,
    ) -> LocalResponse:
        generation_config = generation_config or {}
        wants_json = generation_config.get("response_mime_type") == "application/json"

        messages: List[Dict[str, Any]] = []
        if self.system_instruction:
            messages.append({"role": "system", "content": self.system_instruction})

        content = self._build_content(parts)
        if wants_json:
            content.append({
                "type": "text",
                "text": "Respond with a single valid JSON object and nothing else. "
                        "No markdown fences, no commentary.",
            })
        messages.append({"role": "user", "content": content})

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": generation_config.get("temperature", self.temperature),
            "max_tokens": generation_config.get("max_output_tokens", self.max_tokens),
            "stream": False,
        }
        if wants_json:
            payload["response_format"] = {"type": "json_object"}

        last_error: Optional[Exception] = None
        for attempt in range(Config.LLM_MAX_RETRIES):
            try:
                resp = requests.post(
                    self._endpoint,
                    json=payload,
                    timeout=self.timeout,
                    headers={"Authorization": f"Bearer {Config.LLM_API_KEY}"},
                )
                resp.raise_for_status()
                body = resp.json()

                message = body["choices"][0]["message"]
                text = message.get("content") or ""
                # llama-server returns thinking separately when reasoning is split out.
                if not text.strip() and message.get("reasoning_content"):
                    text = message["reasoning_content"]

                text = _extract_json(text) if wants_json else _strip_reasoning(text)

                if wants_json:
                    json.loads(text)  # validate before handing back to the caller

                return LocalResponse(text, body.get("usage"), body)

            except Exception as e:   # noqa: BLE001 - retry on transport or parse failure
                last_error = e
                if attempt < Config.LLM_MAX_RETRIES - 1:
                    time.sleep(Config.LLM_RETRY_DELAY * (attempt + 1))

        raise RuntimeError(
            f"Local LLM call failed after {Config.LLM_MAX_RETRIES} attempts "
            f"({self._endpoint}, model={self.model}): {last_error}"
        ) from last_error

    # -- health ------------------------------------------------------------

    def health_check(self) -> Dict[str, Any]:
        """Report whether the model server is reachable and what it is serving."""
        try:
            resp = requests.get(f"{self.base_url}/models", timeout=5)
            resp.raise_for_status()
            served = [m.get("id") for m in resp.json().get("data", [])]
            return {"ok": True, "endpoint": self.base_url, "models": served}
        except Exception as e:   # noqa: BLE001
            return {"ok": False, "endpoint": self.base_url, "error": str(e)}


# Backwards-compatible alias so existing call sites read naturally.
GenerativeModel = LocalModel
