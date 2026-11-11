"""LangGraph wiring: the crew runs as parallel lanes, each agent starting as soon as its own inputs exist.

    researcher (side lane: starts with the run, finishes on its own time; see runs.execute_run)
    START ─► scout ─► verifier ─► matcher ─┬─► interviewer ─────────────────────────────► END
                                            ├─► tracker ─────────────────────────────────► END
                                            └─► tailor ─► outreach ─► approval ─► dispatch ─► END

What can't run together, and why: the Verifier needs the Scout's new postings; the Matcher must only score postings
the Verifier cleared (scams are never scored or tailored); the Tailor needs the Matcher's shortlist, Outreach the
tailored resumes, and Dispatch the student's approvals. Everything else overlaps: the Researcher widens the search
while the whole matching lane runs (new boards it adds are fetched by the shared index within minutes). It runs
outside the graph's steps on purpose: LangGraph advances in synchronized steps, so a slow Researcher inside the
graph would hold every other lane back. The Interviewer,
the Tracker and the Tailor → Outreach lane all start the moment matching ends. The Tracker no longer waits for the
student to approve drafts, so new-match emails go out right away.

Every agent decides for itself whether it has anything to do, and records a skip (with the reason) when it doesn't,
so "Prepare application" and skill-question runs use the same graph. State is checkpointed in Postgres after every
step, so a crashed run resumes where it stopped, and the approval gate can pause a run for days.
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


RULES = {name: (should_run, reason) for name, should_run, reason in PIPELINE}


def gated(name: str, fn: Callable[[PipelineState], Awaitable[dict]]):
    """Runs the agent if it has work in this run; otherwise records why it was skipped."""

    async def node(state: PipelineState) -> dict:
        should_run, reason = RULES[name]
        if not should_run(state):
            await mark_skipped(state, name, reason)
            return {"done": [name]}
        return await fn(state)

    node.__name__ = f"run_{name}"
    return node


# The lanes: (from, to). Nodes with several incoming edges here don't exist on purpose, so no agent ever waits for
# an unrelated one.
EDGES: list[tuple[str, str]] = [
    (START, "scout"),
    ("scout", "verifier"),
    ("verifier", "matcher"),
    ("matcher", "interviewer"),
    ("matcher", "tracker"),
    ("matcher", "tailor"),
    ("tailor", "outreach"),
    ("outreach", "approval"),
    ("approval", "dispatch"),
    ("interviewer", END),
    ("tracker", END),
    ("dispatch", END),
]


SIDE_LANE = {"researcher"}  # run alongside the graph by runs.execute_run, not as graph steps


async def run_side_lane(state: PipelineState) -> None:
    """The Researcher, beside the graph. It records its own step (running, done, skipped or failed); a failure here
    never fails the run, since nothing in this run waits for it."""
    try:
        await gated("researcher", AGENTS["researcher"])(state)
    except Exception:  # agent_step already marked the step failed and logged it
        pass


def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    g = StateGraph(PipelineState)
    for name, fn in AGENTS.items():
        if name in SIDE_LANE:
            continue
        g.add_node(name, gated(name, fn))
    for a, b in EDGES:
        g.add_edge(a, b)
    return g.compile(checkpointer=checkpointer)
