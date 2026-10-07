"""
Records every tool call and its response.

`tool_executions` existed as a table from the first migration but had no writer
anywhere, so there was no record of what the agent actually did — only prose in the
activity feed. This fills it.

Tool calls happen on two kinds of thread:

  * the asyncio event loop (backend orchestration), and
  * worker threads (`run_loop` and the Playwright executor),

so the recorder works from either. From a worker it marshals the coroutine onto the
main loop with `run_coroutine_threadsafe` and waits briefly for the result, the same
pattern the UI callback already uses.
"""

import asyncio
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Tool payloads include DOM dumps and raw page source. Keep rows readable and the
# database small; the untruncated artefacts are already written to hive_bucket.
MAX_FIELD_CHARS = 4000
DB_TIMEOUT_SECONDS = 10


def truncate(value: Any, limit: int = MAX_FIELD_CHARS) -> Any:
    """Shrink large values for storage, saying so rather than silently cutting."""
    if isinstance(value, str) and len(value) > limit:
        return {
            "_truncated": True,
            "_original_chars": len(value),
            "preview": value[:limit],
        }
    if isinstance(value, dict):
        return {k: truncate(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        if len(value) > 50:
            return {
                "_truncated": True,
                "_original_items": len(value),
                "preview": [truncate(v, limit) for v in value[:50]],
            }
        return [truncate(v, limit) for v in value]
    if isinstance(value, bytes):
        return {"_bytes": len(value)}
    return value


class ToolRecorder:
    """Writes tool calls for one mission."""

    def __init__(self, db=None, mission_id: Optional[int] = None, loop=None):
        self.db = db
        self.mission_id = mission_id
        self.loop = loop

    def bind(self, db, mission_id: int, loop) -> "ToolRecorder":
        self.db, self.mission_id, self.loop = db, mission_id, loop
        return self

    @property
    def enabled(self) -> bool:
        return self.db is not None and self.mission_id is not None

    # -- cross-thread plumbing ------------------------------------------------

    def _run(self, coro, wait: bool = True):
        """Run a DB coroutine from whichever thread we happen to be on."""
        if self.loop is None:
            return None
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None

        if running is self.loop:
            # Already on the loop: schedule without blocking it.
            return asyncio.ensure_future(coro)

        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        if not wait:
            return None
        try:
            return future.result(timeout=DB_TIMEOUT_SECONDS)
        except Exception as e:
            logger.error("tool recording failed: %s", e, exc_info=True)
            return None

    # -- recording ------------------------------------------------------------

    def start(self, tool_name: str, inputs: Dict[str, Any]) -> Optional[int]:
        if not self.enabled or self.db is None:
            return None
        return self._run(
            self.db.start_tool_execution(
                self.mission_id, tool_name, truncate(inputs or {}),
                datetime.now(timezone.utc),
            )
        )

    def finish(self, execution_id: Optional[int], outputs: Any = None,
               status: str = "success", error: Optional[str] = None) -> None:
        if execution_id is None or not self.enabled or self.db is None:
            return
        payload = outputs if isinstance(outputs, dict) else {"result": outputs}
        self._run(
            self.db.complete_tool_execution(
                execution_id, truncate(payload), status, error
            ),
            wait=False,
        )

    @contextmanager
    def record(self, tool_name: str, inputs: Dict[str, Any]):
        """
        Wrap a tool call.

            with recorder.record("navigate", {"url": url}) as call:
                result = browser.navigate(url)
                call.result = result

        Failures are recorded with the exception and re-raised; the record is never
        the reason a tool call changes behaviour.
        """
        execution_id = self.start(tool_name, inputs)

        class _Call:
            result: Any = None

        call = _Call()
        try:
            yield call
        except Exception as e:
            self.finish(execution_id, {"error": str(e)}, status="failed",
                        error=f"{type(e).__name__}: {e}")
            raise
        else:
            self.finish(execution_id, call.result, status="success")


# A recorder that does nothing, so call sites need no conditionals.
NULL_RECORDER = ToolRecorder()
