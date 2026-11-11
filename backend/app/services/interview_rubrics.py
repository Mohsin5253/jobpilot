"""The rubric library the interviewer grades against: retrieved per question (by kind and field) and put in front of
the grader, so judgments follow published hiring rubrics instead of the model's general taste.

Sources are public descriptions of how large tech companies assess candidates: Google's four attributes (general
cognitive ability, role-related knowledge, leadership, Googleyness) and its structured-interview guidance, Amazon-style
behavioural (STAR) probing, product frameworks (CIRCLES) and standard case structures. Each rubric says what strong
and weak look like, so the grader can quote it.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Rubric:
    id: str
    title: str
    kinds: tuple[str, ...]  # question kinds it applies to ("*" = any)
    fields: tuple[str, ...] = ("*",)  # industries it applies to
    strong: str = ""
    weak: str = ""


RUBRICS: tuple[Rubric, ...] = (
    Rubric(
        "gca", "General cognitive ability (GCA)", ("case", "situational", "technical", "coding", "product", "screening"),
        strong="Breaks an ambiguous problem into parts, states assumptions, compares options with trade-offs, reaches a justified answer and adapts when a constraint changes.",
        weak="Jumps to an answer, ignores constraints, can't explain why, or stalls when the problem changes.",
    ),
    Rubric(
        "rrk", "Role-related knowledge (RRK)", ("technical", "coding", "skill", "project", "proof", "portfolio", "case"),
        strong="Uses the field's concepts correctly and precisely, with a concrete example from their own work and awareness of limits and alternatives.",
        weak="Textbook definitions without an example, misused terms, or claims they can't back up when probed.",
    ),
    Rubric(
        "leadership", "Emergent leadership & ownership", ("behavioural", "project", "proof", "situational", "screening"),
        strong="Shows stepping up without a title: owned an outcome, unblocked others, made a call under uncertainty, and stepped back when someone else was better placed.",
        weak="Describes the team's work as 'we' throughout, no personal decision, no outcome they owned.",
    ),
    Rubric(
        "googleyness", "Googleyness (collaboration, humility, ambiguity)", ("behavioural", "situational", "screening", "roleplay"),
        strong="Comfortable with ambiguity, admits mistakes and what they learned, gives others credit, challenges ideas respectfully, bias to action with care for users.",
        weak="Blames others, never wrong, avoids ambiguity, or acts without considering impact on the team or users.",
    ),
    Rubric(
        "star", "STAR structure (behavioural)", ("behavioural", "situational", "skill", "project", "proof", "screening"),
        strong="Situation in a line, the candidate's own task, specific actions in first person, a measurable result and a reflection.",
        weak="Missing the result, generic actions, hypothetical instead of a real event, or a long situation with little action.",
    ),
    Rubric(
        "circles", "CIRCLES (product sense)", ("case", "product", "portfolio"), ("product", "design", "consulting", "marketing", "*"),
        strong="Comprehends the situation, identifies the customer, reports needs, cuts through prioritisation, lists solutions, evaluates trade-offs, summarises a recommendation with a success metric.",
        weak="Jumps to features without users or needs, no prioritisation, no metric for success.",
    ),
    Rubric(
        "case", "Case structure (business problems)", ("case",), ("consulting", "finance", "marketing", "sales", "operations", "*"),
        strong="Clarifies the objective, lays out a MECE structure, quantifies with stated assumptions, prioritises the biggest driver, ends with a recommendation, risks and next steps.",
        weak="Unstructured brainstorming, maths done silently or wrong, no recommendation.",
    ),
    Rubric(
        "coding_process", "Coding interview process", ("coding",),
        strong="Asks clarifying questions (input size, edge cases, duplicates), states a brute force and its complexity, improves it, states time and space before coding, writes clean code, then tests edge cases and suggests optimisations.",
        weak="Starts coding immediately, no complexity analysis, untested code, can't find their own bug.",
    ),
    Rubric(
        "system_design", "System design trade-offs", ("technical",), ("software", "data_science", "data_analytics"),
        strong="Clarifies scale and requirements, sketches components, discusses trade-offs (latency vs consistency, SQL vs NoSQL, caching, queues) and failure modes.",
        weak="Names technologies without reasons, ignores scale or failure, one-size-fits-all design.",
    ),
    Rubric(
        "pushback", "Handling pushback (follow-ups)", ("*",),
        strong="Takes the new constraint seriously, adapts the plan with a clear reason, keeps the original goal or metric in view.",
        weak="Repeats the first answer, gets defensive, or abandons the goal entirely.",
    ),
)


def retrieve(kind: str, industry: str = "*", k: int = 3) -> list[Rubric]:
    """The rubrics that apply to this kind of question in this field, most specific first."""
    def fits(r: Rubric) -> bool:
        return (kind in r.kinds or "*" in r.kinds) and (industry in r.fields or "*" in r.fields)

    hits = [r for r in RUBRICS if fits(r)]
    hits.sort(key=lambda r: ("*" in r.kinds, len(r.kinds), "*" in r.fields))
    return hits[:k]


def as_prompt(rubrics: list[Rubric]) -> str:
    return "\n".join(f"- {r.title}. Strong: {r.strong} Weak: {r.weak}" for r in rubrics)
