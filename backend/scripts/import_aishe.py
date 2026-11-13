"""Builds JobPilot's campus reference data from the AISHE survey export (public data, Ministry of Education).

  uv run python -m scripts.import_aishe "/path/to/archive/All India Survey on Higher Education - 2015"

Writes app/data/campus/:
  aishe_programmes.csv    201 programmes: abbreviation, name, AISHE course level, ISCED 2011 level, ISCED-F fields
  aishe_disciplines.csv   35 discipline categories with their ISCED-F 2013 code
  aishe_colleges.csv.gz   colleges, standalone institutions and universities: AISHE id, name, kind, state, district,
                          affiliating university (for the setup wizard's search). The data is from 2015-16, so a
                          college that isn't found is added by hand and reviewed.
"""

import csv
import gzip
import re
import sys
from pathlib import Path

from app.campus.taxonomy import AISHE_CATEGORY_TO_ISCED, AISHE_LEVEL_TO_ISCED

OUT = Path(__file__).resolve().parent.parent / "app" / "data" / "campus"


def rows(folder: Path, name: str) -> list[dict]:
    path = next(folder.glob(f"*_{name}.csv"))
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        return list(csv.DictReader(f))


def main(folder: Path) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cats = rows(folder, "ref_broad_discipline_group_category")
    with open(OUT / "aishe_disciplines.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["aishe_id", "name", "isced_code"])
        for c in sorted(cats, key=lambda c: c["id"]):
            w.writerow([c["id"], c["discipline_group_category"].strip(), AISHE_CATEGORY_TO_ISCED.get(c["id"], "")])

    links: dict[str, set[str]] = {}
    for r in rows(folder, "ref_programme_broad_discipline_group_and_category"):
        code = AISHE_CATEGORY_TO_ISCED.get(r["broad_discipline_group_category_id"], "")
        if code:
            links.setdefault(r["programme_id"], set()).add(code)
    with open(OUT / "aishe_programmes.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["aishe_id", "abbreviation", "name", "aishe_level", "isced_level", "isced_fields"])
        for p in sorted(rows(folder, "ref_programme"), key=lambda p: p["id"]):
            abbr, _, full = p["programme"].partition("-")
            abbr, full = abbr.strip(), (full.strip() or abbr.strip())
            level = AISHE_LEVEL_TO_ISCED.get(p["course_level_id"])
            if p["course_level_id"] == "8":  # integrated: levelled by the highest award
                level = 8 if "Ph" in abbr else 7 if re.search(r"\bM\.|Master", p["programme"]) else 6
            w.writerow([p["id"], abbr, full, p["course_level_id"], level, " ".join(sorted(links.get(p["id"], set())))])

    states = {s["st_code"]: s["name"].strip() for s in rows(folder, "ref_state")}
    districts = {(d["st_code"], d["dist_code"]): d["name"].strip() for d in rows(folder, "ref_district")}
    unis = rows(folder, "ref_university")
    uni_name = {u["id"]: u["name"].strip() for u in unis}
    n = 0
    with gzip.open(OUT / "aishe_colleges.csv.gz", "wt", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["aishe_id", "name", "kind", "state", "district", "university"])
        for u in unis:
            w.writerow([f"U-{u['id']}", u["name"].strip(), "university", states.get(u["statecode"], ""), districts.get((u["statecode"], u["district_code"]), ""), ""])
            n += 1
        for c in rows(folder, "college"):
            w.writerow([f"C-{c['id']}", c["name"].strip(), "college", states.get(c["state_code"], ""), districts.get((c["state_code"], c["district_code"]), ""), uni_name.get(c["university_id"], "")])
            n += 1
        for s in rows(folder, "ref_standalone_institution"):
            w.writerow([f"S-{s['id']}", s["name"].strip(), "standalone", states.get(s["statecode"], ""), "", ""])
            n += 1
    print(f"{len(cats)} discipline categories, programmes written, {n} institutions -> {OUT}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
