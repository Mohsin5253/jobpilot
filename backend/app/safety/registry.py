"""The tool registry: every action with an effect outside JobPilot is declared here with its risk tier, who may call
it and what it needs first. The policy engine (policy.py) refuses anything not declared."""

from dataclasses import dataclass
from enum import StrEnum


class Risk(StrEnum):
    READ = "READ"
    DRAFT = "DRAFT"
    EXTERNAL_SIDE_EFFECT = "EXTERNAL_SIDE_EFFECT"


@dataclass(frozen=True)
class Tool:
    name: str
    risk: Risk
    allowed_actors: frozenset[str]
    requires: str  # what must hold before it runs: "approval_grant", a consent purpose, or "" for none
    rate_limit: str = ""  # human-readable; enforced where the call is made (mailer spacing, egress buckets)
    idempotent: bool = False


def _t(name: str, risk: Risk, actors: set[str], requires: str = "", rate_limit: str = "", idempotent: bool = False) -> Tool:
    return Tool(name, risk, frozenset(actors), requires, rate_limit, idempotent)


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in (
        # Outside-world effects: always behind an approval or an active consent; no prompt, setting or agent can skip it.
        _t("email.send", Risk.EXTERNAL_SIDE_EFFECT, {"dispatch"}, "approval_grant", "plan daily cap; >= 90 s apart per mailbox"),
        _t("whatsapp.send", Risk.EXTERNAL_SIDE_EFFECT, {"digest", "whatsapp_reply"}, "consent:whatsapp", "one digest a day; template messages only"),
        _t("proof.publish", Risk.EXTERNAL_SIDE_EFFECT, {"user"}, "consent:public_proof"),
        _t("college.share", Risk.EXTERNAL_SIDE_EFFECT, {"user", "officer_view"}, "consent:college_share"),
        _t("payments.create", Risk.EXTERNAL_SIDE_EFFECT, {"user"}, "", "", True),
        # Reads.
        _t("http.fetch", Risk.READ, {"sources", "career_page", "link_check", "contacts", "evidence", "ingest", "scam_shield", "gmail", "razorpay", "whatsapp", "rdap"}),
        _t("llm.complete", Risk.READ, {"*"}),
        # Drafts: written for the student to review; nothing leaves JobPilot.
        _t("draft.create", Risk.DRAFT, {"outreach", "tracker"}),
        _t("resume.tailor", Risk.DRAFT, {"tailor"}),
    )
}
