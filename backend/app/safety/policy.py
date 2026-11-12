"""One choke point for every tool call and outbound request: `authorize(actor, action, args, ctx)`.

Default deny: an action is allowed only when a rule below allows it; anything undeclared, or declared for other
actors, is refused. Every decision (allow or deny, with its rule id) is logged as metadata: never arguments that
could hold personal data (bodies, addresses, text)."""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.config import settings
from app.logging import log
from app.safety.registry import TOOLS, Risk


@dataclass
class Decision:
    allow: bool
    rule: str
    reason: str = ""


class PolicyDenied(PermissionError):
    def __init__(self, decision: Decision):
        super().__init__(decision.reason or f"Not allowed ({decision.rule})")
        self.decision = decision


@dataclass
class Context:
    user_id: uuid.UUID | None = None
    consents: set[str] = field(default_factory=set)
    grant_ok: bool = False  # a server-verified, payload-bound approval grant was consumed for this action


# ---------- kill switch ----------

_kill: tuple[float, bool] = (0.0, False)


async def kill_switch_on() -> bool:
    """KILL_SWITCH in the environment, or the admin toggle in the database (cached 5 s), stops every outside effect."""
    global _kill
    if settings.kill_switch:
        return True
    if _kill[0] > time.monotonic():
        return _kill[1]
    from sqlalchemy import text

    from app.db import session_scope

    try:
        async with session_scope() as s:
            v = (await s.execute(text("SELECT value FROM system_flags WHERE key = 'kill_switch'"))).scalar_one_or_none()
        on = v == "on"
    except Exception:  # noqa: BLE001 - if the flag can't be read, fail closed
        on = True
    _kill = (time.monotonic() + 5, on)
    return on


def reset_kill_cache() -> None:
    global _kill
    _kill = (0.0, False)


async def consents_for(user_id: uuid.UUID) -> set[str]:
    from app.db import session_scope
    from app.services.consent import active

    async with session_scope() as s:
        return set(await active(s, user_id))


async def whatsapp_context(number: str) -> Context:
    """Who a WhatsApp number belongs to, and their active consents (none if it isn't a student's number)."""
    from sqlalchemy import select

    from app.db import session_scope
    from app.models import Profile

    async with session_scope() as s:
        uid = (await s.execute(select(Profile.user_id).where(Profile.whatsapp_number == number).limit(1))).scalar_one_or_none()
    if uid is None:
        return Context()
    return Context(user_id=uid, consents=await consents_for(uid))


# ---------- the decision ----------


def decide(actor: str, action: str, ctx: Context | None = None, killed: bool = False) -> Decision:
    ctx = ctx or Context()
    tool = TOOLS.get(action)
    if tool is None:
        return Decision(False, "default_deny", f"{action} isn't a declared tool")
    if "*" not in tool.allowed_actors and actor not in tool.allowed_actors:
        return Decision(False, "actor_not_allowed", f"{actor} may not call {action}")
    if tool.risk == Risk.EXTERNAL_SIDE_EFFECT:
        if killed:
            return Decision(False, "kill_switch", "Sending and other outside actions are paused by the kill switch")
        if tool.requires == "approval_grant" and not ctx.grant_ok:
            return Decision(False, "approval_required", "This needs your approval of this exact item first")
        if tool.requires.startswith("consent:") and tool.requires.removeprefix("consent:") not in ctx.consents:
            return Decision(False, "consent_required", f"Needs your '{tool.requires.removeprefix('consent:')}' consent")
        return Decision(True, f"allow:{action}")
    return Decision(True, f"allow:{action}")


async def authorize(actor: str, action: str, args: dict[str, Any] | None = None, ctx: Context | None = None) -> Decision:
    """Decide, log the decision (metadata only), and raise PolicyDenied on a deny."""
    tool = TOOLS.get(action)
    killed = bool(tool and tool.risk == Risk.EXTERNAL_SIDE_EFFECT and await kill_switch_on())
    d = decide(actor, action, ctx, killed)
    log.info("policy.decision", actor=actor, action=action, allow=d.allow, rule=d.rule, user_id=str(ctx.user_id) if ctx and ctx.user_id else None)
    if not d.allow:
        raise PolicyDenied(d)
    return d
