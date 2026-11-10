"""Optional Langfuse tracing. Every helper is a no-op unless LANGFUSE_* keys are configured,
so agents can always wrap their work in spans without caring whether tracing is on."""

from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from app.config import settings
from app.logging import log


@lru_cache
def _client():
    if not settings.langfuse_enabled:
        return None
    try:
        from langfuse import Langfuse

        return Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
    except Exception as exc:
        log.warning("tracing.disabled", error=str(exc))
        return None


class _NullObservation:
    def update(self, **_: Any) -> None:
        pass


@contextmanager
def observe(name: str, as_type: str = "span", **kwargs: Any):
    client = _client()
    if client is None:
        yield _NullObservation()
        return
    with client.start_as_current_observation(name=name, as_type=as_type, **kwargs) as obs:
        yield obs


def flush() -> None:
    client = _client()
    if client is not None:
        client.flush()
