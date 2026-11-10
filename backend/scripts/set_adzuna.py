"""Save a free Adzuna developer key (https://developer.adzuna.com → Register → Dashboard → API access).

Asks for the App ID and App Key without echoing the key, runs one real search for India to prove they
work (one request of your quota), and only then writes ADZUNA_APP_ID / ADZUNA_APP_KEY to backend/.env.
"""

import getpass
import subprocess
import sys
from pathlib import Path

import httpx

ENV = Path(__file__).resolve().parents[1] / ".env"


def clipboard() -> str:
    try:
        return subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def ask_key() -> str:
    # Some terminals drop a paste into a hidden prompt, so an empty answer falls back to the clipboard.
    for _ in range(3):
        key = "".join(getpass.getpass("Adzuna App Key (hidden — paste, or just press Enter to read it from the clipboard): ").split())
        if not key:
            key = "".join(clipboard().split())
            if key:
                print("Read the key from your clipboard.")
        if key:
            print(f"Got a {len(key)}-character key.")
            return key
        print("Nothing received — copy the App Key from the Adzuna dashboard and try again.")
    return ""


def main() -> int:
    app_id = "".join(input("Adzuna App ID: ").split())
    app_key = ask_key()
    if not app_id or not app_key:
        print("App ID and App Key are both needed — nothing saved.", file=sys.stderr)
        return 1
    try:
        r = httpx.get(
            "https://api.adzuna.com/v1/api/jobs/in/search/1",
            params={"app_id": app_id, "app_key": app_key, "what": "intern", "results_per_page": 10, "content-type": "application/json"},
            timeout=30,
        )
    except httpx.HTTPError as e:
        print(f"Couldn't reach Adzuna: {e}. Nothing saved.", file=sys.stderr)
        return 1
    if r.status_code != 200:
        hint = " (check the App ID and Key on your Adzuna dashboard)" if r.status_code in (400, 401, 403) else ""
        print(f"Adzuna did not accept them ({r.status_code}){hint}: {r.text[:200]}\nNothing saved.", file=sys.stderr)
        return 1
    data = r.json()
    lines = ENV.read_text().splitlines() if ENV.exists() else []
    lines = [ln for ln in lines if not ln.startswith(("ADZUNA_APP_ID=", "ADZUNA_APP_KEY="))] + [f"ADZUNA_APP_ID={app_id}", f"ADZUNA_APP_KEY={app_key}"]
    ENV.write_text("\n".join(lines) + "\n")
    ENV.chmod(0o600)
    print(f"Adzuna works: {data.get('count', len(data.get('results', [])))} open internship listings in India. saved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
