"""JobPilot evals.

  uv run python -m evals.run_evals            # offline: matcher (embeddings + skills) and guard
  uv run python -m evals.run_evals --llm      # also: LLM fit reviews + live Tailor fabrication rate

1. Match quality  - fit scores vs my own 1-3 labels on 20 postings for the sample resume:
                    Spearman rho, precision@5, bucket accuracy (>=60 / 40-59 / <40).
2. Guard          - precision / recall of the no-fabrication guard on hand-written adversarial rewrites.
3. Tailor (--llm) - share of the Tailor's raw rewrites the guard had to revert (fabrication rate),
                    and whether anything slipped through after the guard (must be 0).
Writes a JSON report to evals/reports/.
"""

import argparse
import asyncio
import json
import statistics
from datetime import UTC, datetime
from pathlib import Path

from app.agents.guard import bullet_contexts, check_bullet, resume_skillset
from app.agents.matcher import blend, level_factor, resume_for_prompt, review_fit
from app.agents.tailor import tailor_one
from app.embeddings import cosine, get_embedder
from app.llm import CallContext
from app.models import Job, JobMatch
from app.resume_parser import heuristic_parse
from app.skills import extract_skills, job_embedding_text, skill_overlap

ROOT = Path(__file__).resolve().parent
DEMO = ROOT.parent / "app" / "data" / "demo_jobs.json"
SAMPLE_RESUME = ROOT / "data" / "sample_resume.md"


def spearman(xs: list[float], ys: list[float]) -> float:
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else 0.0


def load_resume(path: Path):
    text = path.read_text()
    resume = heuristic_parse(text)
    resume.skills = list(dict.fromkeys([*resume.skills, *extract_skills(text)]))
    return resume, text


async def eval_matcher(use_llm: bool) -> dict:
    spec = json.loads((ROOT / "data" / "match_labels.json").read_text())
    resume, _ = load_resume(SAMPLE_RESUME)
    jobs = {j["id"]: j for j in json.loads(DEMO.read_text())}
    embedder = get_embedder()
    rvec = await embedder.embed_one(resume.embedding_text())
    ids = list(spec["labels"])
    jvecs = await embedder.embed([job_embedding_text(jobs[i]["title"], jobs[i]["company"], jobs[i]["description"]) for i in ids])

    reviews: dict[str, float | None] = {i: None for i in ids}
    if use_llm:
        rj = resume_for_prompt(resume)
        objs = [Job(title=jobs[i]["title"], company=jobs[i]["company"], location=jobs[i]["location"], description=jobs[i]["description"]) for i in ids]
        out = await asyncio.gather(*(review_fit(o, rj, CallContext()) for o in objs))
        reviews = {i: (r.fit_score if r else None) for i, r in zip(ids, out)}

    rows = []
    for i, v in zip(ids, jvecs):
        j = jobs[i]
        semantic = embedder.to_score(cosine(rvec, v))
        _, _, skills = skill_overlap(resume.skills, extract_skills(f"{j['title']}\n{j['description']}"))
        rows.append({"id": i, "title": j["title"], "label": spec["labels"][i], "semantic": round(semantic, 1), "skills": round(skills, 1),
                     "llm": reviews[i], "score": round(blend(semantic, skills, reviews[i]) * level_factor(j["title"], j["description"]), 1)})

    rows.sort(key=lambda r: r["score"], reverse=True)
    bucket = lambda s: 3 if s >= 60 else 2 if s >= 40 else 1  # noqa: E731
    return {
        "embedding_backend": embedder.backend,
        "llm": use_llm,
        "spearman": round(spearman([r["score"] for r in rows], [r["label"] for r in rows]), 3),
        "precision_at_5": sum(r["label"] == 3 for r in rows[:5]) / 5,
        "bucket_accuracy": round(sum(bucket(r["score"]) == r["label"] for r in rows) / len(rows), 3),
        "rows": rows,
    }


def eval_guard() -> dict:
    cases = json.loads((ROOT / "data" / "guard_cases.json").read_text())
    resume, text = load_resume(SAMPLE_RESUME)
    skills = resume_skillset(resume, text)
    tp = fp = tn = fn = 0
    misses = []
    for c in cases:
        verdict = check_bullet(c["rewritten"], c["context"], skills)
        flagged = not verdict.ok
        want = c["expect"] == "violation"
        tp += flagged and want
        fp += flagged and not want
        tn += not flagged and not want
        fn += not flagged and want
        if flagged != want:
            misses.append({**c, "verdict": verdict.as_dict()})
    return {
        "cases": len(cases),
        "precision": round(tp / (tp + fp), 3) if tp + fp else 1.0,
        "recall": round(tp / (tp + fn), 3) if tp + fn else 1.0,
        "accuracy": round((tp + tn) / len(cases), 3),
        "misses": misses,
    }


async def eval_tailor(match_rows: list[dict]) -> dict:
    resume, text = load_resume(SAMPLE_RESUME)
    jobs = {j["id"]: j for j in json.loads(DEMO.read_text())}
    contexts, skills = bullet_contexts(resume), resume_skillset(resume, text)
    total = reverted = leaked = 0
    details = []
    for r in match_rows[:5]:
        j = jobs[r["id"]]
        job = Job(title=j["title"], company=j["company"], location=j["location"], description=j["description"], skills=extract_skills(j["description"]))
        match = JobMatch(strengths=[], gaps=[])
        match.job = job
        bullets, report, _ = await tailor_one(match, resume, text, CallContext())
        for b in bullets:
            total += 1
            reverted += b["reverted"]
            if not check_bullet(b["rewritten"], contexts[b["source_id"]], skills).ok:
                leaked += 1
        details.append({"job": j["title"], "report": report})
    return {
        "rewrites": total,
        "fabrication_rate_before_guard": round(reverted / total, 3) if total else 0.0,
        "violations_after_guard": leaked,
        "details": details,
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="use Claude for fit reviews and run the live Tailor eval (costs money)")
    args = ap.parse_args()

    report: dict = {"at": datetime.now(UTC).isoformat()}
    report["matcher"] = await eval_matcher(args.llm)
    report["guard"] = eval_guard()
    if args.llm:
        report["tailor"] = await eval_tailor(report["matcher"]["rows"])

    m, g = report["matcher"], report["guard"]
    print(f"\nMatcher  ({m['embedding_backend']}{' + LLM' if m['llm'] else ''})")
    print(f"  Spearman rho {m['spearman']:.3f} · precision@5 {m['precision_at_5']:.2f} · bucket accuracy {m['bucket_accuracy']:.2f}")
    for r in m["rows"]:
        print(f"  {r['score']:5.1f}  label {r['label']}  {r['title']}")
    print(f"\nGuard    precision {g['precision']:.2f} · recall {g['recall']:.2f} · accuracy {g['accuracy']:.2f} on {g['cases']} cases")
    for miss in g["misses"]:
        print(f"  MISS ({miss['expect']}): {miss['rewritten']}  -> {miss['verdict']}")
    if "tailor" in report:
        t = report["tailor"]
        print(f"\nTailor   {t['rewrites']} rewrites · fabrication rate before guard {t['fabrication_rate_before_guard']:.1%} · after guard {t['violations_after_guard']}")

    out = ROOT / "reports" / f"eval-{datetime.now(UTC):%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nReport: {out.relative_to(ROOT.parent)}")


if __name__ == "__main__":
    asyncio.run(main())
