"""
Records every LLM call to `llm_traces`.

The observability layer for this already existed — an LLMTrace dataclass with 40
fields, a save_llm_trace writer, a migration, and a doc describing it — but
LLMTracer was never instantiated anywhere, so the table was always empty and not a
single model call was ever traced.

This records from the one place every call passes through, LocalModel, rather than
from each agent, so a new agent is traced without anyone remembering to add it.
Like ToolRecorder it works from worker threads as well as the event loop.
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from core.llm_tracer import LLMTrace, LLMCallStatus

logger = logging.getLogger(__name__)

# Prompts contain whole DOM dumps; keep rows readable.
MAX_PROMPT_CHARS = int(os.getenv("LLM_TRACE_PROMPT_CHARS", "8000"))
MAX_RESPONSE_CHARS = int(os.getenv("LLM_TRACE_RESPONSE_CHARS", "8000"))
DB_TIMEOUT_SECONDS = float(os.getenv("LLM_TRACE_TIMEOUT", "120"))


def _clip(text: Optional[str], limit: int) -> Optional[str]:
    if text is None:
        return None
    text = str(text)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n...[clipped, {len(text)} chars total]"


class LLMRecorder:
    """Writes one row per model call for a mission."""

    def __init__(self, db=None, mission_id: Optional[int] = None, loop=None,
                 session_id: Optional[str] = None):
        self.db = db
        self.mission_id = mission_id
        self.loop = loop
        self.session_id = session_id

    @property
    def enabled(self) -> bool:
        return self.db is not None and self.loop is not None

    def record(
        self,
        *,
        model: str,
        agent_name: Optional[str],
        system_prompt: Optional[str],
        user_prompt: str,
        response: Optional[str],
        started_at: datetime,
        ended_at: datetime,
        usage: Optional[Dict[str, Any]] = None,
        finish_reason: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        status: str = LLMCallStatus.SUCCESS.value,
        error: Optional[str] = None,
        retry_count: int = 0,
    ) -> None:
        if not self.enabled:
            return

        usage = usage or {}
        elapsed_ms = int((ended_at - started_at).total_seconds() * 1000)
        output_tokens = usage.get("completion_tokens")

        trace = LLMTrace(
            trace_id=str(uuid.uuid4()),
            session_id=self.session_id,
            mission_id=self.mission_id,
            llm_model=model,
            llm_provider="local_llama",
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=_clip(system_prompt, MAX_PROMPT_CHARS),
            user_prompt=_clip(user_prompt, MAX_PROMPT_CHARS) or "",
            input_tokens=usage.get("prompt_tokens"),
            llm_response=_clip(response, MAX_RESPONSE_CHARS),
            output_tokens=output_tokens,
            timestamp_start=started_at.isoformat(),
            timestamp_end=ended_at.isoformat(),
            finish_reason=finish_reason,
            status=status,
            error_message=error,
            retry_count=retry_count,
            agent_name=agent_name,
        )
        trace.calculate_derived_metrics()
        # Local inference is free; the field exists for hosted providers.
        trace.estimated_cost_usd = 0.0

        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None

        if running is self.loop:
            asyncio.ensure_future(self._save(trace))
            return

        # From a worker thread: fire and forget, a trace must never slow a mission.
        try:
            asyncio.run_coroutine_threadsafe(self._save(trace), self.loop)
        except Exception as e:   # noqa: BLE001
            logger.error("could not schedule LLM trace: %s", e, exc_info=True)

    async def _save(self, trace: LLMTrace) -> None:
        try:
            await self.db.save_llm_trace(trace)
        except Exception as e:   # noqa: BLE001
            logger.error("could not save LLM trace: %s", e, exc_info=True)


NULL_LLM_RECORDER = LLMRecorder()
