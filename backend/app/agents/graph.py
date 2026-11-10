"""LangGraph wiring: a supervisor routes between the specialist agents over shared state.

    supervisor ─► researcher ─► scout ─► verifier ─► matcher ─► interviewer ─► tailor ─► … ─► tracker ─► END
    (every agent hands control back to the supervisor, which picks the next one)
                   ▲________________________________________________________________|

The supervisor is deliberately deterministic: it picks the first agent in the pipeline that has not
run and whose input exists, and skips (and records) agents with nothing to do. Routing by rules
keeps runs reproducible and cheap; the LLM effort goes into the agents themselves.

State is checkpointed in Postgres after every node, so a crashed or failed run resumes from the last
completed agent, and the approval gate can pause a run for days.
"""

from collections.abc import Awaitable, Callable

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from app.agents.approval import run_approval_gate, run_dispatch
from app.agents.common import PipelineState, mark_skipped
from app.agents.interviewer import run_interviewer
from app.agents.matcher import run_matcher
from app.agents.outreach import run_outreach
from app.agents.researcher import run_researcher
from app.agents.scout import run_scout
from app.agents.tailor import run_tailor
from app.agents.tracker import run_tracker
from app.agents.verifier import run_verifier

# agent -> (should it run given the state?, reason recorded when skipped)
PIPELINE: list[tuple[str, Callable[[PipelineState], bool], str]] = [
    ("researcher", lambda s: not (s.get("rescore_match_ids") or s.get("direct")), "Not needed for this run"),
    ("scout", lambda s: not (s.get("rescore_match_ids") or s.get("direct")), "Not needed for this run"),
    ("verifier", lambda s: bool(s.get("new_job_ids")) and not (s.get("rescore_match_ids") or s.get("direct")), "No new jobs to check"),
    ("matcher", lambda s: bool(s.get("new_job_ids") or s.get("rescore_match_ids")) and not s.get("direct"), "No new jobs to score"),
    ("interviewer", lambda s: bool(s.get("match_ids")) and not (s.get("rescore_match_ids") or s.get("direct")), "No near-miss jobs to ask about"),
    ("tailor", lambda s: bool(s.get("shortlist_ids")), "No job cleared your minimum fit score"),
    ("outreach", lambda s: bool(s.get("tailored_ids")), "Nothing tailored"),
    ("approval", lambda s: bool(s.get("draft_ids")), "No drafts to review"),
    ("dispatch", lambda s: bool(s.get("draft_ids")), "No drafts to send"),
    ("tracker", lambda s: True, ""),
]

AGENTS: dict[str, Callable[[PipelineState], Awaitable[dict]]] = {
    "researcher": run_researcher,
    "scout": run_scout,
    "verifier": run_verifier,
    "matcher": run_matcher,
    "interviewer": run_interviewer,
    "tailor": run_tailor,
    "outreach": run_outreach,
    "approval": run_approval_gate,
    "dispatch": run_dispatch,
    "tracker": run_tracker,
}


async def supervisor(state: PipelineState) -> dict:
    done = set(state.get("done", []))
    skipped: list[str] = []
    for agent, should_run, reason in PIPELINE:
        if agent in done:
            continue
        if not should_run(state):
            await mark_skipped(state, agent, reason)
            skipped.append(agent)
            continue
        return {"next": agent, "done": skipped}
    return {"next": END, "done": skipped}


def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    g = StateGraph(PipelineState)
    g.add_node("supervisor", supervisor)
    for name, fn in AGENTS.items():
        g.add_node(name, fn)
        g.add_edge(name, "supervisor")
    g.add_edge(START, "supervisor")
    g.add_conditional_edges("supervisor", lambda s: s["next"], {**{n: n for n in AGENTS}, END: END})
    return g.compile(checkpointer=checkpointer)
