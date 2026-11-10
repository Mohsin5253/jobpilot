from types import SimpleNamespace

import groq
import httpx
import pytest
from pydantic import BaseModel
from sqlalchemy import select

from app.db import session_scope
from app.llm import LLM, CallContext, LLMOutputError, LLMUnavailable, estimate_cost, retry_after_seconds, strict_schema
from app.models import LLMCall
from app.schemas import ResumeData


class Out(BaseModel):
    score: int
    reasons: list[str] = []


# ---------- Groq (default provider) ----------


def _chat(text: str, finish: str = "stop"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason=finish)],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
    )


class FakeCalls:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def create(self, **kw):
        self.calls.append(kw)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def groq_llm(replies):
    llm = LLM()
    llm.enabled, llm.provider = True, "groq"
    fake = FakeCalls(replies)
    llm._client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
    return llm, fake


def _groq_error(cls, status: int, message: str):
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    return cls(message, response=httpx.Response(status, request=req), body=None)


def test_strict_schema_inlines_refs_and_requires_everything():
    schema = strict_schema(ResumeData)
    assert "$defs" not in str(schema) and "$ref" not in str(schema)
    exp = schema["properties"]["experience"]["items"]
    assert exp["additionalProperties"] is False
    assert set(exp["required"]) == set(exp["properties"]) and "title" in exp["properties"]  # a field named "title" survives
    assert "default" not in str(schema)


async def test_offline_mode_raises_unavailable():
    with pytest.raises(LLMUnavailable):
        await LLM().structured(agent="t", tier="fast", system="s", prompt="p", schema=Out, ctx=CallContext())


async def test_groq_valid_json_records_cost():
    llm, fake = groq_llm([_chat('{"score": 80, "reasons": ["python"]}')])
    out = await llm.structured(agent="matcher", tier="fast", system="sys", prompt="p", schema=Out, ctx=CallContext())
    assert out.score == 80
    kw = fake.calls[0]
    assert kw["model"] == "openai/gpt-oss-20b" and kw["reasoning_effort"] == "low"
    assert kw["response_format"]["json_schema"]["strict"] is True
    assert kw["messages"][0] == {"role": "system", "content": "sys"}
    async with session_scope() as s:
        call = (await s.execute(select(LLMCall))).scalar_one()
    assert call.success and float(call.cost_usd) == pytest.approx(estimate_cost("openai/gpt-oss-20b", 100, 50))


async def test_groq_smart_tier_uses_120b():
    llm, fake = groq_llm([_chat('{"score": 1}')])
    await llm.structured(agent="tailor", tier="smart", system="s", prompt="p", schema=Out, ctx=CallContext())
    assert fake.calls[0]["model"] == "openai/gpt-oss-120b" and fake.calls[0]["reasoning_effort"] == "medium"


async def test_groq_schema_400_is_repaired():
    err = _groq_error(groq.BadRequestError, 400, "Generated JSON does not match the expected schema. Please adjust your prompt.")
    llm, fake = groq_llm([err, _chat('{"score": 72}')])
    out = await llm.structured(agent="t", tier="fast", system="s", prompt="ORIGINAL", schema=Out, ctx=CallContext())
    assert out.score == 72 and len(fake.calls) == 2
    assert "did not match the required JSON schema" in fake.calls[1]["messages"][1]["content"]


async def test_groq_output_parse_failed_is_repaired():
    err = _groq_error(groq.BadRequestError, 400, "Error code: 400 - {'error': {'message': 'Parsing failed. The model generated output that could not be parsed.', 'code': 'output_parse_failed'}}")
    llm, fake = groq_llm([err, _chat('{"score": 4}')])
    assert (await llm.structured(agent="t", tier="fast", system="s", prompt="p", schema=Out, ctx=CallContext())).score == 4
    assert len(fake.calls) == 2


async def test_groq_other_400_is_not_retried():
    llm, fake = groq_llm([_groq_error(groq.BadRequestError, 400, "model_not_found")])
    with pytest.raises(LLMUnavailable):
        await llm.structured(agent="t", tier="fast", system="s", prompt="p", schema=Out, ctx=CallContext())
    assert len(fake.calls) == 1


async def test_groq_bad_json_is_repaired():
    llm, fake = groq_llm([_chat('{"score": "high"'), _chat('{"score": 5}')])
    assert (await llm.structured(agent="t", tier="fast", system="s", prompt="p", schema=Out, ctx=CallContext())).score == 5
    assert "failed validation" in fake.calls[1]["messages"][1]["content"]


async def test_groq_truncation_doubles_budget():
    llm, fake = groq_llm([_chat('{"score": 1', finish="length"), _chat('{"score": 5}')])
    await llm.structured(agent="t", tier="fast", system="s", prompt="p", schema=Out, ctx=CallContext(), max_tokens=1000)
    assert fake.calls[1]["max_completion_tokens"] == 2000


async def test_groq_gives_up_after_repairs():
    llm, _ = groq_llm([_chat("nope")] * 3)
    with pytest.raises(LLMOutputError):
        await llm.structured(agent="t", tier="fast", system="s", prompt="p", schema=Out, ctx=CallContext())


async def test_groq_rate_limit_waits_for_retry_hint(monkeypatch):
    slept: list[float] = []

    async def fake_sleep(secs):
        slept.append(secs)

    monkeypatch.setattr("app.llm.asyncio.sleep", fake_sleep)
    err = _groq_error(groq.RateLimitError, 429, "Rate limit reached on tokens per minute (TPM). Please try again in 11.295s.")
    llm, fake = groq_llm([err, _chat('{"score": 3}')])
    out = await llm.structured(agent="t", tier="smart", system="s", prompt="p", schema=Out, ctx=CallContext())
    assert out.score == 3 and len(fake.calls) == 2
    assert 11.4 < slept[0] < 13  # the hint plus a little jitter


async def test_groq_rate_limit_gives_up_after_wait_budget(monkeypatch):
    async def fake_sleep(_):
        pass

    monkeypatch.setattr("app.llm.asyncio.sleep", fake_sleep)
    err = _groq_error(groq.RateLimitError, 429, "Please try again in 1m30s.")
    llm, _ = groq_llm([err])
    with pytest.raises(LLMUnavailable):
        await llm.structured(agent="t", tier="fast", system="s", prompt="p", schema=Out, ctx=CallContext())
    async with session_scope() as s:
        call = (await s.execute(select(LLMCall))).scalar_one()
    assert not call.success and "RateLimitError" in call.error


def test_retry_after_parsing():
    assert retry_after_seconds(Exception("Please try again in 4.6725s")) == pytest.approx(4.6725)
    assert retry_after_seconds(Exception("try again in 1m2.5s")) == pytest.approx(62.5)
    assert retry_after_seconds(Exception("try again in 350ms")) == pytest.approx(0.35)


# ---------- Anthropic (optional provider) ----------


async def test_anthropic_provider_still_works():
    resp = SimpleNamespace(
        content=[SimpleNamespace(type="text", text='{"score": 9}')],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=10, output_tokens=5, cache_creation_input_tokens=0, cache_read_input_tokens=0),
    )
    llm = LLM()
    llm.enabled, llm.provider = True, "anthropic"
    fake = FakeCalls([resp])
    llm._client = SimpleNamespace(beta=SimpleNamespace(messages=fake))
    out = await llm.structured(agent="t", tier="smart", system="s", prompt="p", schema=Out, ctx=CallContext())
    assert out.score == 9
    assert fake.calls[0]["model"] == "claude-opus-5-5" and fake.calls[0]["fallbacks"] == "default"
