"""
Durable event bus for mission activity.

Replaces Redis pub/sub, which was fire-and-forget: if no browser happened to be
connected when an event was published, it was gone. In one recorded test run 125
events were published to zero subscribers, so the mission's entire narrative was
lost even though the mission itself ran fine.

Every event is now written to `activity_logs` *before* it is fanned out, and the
full event payload is kept in the metadata column so a replay is lossless. The feed
can therefore be rebuilt on page load or after a reconnect, and the mission history
survives a server restart.

Fan-out is in-process: subscribers are asyncio queues belonging to SSE connections.
A slow or dead client cannot block a publish — its queue is bounded and drops with a
warning rather than stalling the mission.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional

logger = logging.getLogger(__name__)

# Bounded so one wedged browser tab cannot grow without limit.
SUBSCRIBER_QUEUE_SIZE = 1000


class Subscription:
    """One connected consumer (typically an SSE stream)."""

    def __init__(self, bus: "EventBus", mission_id: Optional[int] = None):
        self._bus = bus
        self.mission_id = mission_id
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        self.dropped = 0

    def wants(self, event: Dict[str, Any]) -> bool:
        if self.mission_id is None:
            return True
        return event.get("mission_id") in (None, self.mission_id)

    async def __aenter__(self) -> "Subscription":
        self._bus._subscribers.add(self)
        return self

    async def __aexit__(self, *exc) -> None:
        self._bus._subscribers.discard(self)

    async def events(self) -> AsyncIterator[Dict[str, Any]]:
        while True:
            yield await self.queue.get()


class EventBus:
    """Persist-then-broadcast event bus."""

    def __init__(self, db=None):
        self.db = db
        self._subscribers: set = set()

    # -- lifecycle (kept so callers don't need to care which bus they have) ----

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        self._subscribers.clear()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    # -- publishing ------------------------------------------------------------

    async def publish_event(self, channel: str, event_data: Dict[str, Any]) -> None:
        """
        Record an event, then hand it to every interested subscriber.

        `channel` is accepted for call-site compatibility; routing is by mission_id.
        """
        event = dict(event_data)
        event.setdefault("timestamp", datetime.now(timezone.utc).isoformat())

        await self._persist(event)
        self._broadcast(event)

    async def publish_mission_event(self, mission_id: int, event_type: str, data: Dict[str, Any]) -> None:
        payload = dict(data)
        payload.update({"type": event_type, "mission_id": mission_id})
        await self.publish_event(f"mission:{mission_id}", payload)

    async def _persist(self, event: Dict[str, Any]) -> None:
        mission_id = event.get("mission_id")
        if self.db is None or mission_id is None:
            # Events without a mission (global status pings) have nowhere to live in
            # activity_logs, which is keyed by mission. They are still broadcast.
            return

        screenshot = event.get("screenshot") or {}
        try:
            await self.db.save_activity_log(
                mission_id=mission_id,
                message=event.get("message") or event.get("type", "event"),
                message_type=event.get("type", "log"),
                screenshot_path=screenshot.get("path"),
                metadata=event,
            )
        except Exception as e:
            # Never let a logging failure take down a mission, but never hide it.
            logger.error("could not persist event for mission %s: %s", mission_id, e, exc_info=True)

    def _broadcast(self, event: Dict[str, Any]) -> None:
        for sub in list(self._subscribers):
            if not sub.wants(event):
                continue
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                sub.dropped += 1
                logger.warning(
                    "subscriber queue full (mission=%s), dropped %d event(s) for this client; "
                    "it can recover via replay",
                    sub.mission_id, sub.dropped,
                )

    # -- consuming -------------------------------------------------------------

    def subscribe(self, mission_id: Optional[int] = None) -> Subscription:
        return Subscription(self, mission_id)

    async def replay(self, mission_id: int, limit: int = 500, after_id: int = 0) -> List[Dict[str, Any]]:
        """Rebuild the feed from storage. This is what makes a reload lossless."""
        if self.db is None:
            return []
        rows = await self.db.get_mission_activity_logs(mission_id, limit=limit, after_id=after_id)

        events: List[Dict[str, Any]] = []
        for row in rows:
            meta = row.get("metadata")
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except json.JSONDecodeError:
                    meta = None
            event = dict(meta) if isinstance(meta, dict) else {
                "type": row.get("message_type", "mission_log"),
                "mission_id": mission_id,
            }
            # Structured events (plan_generated, tool_approval_request, ...) carry no
            # "message" of their own. The stored column holds the fallback label, so
            # a replayed feed shows the event type instead of "undefined".
            event.setdefault("message", row.get("message"))
            event.setdefault("type", row.get("message_type", "mission_log"))
            event.setdefault("mission_id", mission_id)
            ts = row.get("timestamp")
            event["timestamp"] = ts.isoformat() if hasattr(ts, "isoformat") else ts
            event["_log_id"] = row.get("id")
            events.append(event)
        return events
