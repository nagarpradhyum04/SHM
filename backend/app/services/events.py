"""Timeline event log and an in-process broadcaster for server-sent events."""
from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

from sqlalchemy.orm import Session

from app.models import EventLog
from app.timeutil import utcnow


class Broadcaster:
    """Fan-out of lightweight change notifications to SSE subscribers.

    Notifications are hints ("defects changed for asset X"); clients refetch
    authoritative data over REST.
    """

    def __init__(self) -> None:
        self._subscribers: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        with self._lock:
            self._subscribers.add((asyncio.get_running_loop(), q))
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers = {(l, s) for (l, s) in self._subscribers if s is not q}

    def publish(self, topic: str, payload: dict[str, Any] | None = None) -> None:
        message = json.dumps({"topic": topic, "payload": payload or {}, "ts": utcnow().isoformat()})
        with self._lock:
            subs = list(self._subscribers)
        for loop, q in subs:
            try:
                loop.call_soon_threadsafe(_put_nowait, q, message)
            except RuntimeError:  # loop closed
                self.unsubscribe(q)


def _put_nowait(q: asyncio.Queue, message: str) -> None:
    if q.full():
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            pass
    q.put_nowait(message)


broadcaster = Broadcaster()


def log_event(
    db: Session,
    *,
    event_type: str,
    title: str,
    asset_id: str | None = None,
    component_id: str | None = None,
    device_id: str | None = None,
    ref_type: str | None = None,
    ref_id: str | None = None,
    priority: str | None = None,
    data_source: str | None = None,
    actor: str | None = None,
    data: dict | None = None,
    ts=None,
) -> EventLog:
    ev = EventLog(
        asset_id=asset_id,
        component_id=component_id,
        device_id=device_id,
        event_type=event_type,
        title=title,
        ref_type=ref_type,
        ref_id=ref_id,
        priority=priority,
        data_source=data_source,
        actor=actor,
        data=data,
        ts=ts or utcnow(),
    )
    db.add(ev)
    return ev
