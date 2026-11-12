"""Verifier on the golden set: VERIFIED precision, money-request recall (must be blocked), scam recall (blocked or
flagged), legitimate postings wrongly blocked."""

import json
from pathlib import Path

from app.agents.verifier import assess
from app.models import Job

DATA = Path(__file__).resolve().parent / "datasets" / "verifier.jsonl"


def run(verbose: bool = False) -> dict:
    rows = [json.loads(line) for line in DATA.read_text().splitlines() if line.strip()]
    out = []
    for r in rows:
        j = Job(source="eval", external_id=r["id"], company=r["company"], title=r["title"], description=r["description"], url=r["url"],
                company_domain=r["company_domain"], recruiter_email=r["recruiter_email"], link_status="ok" if r["label"] == "legit" else "unverified", apply_links=[], ghost_reasons=[])
        v = assess(j)
        out.append((r, v.status))
    legit = [s for r, s in out if r["label"] == "legit"]
    money = [s for r, s in out if r["label"] == "scam_money"]
    scams = [s for r, s in out if r["label"].startswith("scam")]
    verified = [r for r, s in out if s == "verified"]
    m = {
        "cases": len(out),
        "verified_precision": round(sum(r["label"] == "legit" for r in verified) / len(verified), 4) if verified else None,
        "money_recall": round(sum(s == "suspicious" for s in money) / len(money), 4),
        "scam_recall": round(sum(s in ("suspicious", "caution") for s in scams) / len(scams), 4),
        "legit_false_block": round(sum(s == "suspicious" for s in legit) / len(legit), 4),
        "legit_verified_rate": round(sum(s == "verified" for s in legit) / len(legit), 4),
    }
    by_lang: dict[str, list[int]] = {}
    for r, s in out:
        if r["label"].startswith("scam"):
            ok = s == "suspicious" if r["label"] == "scam_money" else s in ("suspicious", "caution")
            by_lang.setdefault(r["lang"], []).append(int(ok))
    m["scam_recall_by_language"] = {k: round(sum(v) / len(v), 3) for k, v in sorted(by_lang.items())}
    if verbose:
        for r, s in out:
            bad = (r["label"] == "scam_money" and s != "suspicious") or (r["label"] == "scam_other" and s == "verified") or (r["label"] == "legit" and s == "suspicious")
            if bad:
                print("MISS", r["id"], r["lang"], s, "|", r["description"][-140:])
    return m


if __name__ == "__main__":
    import sys

    print(json.dumps(run("-v" in sys.argv), indent=2, ensure_ascii=False))
