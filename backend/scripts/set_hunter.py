"""Save a Hunter.io API key into backend/.env so the Contact Finder can find senior people at a company.

  uv run python scripts/set_hunter.py

The key is read without echo, checked against Hunter's account endpoint (no search credit is used),
and only saved if Hunter accepts it. Free plan: 25 searches + 50 verifications a month.
"""

import getpass
import sys
from pathlib import Path

import httpx

ENV = Path(__file__).resolve().parents[1] / ".env"


def main() -> int:
    key = "".join(getpass.getpass("Hunter.io API key (hunter.io → API → copy key): ").split())
    if not key:
        print("No key entered — nothing saved.", file=sys.stderr)
        return 1
    try:
        r = httpx.get("https://api.hunter.io/v2/account", params={"api_key": key}, timeout=15)
    except httpx.HTTPError as e:
        print(f"Couldn't reach Hunter: {e}. Nothing saved.", file=sys.stderr)
        return 1
    if r.status_code != 200:
        print(f"Hunter did not accept the key ({r.status_code}): {r.text[:200]}\nNothing saved.", file=sys.stderr)
        return 1
    data = r.json().get("data", {})
    searches = (data.get("requests") or {}).get("searches", {})
    lines = ENV.read_text().splitlines() if ENV.exists() else []
    lines = [ln for ln in lines if not ln.startswith("HUNTER_API_KEY=")] + [f"HUNTER_API_KEY={key}"]
    ENV.write_text("\n".join(lines) + "\n")
    ENV.chmod(0o600)
    print(f"Hunter accepted the key ({data.get('plan_name', 'plan')}: {searches.get('used', '?')}/{searches.get('available', '?')} searches used). saved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
