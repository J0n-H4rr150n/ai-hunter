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
        on_progress=None,
    ):
        self.model = model or Config.LLM_MODEL
        self.system_instruction = system_instruction
        self.base_url = (base_url or Config.LLM_BASE_URL).rstrip("/")
        self.temperature = Config.LLM_TEMPERATURE if temperature is None else temperature
        self.max_tokens = max_tokens or Config.LLM_MAX_TOKENS
        # Three distinct deadlines; see Config for how they are derived.
        self.stall_timeout = timeout or Config.LLM_STALL_TIMEOUT
        self.first_token_timeout = Config.LLM_FIRST_TOKEN_TIMEOUT
        self.total_timeout = Config.llm_total_timeout()
        self.supports_vision = Config.LLM_SUPPORTS_VISION
        # Called with (elapsed_seconds, tokens_so_far) while a slow generation runs,
        # so the UI can show the agent is thinking rather than looking hung.
        self.on_progress = on_progress
        self._endpoint = f"{self.base_url}/chat/completions"

    # -- prompt assembly ---------------------------------------------------

    def _build_content(self, parts: Any) -> List[Dict[str, Any]]:
        """Flatten a parts list (strings + Part images) into OpenAI content blocks."""
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

    # -- transport ---------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {Config.LLM_API_KEY}"}

    def _deadline_exceeded(self, started: float) -> bool:
        return (time.monotonic() - started) > self.total_timeout

    def _stream(self, payload: Dict[str, Any]):
        """
        Read the completion as a stream.

        Streaming is what makes a slow model safe to use: tokens arrive steadily, so
        the only deadline is the silence between them. A non-streaming request sends
        nothing until the whole answer is ready, which turns the read timeout into a
        total-duration limit and kills long but perfectly healthy generations.
        """
        started = time.monotonic()
        last_report = started
        last_chunk_at = started
        first_token_at = None
        chunks: List[str] = []
        reasoning: List[str] = []
        finish_reason = None
        usage = None

        with requests.post(
            self._endpoint,
            json=payload,
            headers=self._headers(),
            stream=True,
            # (connect, read). The socket deadline is the widest legitimate
            # silence — waiting for the first token. Once tokens flow, the tighter
            # stall limit is enforced in the loop below.
            timeout=(Config.LLM_CONNECT_TIMEOUT, self.first_token_timeout),
        ) as resp:
            resp.raise_for_status()

            # requests falls back to ISO-8859-1 for text/* responses that carry no
            # charset, and llama-server's text/event-stream does not. That silently
            # mangled every non-ASCII character: an em dash arrived as "â".
            # The OpenAI-compatible API is always UTF-8.
            resp.encoding = "utf-8"

            for raw in resp.iter_lines(decode_unicode=True):
                if raw is None:
                    continue
                line = raw.strip()
                if not line:
                    continue
                if not line.startswith("data:"):
                    continue

                data = line[5:].strip()
                if data == "[DONE]":
                    break

                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    # A malformed chunk is worth noting but not worth aborting on.
                    continue

                if event.get("usage"):
                    usage = event["usage"]

                for choice in event.get("choices", []):
                    delta = choice.get("delta") or {}
                    if delta.get("content"):
                        chunks.append(delta["content"])
                    if delta.get("reasoning_content"):
                        reasoning.append(delta["reasoning_content"])
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]

                now = time.monotonic()
                produced = len(chunks) + len(reasoning)
                if produced and first_token_at is None:
                    first_token_at = now
                if produced:
                    last_chunk_at = now

                # Distinct failures: a server that never starts, one that dies
                # mid-answer, and one that is simply taking too long overall.
                if first_token_at is None and (now - started) > self.first_token_timeout:
                    raise TimeoutError(
                        f"no first token after {self.first_token_timeout:.0f}s "
                        f"(prompt ingestion or a queued request should not take this long)"
                    )
                if first_token_at is not None and (now - last_chunk_at) > self.stall_timeout:
                    raise TimeoutError(
                        f"generation stalled: {self.stall_timeout:.0f}s with no token "
                        f"after {produced} tokens"
                    )

                if self.on_progress and (now - last_report) >= Config.LLM_PROGRESS_INTERVAL:
                    last_report = now
                    try:
                        self.on_progress(now - started, len(chunks) + len(reasoning))
                    except Exception:
                        pass   # progress reporting must never break generation

                if self._deadline_exceeded(started):
                    raise TimeoutError(
                        f"generation exceeded {self.total_timeout:.0f}s "
                        f"(budget {Config.LLM_MAX_TOKENS} tokens at a "
                        f"{Config.LLM_MIN_TOKENS_PER_SEC} tok/s floor) "
                        f"after {produced} tokens"
                    )

        text = "".join(chunks)
        if not text.strip() and reasoning:
            text = "".join(reasoning)
        return text, finish_reason, usage, {"usage": usage, "streamed": True}

    def _blocking(self, payload: Dict[str, Any]):
        """Non-streaming fallback, for servers that do not support SSE."""
        resp = requests.post(
            self._endpoint,
            json=payload,
            headers=self._headers(),
            timeout=(Config.LLM_CONNECT_TIMEOUT, self.total_timeout),
        )
        resp.raise_for_status()
        body = resp.json()
        choice = body["choices"][0]
        message = choice["message"]
        text = message.get("content") or ""
        if not text.strip() and message.get("reasoning_content"):
            text = message["reasoning_content"]
        return text, choice.get("finish_reason"), body.get("usage"), body

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
            "stream": Config.LLM_STREAM,
        }
        if Config.LLM_STREAM:
            # Ask for usage in the terminal chunk so token counts survive streaming.
            payload["stream_options"] = {"include_usage": True}
        if wants_json:
            payload["response_format"] = {"type": "json_object"}

        thinking = Config.LLM_ENABLE_THINKING and (Config.LLM_THINK_ON_JSON or not wants_json)
        if not thinking:
            # Qwen3's template honours this; servers that ignore it are unaffected.
            payload["chat_template_kwargs"] = {"enable_thinking": False}

        last_error: Optional[Exception] = None
        for attempt in range(Config.LLM_MAX_RETRIES):
            try:
                if Config.LLM_STREAM:
                    text, finish_reason, usage, body = self._stream(payload)
                else:
                    text, finish_reason, usage, body = self._blocking(payload)

                choice = {"finish_reason": finish_reason}

                if not text.strip():
                    # An empty completion usually means the prompt filled the context
                    # window or the generation budget went entirely on reasoning.
                    # Say which, rather than failing later on a JSON parse.
                    raise RuntimeError(
                        f"model returned an empty completion "
                        f"(finish_reason={finish_reason!r}, usage={usage}). "
                        f"The prompt is likely too long for the served context "
                        f"window, or max_tokens was consumed by reasoning."
                    )

                text = _extract_json(text) if wants_json else _strip_reasoning(text)

                if wants_json:
                    try:
                        json.loads(text)  # validate before handing back to the caller
                    except json.JSONDecodeError as e:
                        raise ValueError(
                            f"model did not return valid JSON ({e}); "
                            f"first 300 chars: {text[:300]!r}"
                        ) from e

                return LocalResponse(text, usage, body)

            except RuntimeError as e:
                # An empty completion is deterministic — the prompt does not fit, or
                # the token budget is exhausted. Retrying just burns the single
                # llama-server slot (--parallel 1) and blocks every other call for
                # minutes, so fail fast and let the caller shorten the prompt.
                last_error = e
                break

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
