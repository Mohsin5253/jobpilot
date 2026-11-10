"""Save a JSearch API key into backend/.env so the Scout can pull jobs listed on LinkedIn, Indeed,
Glassdoor, Naukri, Wellfound and company sites (via the Google for Jobs index).

  uv run python scripts/set_jsearch.py

Get a free key: rapidapi.com → search "JSearch" (by OpenWeb Ninja) → Subscribe to the Basic (free) plan →
copy the X-RapidAPI-Key. The key is checked with one real search (uses 1 of your free requests) and only
saved if it works.
"""

import getpass
import sys
from pathlib import Path

import httpx

ENV = Path(__file__).resolve().parents[1] / ".env"


def main() -> int:
    key = "".join(getpass.getpass("JSearch key (RapidAPI X-RapidAPI-Key): ").split())
    if not key:
        print("No key entered — nothing saved.", file=sys.stderr)
        return 1
    try:
        # During JSearch's v5 rollout one of these paths answers 404 "Endpoint does not exist" (no credit used).
        for path in ("/search", "/search-v2"):
            r = httpx.get(
                "https://jsearch.p.rapidapi.com" + path,
                params={"query": "internship jobs in India", "num_pages": "1", "country": "in", "date_posted": "week"},
                headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"},
                timeout=40,
            )
            if not (r.status_code == 404 and "does not exist" in r.text):
                break
    except httpx.HTTPError as e:
        print(f"Couldn't reach JSearch: {e}. Nothing saved.", file=sys.stderr)
        return 1
    if r.status_code != 200:
        hint = " (subscribe to JSearch's Basic plan on RapidAPI first)" if r.status_code in (401, 403) else ""
        print(f"JSearch did not accept the key ({r.status_code}){hint}: {r.text[:200]}\nNothing saved.", file=sys.stderr)
        return 1
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.sources.providers import jsearch_jobs

    jobs = jsearch_jobs(r.json())
    if not jobs:
        print(f"JSearch answered but returned no jobs; response starts: {r.text[:300]}\nNothing saved.", file=sys.stderr)
        return 1
    publishers = sorted({j.get("job_publisher") for j in jobs if j.get("job_publisher")})
    remaining = r.headers.get("x-ratelimit-requests-remaining")
    lines = ENV.read_text().splitlines() if ENV.exists() else []
    lines = [ln for ln in lines if not ln.startswith(("JSEARCH_API_KEY=", "JSEARCH_PROVIDER="))] + [f"JSEARCH_API_KEY={key}", "JSEARCH_PROVIDER=rapidapi"]
    ENV.write_text("\n".join(lines) + "\n")
    ENV.chmod(0o600)
    print(f"JSearch works: {len(jobs)} live jobs from {', '.join(publishers[:6]) or 'various boards'}"
          + (f" · {remaining} requests left this month" if remaining else "") + ". saved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
