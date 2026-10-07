"""
Central logging configuration.

Previously the console handler used '%(levelname)s: %(message)s', so anything read
from stdout or journalctl had no time reference at all, and most modules printed
with print() rather than logging. This gives every line a timestamp and a logger
name, and sends the same records to a rotating file.

Timestamps are emitted in UTC with an explicit offset so they are unambiguous when
correlated with database rows, which are also stored as aware UTC.
"""

import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
# ISO-8601 with an explicit +0000 so a log line can be matched to a DB timestamp.
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


def configure_logging(log_dir: "Path | None" = None, level: "int | None" = None) -> logging.Logger:
    """Install handlers on the root logger. Safe to call more than once."""
    global _CONFIGURED
    root = logging.getLogger()
    if _CONFIGURED:
        return root

    resolved_level: int = level if level is not None else getattr(
        logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO
    )

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    formatter.converter = time.gmtime  # UTC, matching what we store

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    log_dir = log_dir or Path(os.getenv("HIVE_BUCKET_PATH", Path(__file__).resolve().parent.parent / "hive_bucket")) / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "ai-hunter.log", maxBytes=10 * 1024 * 1024, backupCount=5
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as e:
        # Logging to a file is best-effort, but say so rather than losing it quietly.
        root.warning("file logging disabled, could not open %s: %s", log_dir, e)

    root.setLevel(resolved_level)

    # Playwright and asyncio are chatty at DEBUG and drown out agent activity.
    for noisy in ("asyncio", "urllib3", "websockets"):
        logging.getLogger(noisy).setLevel(max(resolved_level, logging.INFO))

    _CONFIGURED = True
    return root


def log_unhandled(logger: logging.Logger, context: str):
    """
    Return a done-callback that reports a background task dying.

    asyncio tasks swallow exceptions until the task is awaited or garbage collected,
    so a mission that crashes in the background would otherwise leave no trace.
    """
    import asyncio

    def _callback(task: "asyncio.Task"):
        if task.cancelled():
            logger.info("%s was cancelled", context)
            return
        exc = task.exception()
        if exc is not None:
            logger.error("%s failed: %s", context, exc, exc_info=exc)

    return _callback
