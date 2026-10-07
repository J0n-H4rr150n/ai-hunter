"""
Cooperative pause/stop signalling for a running mission.

The mission body is async but does its real work in synchronous calls (Playwright on a
dedicated thread, blocking LLM HTTP requests), so the signal has to be readable from
any thread. `threading.Event` covers that; asyncio task cancellation covers the rest.

Stopping is two-sided, and both sides matter:

  * This object makes the loop *refuse to continue* — every checkpoint raises
    `MissionStopped`, so the mission cannot advance another step.
  * The caller additionally cancels the mission task and closes the browser, which is
    what kills work already in flight (a page load, a fuzz batch).

Without the second half a stop would only land after the current long operation
finished, which is the behaviour this replaces.
"""

import threading


class MissionStopped(Exception):
    """Raised at a checkpoint when a stop has been requested."""


class MissionAborted(Exception):
    """
    Raised when a mission ends early for a reason that is not a user stop:
    planning failed, the operator rejected the plan, and so on.

    This exists because the abort paths used to `return` instead, and the caller
    could not tell an abort apart from a normal finish — so every aborted mission
    was recorded as "completed".
    """

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class MissionControl:
    def __init__(self):
        self._stop = threading.Event()
        self._pause = threading.Event()
        # Set when not paused, so waiters can block on a single primitive.
        self._unpaused = threading.Event()
        self._unpaused.set()

    # -- signals -----------------------------------------------------------

    def request_stop(self) -> None:
        self._stop.set()
        # Release anything blocked in a pause so it can observe the stop.
        self._unpaused.set()

    def request_pause(self) -> None:
        self._pause.set()
        self._unpaused.clear()

    def resume(self) -> None:
        self._pause.clear()
        self._unpaused.set()

    # -- state -------------------------------------------------------------

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    @property
    def paused(self) -> bool:
        return self._pause.is_set() and not self._stop.is_set()

    # -- checks ------------------------------------------------------------

    def raise_if_stopped(self) -> None:
        if self._stop.is_set():
            raise MissionStopped("mission stopped by user")

    def checkpoint(self, on_pause=None, on_resume=None) -> None:
        """
        Call between units of work.

        Raises `MissionStopped` if a stop was requested, otherwise blocks for as long
        as the mission is paused. `on_pause` / `on_resume` are optional callbacks used
        to report the transition to the UI exactly once.
        """
        self.raise_if_stopped()

        if not self._pause.is_set():
            return

        if on_pause:
            on_pause()

        while True:
            # Timed wait so a stop issued during a pause is noticed promptly.
            self._unpaused.wait(timeout=0.25)
            self.raise_if_stopped()
            if not self._pause.is_set():
                break

        if on_resume:
            on_resume()
