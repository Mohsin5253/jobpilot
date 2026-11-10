"""Proof-of-skills pack: evidence a recruiter can check, attached to every application.

* GitHub (official REST API): public repos, languages, topics, stars and recent activity. Ownership is
  verified by putting a one-time code in the GitHub bio (checked once; it can be removed afterwards).
* Codeforces (official API): rating and rank. Shown as linked, since the API offers no ownership check.
* Anything else (LeetCode, Kaggle, certificates, deployed projects) is self-reported with a link, labelled
  as such; deployed links are checked for being live.

Skills the evidence demonstrates are listed as "evidenced", so the app can show which of a job's skills
the student can prove, not just claim.
"""

import secrets
from datetime import UTC, datetime, timedelta

import httpx

from app.config import settings
from app.skills import extract_skills
from app.sources.authenticity import check_link
from app.sources.base import USER_AGENT

GITHUB = "https://api.github.com"
CODEFORCES = "https://codeforces.com/api"
ITEM_KINDS = {"leetcode", "kaggle", "certificate", "project", "hackathon", "other"}


class EvidenceError(Exception):
    pass


def _gh_headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT, "X-GitHub-Api-Version": "2022-11-28"}
    if settings.github_token:
        h["Authorization"] = f"Bearer {settings.github_token}"
    return h


async def fetch_github(client: httpx.AsyncClient, username: str) -> dict:
    username = username.strip().removeprefix("https://github.com/").removeprefix("github.com/").strip("/@ ")
    if not username or "/" in username:
        raise EvidenceError("Enter your GitHub username, e.g. aarav-mehta")
    r = await client.get(f"{GITHUB}/users/{username}", headers=_gh_headers(), timeout=15)
    if r.status_code == 404:
        raise EvidenceError(f"No GitHub account called {username}")
    if r.status_code == 403:
        raise EvidenceError("GitHub is rate-limiting us right now; try again in a few minutes")
    r.raise_for_status()
    user = r.json()
    rr = await client.get(f"{GITHUB}/users/{username}/repos", params={"per_page": 100, "sort": "pushed", "type": "owner"}, headers=_gh_headers(), timeout=15)
    rr.raise_for_status()
    repos = [x for x in rr.json() if not x.get("fork") and not x.get("archived")]
    languages: dict[str, int] = {}
    for x in repos:
        if x.get("language"):
            languages[x["language"]] = languages.get(x["language"], 0) + 1
    since = datetime.now(UTC) - timedelta(days=90)
    active = sum(1 for x in repos if x.get("pushed_at") and datetime.fromisoformat(x["pushed_at"].replace("Z", "+00:00")) >= since)
    top = sorted(repos, key=lambda x: (x.get("stargazers_count", 0), x.get("pushed_at") or ""), reverse=True)[:6]
    return {
        "username": user.get("login", username),
        "url": user.get("html_url", f"https://github.com/{username}"),
        "name": user.get("name") or "",
        "bio": user.get("bio") or "",
        "public_repos": len(repos),
        "followers": user.get("followers", 0),
        "since": (user.get("created_at") or "")[:10],
        "active_repos_90d": active,
        "stars": sum(x.get("stargazers_count", 0) for x in repos),
        "languages": dict(sorted(languages.items(), key=lambda kv: -kv[1])[:8]),
        "top_repos": [
            {
                "name": x["name"],
                "url": x["html_url"],
                "description": (x.get("description") or "")[:200],
                "language": x.get("language") or "",
                "stars": x.get("stargazers_count", 0),
                "topics": (x.get("topics") or [])[:6],
                "pushed_at": (x.get("pushed_at") or "")[:10],
            }
            for x in top
        ],
        "fetched_at": datetime.now(UTC).isoformat(),
    }


async def fetch_codeforces(client: httpx.AsyncClient, handle: str) -> dict:
    handle = handle.strip().strip("@/ ")
    r = await client.get(f"{CODEFORCES}/user.info", params={"handles": handle}, headers={"User-Agent": USER_AGENT}, timeout=15)
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if data.get("status") != "OK" or not data.get("result"):
        raise EvidenceError(f"No Codeforces handle called {handle}")
    u = data["result"][0]
    return {
        "handle": u.get("handle", handle),
        "url": f"https://codeforces.com/profile/{u.get('handle', handle)}",
        "rating": u.get("rating"),
        "max_rating": u.get("maxRating"),
        "rank": u.get("rank") or "unrated",
        "max_rank": u.get("maxRank") or "",
        "fetched_at": datetime.now(UTC).isoformat(),
    }


def new_verify_code() -> str:
    return f"jobpilot-{secrets.token_hex(3)}"


def evidenced_skills(evidence: dict) -> list[str]:
    gh = evidence.get("github") or {}
    text = " ".join(
        [*gh.get("languages", {}).keys()]
        + [" ".join([r.get("language", ""), r.get("description", ""), *r.get("topics", [])]) for r in gh.get("top_repos", [])]
    )
    skills = extract_skills(text) if text.strip() else []
    if (evidence.get("codeforces") or {}).get("rating"):
        skills.append("Data Structures")
    return list(dict.fromkeys(skills))


async def check_item(client: httpx.AsyncClient, item: dict) -> dict:
    status = await check_link(client, item["url"])
    return {**item, "live": status != "dead", "checked_at": datetime.now(UTC).isoformat()}


def stale(block: dict | None) -> bool:
    at = (block or {}).get("fetched_at")
    return not at or datetime.now(UTC) - datetime.fromisoformat(at) > timedelta(hours=settings.evidence_cache_hours)


def public_view(evidence: dict, resume_name: str, headline: str) -> dict:
    """What the public proof page shows: evidence only, never contact details."""
    gh = evidence.get("github")
    return {
        "name": resume_name,
        "headline": headline,
        "github": {k: gh.get(k) for k in ("username", "url", "public_repos", "stars", "active_repos_90d", "languages", "top_repos", "since")} | {"verified": bool(gh.get("verified"))} if gh else None,
        "codeforces": evidence.get("codeforces"),
        "items": [i for i in evidence.get("items", []) if i.get("live") is not False],
        "skills": evidenced_skills(evidence),
    }
