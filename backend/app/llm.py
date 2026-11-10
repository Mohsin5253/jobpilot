"""LLM access for every agent: structured output, JSON repair, cost + latency accounting.

Two tiers, per the design: a cheap fast model for scoring/parsing and a stronger model for writing.
Provider is chosen by LLM_PROVIDER: Groq (default; gpt-oss-20b / gpt-oss-120b) or Anthropic (Claude).
Failure policy:
  * 5xx / network errors are retried by the SDK, then surface as LLMUnavailable so the calling agent
    can fall back to its deterministic path;
  * 429s are waited out using the provider's retry hint, up to settings.llm_rate_limit_wait_s per call;
  * a response that is cut off or does not validate against the schema is re-asked with the
    validation error attached (up to settings.llm_max_repairs times), then raises LLMOutputError.
"""

import asyncio
import copy
import json
import random
import re
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy import update

from app.config import MODEL_PRICING, PROVIDER_MODELS, settings
from app.db import session_scope
from app.logging import log
from app.models import AgentRun, LLMCall
from app.tracing import observe

T = TypeVar("T", bound=BaseModel)
Tier = Literal["fast", "smart"]

FALLBACK_BETA = "server-side-fallback-2026-07-01"
_GROQ_GENERATION_ERRORS = ("json_validate_failed", "output_parse_failed", "does not match the expected schema", "parsing failed")


class LLMUnavailable(Exception):
    """No model available (offline mode or the API failed after retries)."""


class LLMOutputError(Exception):
    """The model answered but never produced output matching the schema (or refused)."""


class _Repairable(Exception):
    """Provider rejected or truncated the output in a way a re-ask can fix."""


class _RateLimited(Exception):
    def __init__(self, wait_s: float, message: str) -> None:
        super().__init__(message)
        self.wait_s = wait_s


_TRY_AGAIN = re.compile(r"try again in (?:(\d+)m)?([\d.]+)(ms|s)", re.IGNORECASE)


def retry_after_seconds(exc: Exception) -> float:
    """How long a 429 asks us to wait: retry-after header, else Groq's "try again in 1m2.5s" text."""
    response = getattr(exc, "response", None)
    header = response.headers.get("retry-after") if response is not None else None
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    if m := _TRY_AGAIN.search(str(exc)):
        minutes, value, unit = m.groups()
        secs = float(value) / (1000 if unit == "ms" else 1)
        return secs + 60 * int(minutes or 0)
    return 5.0


@dataclass(frozen=True)
class CallContext:
    user_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None


@dataclass
class _Reply:
    text: str
    stop: Literal["ok", "truncated", "refused"]
    input_tokens: int
    output_tokens: int
    cache_read: int = 0


def estimate_cost(model: str, input_tokens: int, output_tokens: int, cache_read: int = 0) -> float:
    price_in, price_out = MODEL_PRICING.get(model, (1.0, 4.0))
    return (input_tokens * price_in + cache_read * price_in * 0.1 + output_tokens * price_out) / 1_000_000


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON schema in the shape strict structured outputs want: $refs inlined, every property
    required, no extra properties, no defaults/titles."""
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(x) for x in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            return walk(copy.deepcopy(defs[node["$ref"].rsplit("/", 1)[-1]]))
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key in ("default", "title"):
                continue
            # "properties" maps field names to schemas: keep the names (a field may be called "title").
            out[key] = {name: walk(sub) for name, sub in value.items()} if key == "properties" else walk(value)
        if out.get("type") == "object" and "properties" in out:
            out["required"] = list(out["properties"])
            out["additionalProperties"] = False
        return out

    return walk(raw)


class LLM:
    def __init__(self) -> None:
        self.enabled = settings.llm_enabled
        self.provider = settings.llm_provider
        self._client: Any = None
        if self.enabled and self.provider == "groq":
            import groq

            self._client = groq.AsyncGroq(api_key=settings.groq_api_key, max_retries=3, timeout=120.0)
        elif self.enabled:
            import anthropic

            self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=3, timeout=180.0)
        self._sem = asyncio.Semaphore(settings.llm_concurrency)

    def model_for(self, tier: Tier) -> str:
        fast, smart = PROVIDER_MODELS[self.provider]
        return (settings.fast_model or fast) if tier == "fast" else (settings.smart_model or smart)

    # ---- providers -------------------------------------------------------------------------

    async def _groq(self, model: str, tier: Tier, system: str, prompt: str, schema: type[BaseModel], budget: int) -> _Reply:
        import groq

        try:
            resp = await self._client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": schema.__name__, "strict": True, "schema": strict_schema(schema)},
                },
                reasoning_effort="low" if tier == "fast" else "medium",
                include_reasoning=False,
                max_completion_tokens=budget,
            )
        except groq.BadRequestError as exc:
            # Groq checks structured output server-side and answers 400 when a generation went wrong
            # (json_validate_failed / output_parse_failed). A re-ask fixes those; other 400s are real errors.
            if any(marker in str(exc).lower() for marker in _GROQ_GENERATION_ERRORS):
                raise _Repairable(str(exc)[:500]) from exc
            raise LLMUnavailable(str(exc)) from exc
        except groq.RateLimitError as exc:
            raise _RateLimited(retry_after_seconds(exc), f"RateLimitError: {exc}") from exc
        except (groq.APIStatusError, groq.APIConnectionError) as exc:
            raise LLMUnavailable(f"{type(exc).__name__}: {exc}") from exc
        choice = resp.choices[0]
        usage = resp.usage
        return _Reply(
            text=choice.message.content or "",
            stop="truncated" if choice.finish_reason == "length" else "ok",
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )

    async def _anthropic(self, model: str, tier: Tier, system: str, prompt: str, schema: type[BaseModel], budget: int) -> _Reply:
        import anthropic
        from anthropic import transform_schema

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": budget,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": prompt}],
            "thinking": {"type": "adaptive"},
            "output_config": {
                "effort": "low" if tier == "fast" else "medium",
                "format": {"type": "json_schema", "schema": transform_schema(schema)},
            },
        }
        if tier == "smart" and settings.smart_fallbacks:
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        try:
            resp = await self._client.beta.messages.create(**kwargs)
        except anthropic.RateLimitError as exc:
            raise _RateLimited(retry_after_seconds(exc), f"RateLimitError: {exc}") from exc
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            raise LLMUnavailable(f"{type(exc).__name__}: {exc}") from exc
        u = resp.usage
        text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
        stop = {"refusal": "refused", "max_tokens": "truncated"}.get(resp.stop_reason, "ok")
        return _Reply(
            text=text,
            stop=stop,  # type: ignore[arg-type]
            input_tokens=(u.input_tokens or 0) + (u.cache_creation_input_tokens or 0),
            output_tokens=u.output_tokens or 0,
            cache_read=u.cache_read_input_tokens or 0,
        )

    # ---- public ------------------------------------------------------------------------------

    async def structured(
        self,
        *,
        agent: str,
        tier: Tier,
        system: str,
        prompt: str,
        schema: type[T],
        ctx: CallContext,
        max_tokens: int = 8000,
    ) -> T:
        if not self.enabled or self._client is None:
            raise LLMUnavailable("LLM disabled (offline mode)")
        if ctx.user_id is not None:
            from app.services.usage import over_ai_budget

            # Past the plan's daily AI budget every agent falls back to its offline version: slower to
            # impress, but never broken, and one account can't run up the bill.
            if await over_ai_budget(ctx.user_id):
                raise LLMUnavailable("Daily AI budget for your plan reached")

        model = self.model_for(tier)
        call = self._groq if self.provider == "groq" else self._anthropic
        usage = {"in": 0, "out": 0, "cache": 0}
        started = time.perf_counter()
        current_prompt, budget, last_error = prompt, max_tokens, ""
        waited = 0.0

        async def send() -> _Reply:
            # Rate limits are waited out (outside the concurrency slot) rather than counted as
            # failures, up to llm_rate_limit_wait_s per call; beyond that the agent falls back.
            nonlocal waited
            while True:
                try:
                    async with self._sem:
                        return await call(model, tier, system, current_prompt, schema, budget)
                except _RateLimited as rl:
                    pause = rl.wait_s + random.uniform(0.2, 1.5)
                    if waited + pause > settings.llm_rate_limit_wait_s:
                        raise LLMUnavailable(str(rl)) from rl
                    log.info("llm.rate_limited", agent=agent, model=model, wait_s=round(pause, 1))
                    await asyncio.sleep(pause)
                    waited += pause

        # Traces carry timings, tokens and cost only: never the prompt (resumes, pasted messages) or the reply.
        with observe(f"llm.{agent}", as_type="generation", model=model) as gen:
            for attempt in range(1, settings.llm_max_repairs + 2):
                try:
                    reply = await send()
                except _Repairable as exc:
                    last_error = str(exc)
                    current_prompt = f"{prompt}\n\n---\nYour previous answer did not match the required JSON schema ({last_error[:300]}). Answer again with JSON that matches it exactly."
                    continue
                except LLMUnavailable as exc:
                    await self._record(ctx, agent, model, usage, started, attempt, False, str(exc)[:1000])
                    log.warning("llm.unavailable", agent=agent, model=model, error=str(exc)[:300])
                    raise

                usage["in"] += reply.input_tokens
                usage["out"] += reply.output_tokens
                usage["cache"] += reply.cache_read

                if reply.stop == "refused":
                    last_error = "model refused"
                    break
                if reply.stop == "truncated":
                    last_error = "response truncated at max_tokens"
                    budget = min(budget * 2, 32000)
                    continue

                try:
                    parsed = schema.model_validate_json(reply.text)
                except (ValidationError, json.JSONDecodeError, ValueError) as exc:
                    last_error = str(exc)[:800]
                    log.info("llm.repair", agent=agent, attempt=attempt, error=last_error[:200])
                    current_prompt = (
                        f"{prompt}\n\n---\nYour previous answer failed validation:\n{last_error}\n"
                        f"Previous answer:\n{reply.text[:3000]}\n\nReturn only a corrected JSON object that matches the schema."
                    )
                    continue

                await self._record(ctx, agent, model, usage, started, attempt, True, None)
                gen.update(
                    usage_details={"input": usage["in"], "output": usage["out"]},
                    cost_details={"total": estimate_cost(model, usage["in"], usage["out"], usage["cache"])},
                )
                return parsed

            await self._record(ctx, agent, model, usage, started, attempt, False, last_error)
            gen.update(level="ERROR", status_message=last_error)
            raise LLMOutputError(last_error)

    async def _record(
        self,
        ctx: CallContext,
        agent: str,
        model: str,
        usage: dict[str, int],
        started: float,
        attempts: int,
        success: bool,
        error: str | None,
    ) -> None:
        cost = estimate_cost(model, usage["in"], usage["out"], usage["cache"])
        latency = int((time.perf_counter() - started) * 1000)
        try:
            async with session_scope() as s:
                s.add(
                    LLMCall(
                        run_id=ctx.run_id,
                        user_id=ctx.user_id,
                        agent=agent,
                        model=model,
                        input_tokens=usage["in"],
                        output_tokens=usage["out"],
                        cache_read_tokens=usage["cache"],
                        cost_usd=cost,
                        latency_ms=latency,
                        attempts=attempts,
                        success=success,
                        error=error,
                    )
                )
                if ctx.run_id:
                    await s.execute(
                        update(AgentRun)
                        .where(AgentRun.id == ctx.run_id)
                        .values(
                            cost_usd=AgentRun.cost_usd + cost,
                            input_tokens=AgentRun.input_tokens + usage["in"],
                            output_tokens=AgentRun.output_tokens + usage["out"],
                            llm_calls=AgentRun.llm_calls + 1,
                        )
                    )
        except Exception as exc:  # accounting must never break the pipeline
            log.error("llm.record_failed", error=str(exc))


@lru_cache
def get_llm() -> LLM:
    return LLM()
