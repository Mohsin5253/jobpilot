"""Live events for the dashboard: Postgres LISTEN/NOTIFY fanned out to Server-Sent Events.

Agents publish inside their own transaction (`publish(session, ...)`), so an event is delivered only once
its rows are committed and works across processes (API + separate workers). Each API process keeps one
LISTEN connection and hands events to the browser streams of the user they belong to.
"""

import asyncio
import contextlib
import json
import uuid
from collections import defaultdict

import psycopg
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.logging import log

CHANNEL = "jobpilot_events"


async def publish(session: AsyncSession, user_id: uuid.UUID | str, kind: str, **data) -> None:
    payload = json.dumps({"user_id": str(user_id), "kind": kind, **data}, default=str)
    if len(payload) > 7000:  # NOTIFY payloads are capped at 8000 bytes
        payload = json.dumps({"user_id": str(user_id), "kind": kind})
    await session.execute(text("SELECT pg_notify(:c, :p)"), {"c": CHANNEL, "p": payload})


class EventHub:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._task: asyncio.Task | None = None

    def subscribe(self, user_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subs[user_id].add(q)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._listen())
        return q

    def unsubscribe(self, user_id: str, q: asyncio.Queue) -> None:
        self._subs[user_id].discard(q)
        if not self._subs[user_id]:
            self._subs.pop(user_id, None)

    async def _listen(self) -> None:
        while self._subs:
            try:
                async with await psycopg.AsyncConnection.connect(settings.psycopg_conninfo, autocommit=True) as conn:
                    await conn.execute(f"LISTEN {CHANNEL}")
                    async for n in conn.notifies():
                        self._dispatch(n.payload)
                        if not self._subs:
                            return
            except (psycopg.Error, OSError) as exc:
                log.warning("events.listen_failed", error=str(exc))
                await asyncio.sleep(2)

    def _dispatch(self, raw: str) -> None:
        try:
            event = json.loads(raw)
        except ValueError:
            return
        for q in list(self._subs.get(event.get("user_id", ""), ())):
            with contextlib.suppress(asyncio.QueueFull):  # a stalled tab drops events; it refetches on reconnect
                q.put_nowait(event)

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None


hub = EventHub()
