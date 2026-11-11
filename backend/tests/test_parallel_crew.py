"""The crew runs as parallel lanes: agents whose inputs are ready run at the same time."""

import asyncio
import time

from langgraph.checkpoint.memory import MemorySaver

from app.agents import graph as crew


async def test_independent_agents_overlap(monkeypatch):
    spans: dict[str, tuple[float, float]] = {}

    def fake(name: str, out: dict):
        async def run(state):
            start = time.perf_counter()
            await asyncio.sleep(1.0 if name == "researcher" else 0.3)
            spans[name] = (start, time.perf_counter())
            return {**out, "done": [name]}

        return run

    outputs = {
        "researcher": {},
        "scout": {"new_job_ids": ["j1"]},
        "verifier": {"new_job_ids": ["j1"]},
        "matcher": {"match_ids": ["m1"], "shortlist_ids": ["m1"]},
        "interviewer": {"question_ids": []},
        "tailor": {"tailored_ids": ["m1"]},
        "outreach": {"draft_ids": []},  # no drafts: approval and dispatch skip
        "approval": {},
        "dispatch": {},
        "tracker": {},
    }
    monkeypatch.setattr(crew, "AGENTS", {k: fake(k, v) for k, v in outputs.items()})

    async def no_skip_record(state, agent, reason):
        return None

    checked: dict[str, str] = {}

    async def record_checked(state, agent, detail):
        checked[agent] = detail

    monkeypatch.setattr(crew, "mark_skipped", no_skip_record)
    monkeypatch.setattr(crew, "mark_checked", record_checked)
    g = crew.build_graph(MemorySaver())
    state = {"run_id": "r", "user_id": "u", "done": [], "errors": []}
    t0 = time.perf_counter()
    final, _ = await asyncio.gather(g.ainvoke(state, {"configurable": {"thread_id": "t"}}), crew.run_side_lane(state))
    elapsed = time.perf_counter() - t0

    def overlap(a: str, b: str) -> bool:
        return spans[a][0] < spans[b][1] and spans[b][0] < spans[a][1]

    assert overlap("researcher", "scout") and overlap("researcher", "matcher")
    # A slow Researcher (1s here) doesn't hold the matching lane back: the Matcher starts before it finishes.
    assert spans["matcher"][0] < spans["researcher"][1]
    assert overlap("interviewer", "tailor") and overlap("tailor", "tracker")
    # Dependencies still hold: each waits for what it needs.
    assert spans["verifier"][0] >= spans["scout"][1] and spans["matcher"][0] >= spans["verifier"][1]
    assert spans["tailor"][0] >= spans["matcher"][1] and spans["outreach"][0] >= spans["tailor"][1]
    # 8 agents x 0.3s one after another would take 2.4s; in lanes it's 5 steps deep.
    assert elapsed < 1.9, elapsed
    assert "researcher" in spans and set(final["done"]) >= {"scout", "verifier", "matcher", "interviewer", "tailor", "outreach", "tracker", "approval", "dispatch"}


async def test_keep_awake_pings_its_own_public_address(monkeypatch):
    import httpx
    import respx

    from app import worker
    from app.config import settings

    monkeypatch.setattr(settings, "render_external_url", "https://jobpilot-api.example.onrender.com")
    with respx.mock(assert_all_called=True) as m:
        route = m.get("https://jobpilot-api.example.onrender.com/health").mock(return_value=httpx.Response(200, json={"status": "ok"}))
        await worker.keep_awake_ping()
        assert route.called
    with respx.mock() as m:  # a failed ping is logged, never raised
        m.get("https://jobpilot-api.example.onrender.com/health").mock(side_effect=httpx.ConnectError("down"))
        await worker.keep_awake_ping()
