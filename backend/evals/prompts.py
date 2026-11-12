"""Prompt versions: every system prompt in the app, by a hash of its text.

  uv run python -m evals.prompts            # print the current versions
  uv run python -m evals.prompts --update   # accept a prompt change (run `make eval` first; CI runs it too)

tests/test_v11_accuracy.py fails when a prompt changes without updating evals/data/prompt_versions.json, so a prompt
edit can't land without a deliberate update that the eval gate then checks. Each AI call also records the hash of the
system prompt it used (llm_calls.prompt_version), never the text.
"""

import hashlib
import importlib
import json
import pkgutil
import sys
from pathlib import Path

SNAPSHOT = Path(__file__).resolve().parent / "data" / "prompt_versions.json"


def collect() -> dict[str, str]:
    import app

    out: dict[str, str] = {}
    for mod in pkgutil.walk_packages(app.__path__, "app."):
        if mod.name.startswith(("app.api.routes.__", "app.data")):
            continue
        try:
            m = importlib.import_module(mod.name)
        except Exception:  # noqa: BLE001 - optional modules
            continue
        for name, value in vars(m).items():
            if isinstance(value, str) and len(value) > 120 and any(k in name.upper() for k in ("SYSTEM", "PROMPT", "RUBRIC")) and getattr(m, "__name__", "") == mod.name:
                out[f"{mod.name}.{name}"] = hashlib.sha256(value.encode()).hexdigest()[:12]
    return dict(sorted(out.items()))


if __name__ == "__main__":
    current = collect()
    if "--update" in sys.argv:
        SNAPSHOT.write_text(json.dumps(current, indent=2) + "\n")
        print(f"Updated {SNAPSHOT.name}: {len(current)} prompts")
    else:
        print(json.dumps(current, indent=2))
