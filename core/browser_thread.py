"""
Thread confinement for the synchronous Playwright browser.

Playwright's sync API binds its objects to the thread (and greenlet) that created
them, and it refuses to start at all on a thread running an asyncio loop. The mission
code is async and interleaves `await db...` with direct browser calls, so neither
"build it on the event loop" nor "run the whole mission in a worker" works.

`ThreadedBrowser` resolves that by owning a single dedicated worker thread and
marshalling every attribute read and method call onto it. Call sites are unchanged:

    browser = ThreadedBrowser(lambda: SoMBrowser(headless=True))
    browser.navigate(url)            # runs on the browser thread
    browser.page.title()             # nested objects are proxied too

Calls block the caller until the browser thread returns, which matches the previous
synchronous behaviour.
"""

import concurrent.futures
import os
import signal
from typing import Any, Callable, List

# Values safe to hand back as-is. Anything else may be a Playwright handle that
# would explode if touched from another thread, so it gets proxied instead.
_PASSTHROUGH = (str, bytes, bytearray, int, float, bool, complex, type(None))
_CONTAINERS = (list, dict, tuple, set, frozenset)


def _wrap(value: Any, submit: Callable) -> Any:
    if isinstance(value, _PASSTHROUGH) or isinstance(value, _CONTAINERS):
        return value
    return _ThreadBound(value, submit)


class _ThreadBound:
    """Proxy that routes attribute access and calls onto the owning thread."""

    __slots__ = ("_obj", "_submit")

    def __init__(self, obj: Any, submit: Callable):
        object.__setattr__(self, "_obj", obj)
        object.__setattr__(self, "_submit", submit)

    def __getattr__(self, name: str) -> Any:
        obj = object.__getattribute__(self, "_obj")
        submit = object.__getattribute__(self, "_submit")
        return _wrap(submit(getattr, obj, name), submit)

    def __setattr__(self, name: str, value: Any) -> None:
        obj = object.__getattribute__(self, "_obj")
        submit = object.__getattribute__(self, "_submit")
        submit(setattr, obj, name, value)

    def __call__(self, *args, **kwargs) -> Any:
        obj = object.__getattribute__(self, "_obj")
        submit = object.__getattribute__(self, "_submit")
        return _wrap(submit(obj, *args, **kwargs), submit)

    def __repr__(self) -> str:
        return f"<thread-bound {object.__getattribute__(self, '_obj')!r}>"


class ThreadedBrowser:
    """A SoMBrowser (or similar) confined to one dedicated thread."""

    def __init__(self, factory: Callable[[], Any]):
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="playwright"
        )
        self._closed = False
        # The factory itself must run on the worker thread: that is where
        # sync_playwright().start() needs to happen.
        self._target = self._submit(factory)

    def _submit(self, fn: Callable, *args, **kwargs) -> Any:
        if self._closed:
            raise RuntimeError("browser has already been closed")
        return self._executor.submit(fn, *args, **kwargs).result()

    def __getattr__(self, name: str) -> Any:
        # Only reached for names not in __dict__, so internals never recurse here.
        target = self.__dict__.get("_target")
        if target is None:
            raise AttributeError(name)
        return _wrap(self._submit(getattr, target, name), self._submit)

    def close(self) -> None:
        """Graceful shutdown. Blocks behind any work already on the browser thread."""
        if self._closed:
            return
        try:
            self._submit(self._target.close)
        finally:
            self._closed = True
            self._executor.shutdown(wait=False)

    def kill(self) -> int:
        """
        Force shutdown for a user-requested stop.

        `close()` is queued onto the browser thread, so it cannot interrupt a
        navigation or fuzz batch already running there — it waits for it, which makes
        a "force stop" take as long as the thing it is meant to abort. Killing the
        Chromium processes instead makes the in-flight call fail immediately, which
        unblocks the thread. Returns how many processes were signalled.
        """
        self._closed = True
        killed = _kill_browser_processes()
        self._executor.shutdown(wait=False)
        return killed

    @property
    def raw(self) -> Any:
        """The underlying object. Only touch this from the browser thread."""
        return self._target


def _descendant_pids(root: int) -> List[int]:
    """Every descendant of `root`, read straight from /proc."""
    children = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat", "rb") as fh:
                data = fh.read().decode("utf-8", "replace")
            # comm can contain spaces and parens, so parse after the final ')'.
            ppid = int(data[data.rindex(")") + 2:].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        children.setdefault(ppid, []).append(int(entry))

    out, stack = [], [root]
    while stack:
        for child in children.get(stack.pop(), []):
            out.append(child)
            stack.append(child)
    return out


def _kill_browser_processes() -> int:
    """SIGKILL any Chromium processes this process launched."""
    killed = 0
    for pid in _descendant_pids(os.getpid()):
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                cmdline = fh.read().decode("utf-8", "replace")
        except OSError:
            continue
        if not any(m in cmdline for m in ("chrome", "chromium", "headless_shell")):
            continue
        try:
            os.kill(pid, signal.SIGKILL)
            killed += 1
        except OSError:
            pass
    return killed
