"""How outbound job-source traffic grows with users: per-user fetching (before) vs shared ingestion (now).

Builds N synthetic users the way real ones look (the default company boards, plus boards the Researcher
added from the catalog, skills that point to different role families, some non-technical) and runs them
through the real target planner (app.services.ingest.wanted_targets). No network, no database.

  uv run python -m scripts.scale_check            # 10 / 100 / 1,000 / 10,000 users
  uv run python -m scripts.scale_check 50000
"""

import random
import sys

from app.agents.researcher import CATALOG
from app.config import settings
from app.schemas import Preferences
from app.services.ingest import SOURCES, wanted_targets

SKILL_POOL = [
    ["python", "machine learning", "pytorch", "sql"],
    ["python", "llm", "rag", "langchain"],
    ["pandas", "numpy", "statistics"],
    ["sql", "excel", "power bi", "tableau"],
    ["fastapi", "django", "python"],
    ["javascript", "react", "node"],
    ["java", "data structures", "c++"],
    ["excel", "communication"],
]


def synthetic_user(rng: random.Random) -> tuple[Preferences, list[str]]:
    base = Preferences()
    extra = rng.sample(CATALOG, k=rng.randint(0, 12))  # boards the Researcher found for this user
    split = len(extra) // 2
    tracks = rng.choice([["technical"], ["technical", "non_technical"], ["non_technical"]])
    prefs = base.model_copy(
        update={
            "greenhouse_boards": list(dict.fromkeys(base.greenhouse_boards + extra[:split])),
            "lever_boards": list(dict.fromkeys(base.lever_boards + extra[split:])),
            "tracks": tracks,
        }
    )
    return prefs, rng.choice(SKILL_POOL)


def per_minute(targets: list[tuple[str, str]], shared: bool) -> float:
    """Requests per minute if every target is fetched once per its source's polite gap. Quota APIs are
    capped by their monthly budget when shared; per-user fetching spends a budget per user (until it runs out)."""
    rate = 0.0
    quota_seen: set[str] = set()
    for src, _ in targets:
        s = SOURCES[src]
        gap = max(float(s.min_interval_minutes), 1.0)
        if getattr(s, "quota_limited", False):
            if shared:
                if src not in quota_seen:  # one budget for the whole service, whatever the number of searches
                    rate += 1 / gap
                    quota_seen.add(src)
            else:
                rate += 1 / gap
        else:
            rate += 1 / gap
    return rate


def main(sizes: list[int]) -> None:
    # Count quota APIs as configured in production.
    settings.jsearch_api_key = settings.jsearch_api_key or "x"
    settings.adzuna_app_id, settings.adzuna_app_key = settings.adzuna_app_id or "x", settings.adzuna_app_key or "x"
    rng = random.Random(7)
    print(f"{'users':>8} | {'per-user fetching':>18} | {'shared ingestion':>16} | {'distinct targets':>16} | saving")
    print("-" * 80)
    for n in sizes:
        users = [synthetic_user(rng) for _ in range(n)]
        all_targets = [t for prefs, skills in users for t in wanted_targets(prefs, skills)]
        distinct = sorted(set(all_targets))
        before = per_minute(all_targets, shared=False)
        after = per_minute(distinct, shared=True)
        print(f"{n:>8,} | {before:>14,.0f}/min | {after:>12,.0f}/min | {len(distinct):>16,} | {before / max(after, 1e-9):,.0f}x fewer")
    jsearch_gap = SOURCES["jsearch"].min_interval_minutes
    print(f"\nQuota APIs: per-user fetching would need {settings.jsearch_monthly_requests:,} JSearch requests a month *per user*;")
    print(f"shared ingestion spends one {settings.jsearch_monthly_requests:,}-request budget for everyone (one search every {jsearch_gap} min).")


if __name__ == "__main__":
    main([int(a) for a in sys.argv[1:]] or [10, 100, 1_000, 10_000])
