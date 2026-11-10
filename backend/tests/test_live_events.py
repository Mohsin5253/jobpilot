"""New matches reach the open dashboard through Postgres LISTEN/NOTIFY, only after their rows commit."""

import asyncio
import uuid

from app.db import session_scope
from app.services.events import EventHub, publish


async def test_events_reach_only_their_user_after_commit():
    hub = EventHub()
    me, other = str(uuid.uuid4()), str(uuid.uuid4())
    mine, theirs = hub.subscribe(me), hub.subscribe(other)
    await asyncio.sleep(0.3)  # LISTEN is up
    async with session_scope() as s:
        await publish(s, me, "new_matches", count=1, fits=[{"match_id": "m1", "title": "ML Intern", "company": "Acme", "score": 82}])
        await asyncio.sleep(0.3)
        assert mine.empty()  # not delivered before commit
    event = await asyncio.wait_for(mine.get(), timeout=3)
    assert event["kind"] == "new_matches" and event["fits"][0]["score"] == 82
    assert theirs.empty()
    hub.unsubscribe(me, mine)
    hub.unsubscribe(other, theirs)
    await hub.close()
