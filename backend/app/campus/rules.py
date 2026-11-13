"""Drive eligibility as data: a list of rules from the rule builder, evaluated in code with every rule id logged.

Rule shapes (each has an id and a type):
  {"id": "r1", "type": "field_in", "values": ["0613", "061"]}            ISCED-F codes (a narrow code covers its detailed ones)
  {"id": "r2", "type": "degree_in", "values": ["<degree uuid>", ...]}
  {"id": "r3", "type": "level_in", "values": [6, 7]}                       ISCED 2011 levels
  {"id": "r4", "type": "department_in" | "program_in", "values": [...]}
  {"id": "r5", "type": "term_in", "values": [7, 8]}                        year / semester / trimester, as the college counts
  {"id": "r6", "type": "score_gte", "value": 7.0}                          in the campus's own scale; never converted
  {"id": "r7", "type": "pending_subjects_lte", "value": 0}                 backlog / ATKT / KT / arrears / resit...
  {"id": "r8", "type": "graduation_year_in", "values": [2026]}
  {"id": "r9", "type": "custom_yes", "key": "nursing_registration"}       a campus-defined yes/no field
  {"id": "r10", "type": "custom_gte", "key": "typing_wpm", "value": 40}
  {"id": "r11", "type": "category_in" | "gender_in", "values": [...]}       only when the campus explicitly allows it
Unknown values (a record without a score) fail the rule and say so: nobody is silently included.
"""

from dataclasses import dataclass, field

RULE_TYPES = {"field_in", "degree_in", "level_in", "department_in", "program_in", "term_in", "score_gte", "pending_subjects_lte",
              "graduation_year_in", "custom_yes", "custom_gte", "category_in", "gender_in"}
SENSITIVE = {"category_in", "gender_in"}


class RuleError(ValueError):
    pass


@dataclass
class Record:
    """What a rule can look at, for one student: the college's record plus the program's degree and field."""

    department_id: str | None = None
    program_id: str | None = None
    degree_id: str | None = None
    field_code: str | None = None
    isced_level: int | None = None
    term: int | None = None
    score: float | None = None
    pending_subjects: int | None = None
    graduation_year: int | None = None
    custom: dict = field(default_factory=dict)


def validate(rules: list[dict], allow_sensitive: bool = False) -> list[dict]:
    seen = set()
    out = []
    for i, r in enumerate(rules or []):
        t = r.get("type")
        if t not in RULE_TYPES:
            raise RuleError(f"Unknown rule type: {t}")
        if t in SENSITIVE and not allow_sensitive:
            raise RuleError("Category or gender rules need to be enabled by your college first, where the law allows them")
        rid = str(r.get("id") or f"r{i + 1}")
        if rid in seen:
            raise RuleError(f"Duplicate rule id {rid}")
        seen.add(rid)
        if t.endswith("_in") and not r.get("values"):
            raise RuleError(f"Rule {rid} needs at least one value")
        if t in ("score_gte", "pending_subjects_lte", "custom_gte") and r.get("value") is None:
            raise RuleError(f"Rule {rid} needs a value")
        out.append({**r, "id": rid})
    return out


def _field_match(code: str | None, wanted: list[str]) -> bool:
    return bool(code) and any(code == w or code.startswith(w) for w in wanted)


def evaluate(rules: list[dict], rec: Record) -> tuple[bool, list[str]]:
    """(eligible, ids of the rules that failed)."""
    failed: list[str] = []
    for r in rules:
        t, rid = r["type"], r["id"]
        vals = r.get("values") or []
        ok: bool
        if t == "field_in":
            ok = _field_match(rec.field_code, [str(v) for v in vals])
        elif t == "degree_in":
            ok = rec.degree_id is not None and str(rec.degree_id) in {str(v) for v in vals}
        elif t == "level_in":
            ok = rec.isced_level is not None and rec.isced_level in {int(v) for v in vals}
        elif t == "department_in":
            ok = rec.department_id is not None and str(rec.department_id) in {str(v) for v in vals}
        elif t == "program_in":
            ok = rec.program_id is not None and str(rec.program_id) in {str(v) for v in vals}
        elif t == "term_in":
            ok = rec.term is not None and rec.term in {int(v) for v in vals}
        elif t == "score_gte":
            ok = rec.score is not None and float(rec.score) >= float(r["value"])
        elif t == "pending_subjects_lte":
            ok = rec.pending_subjects is not None and rec.pending_subjects <= int(r["value"])
        elif t == "graduation_year_in":
            ok = rec.graduation_year is not None and rec.graduation_year in {int(v) for v in vals}
        elif t == "custom_yes":
            ok = rec.custom.get(r.get("key")) in (True, "yes", "Yes", 1, "1")
        elif t == "custom_gte":
            v = rec.custom.get(r.get("key"))
            ok = v is not None and float(v) >= float(r["value"])
        elif t in SENSITIVE:
            ok = str(rec.custom.get(t.removesuffix("_in"), "")) in {str(v) for v in vals}
        else:  # validate() prevents this
            ok = False
        if not ok:
            failed.append(rid)
    return not failed, failed


def legacy_rules(eligibility: dict, departments_by_name: dict[str, str]) -> list[dict]:
    """v1 drives stored {min_cgpa, branches, max_backlogs, grad_years}; as rules in the campus's own scale."""
    out: list[dict] = []
    if eligibility.get("min_cgpa") is not None:
        out.append({"id": "legacy_score", "type": "score_gte", "value": float(eligibility["min_cgpa"])})
    if eligibility.get("branches"):
        ids = [departments_by_name[b.lower()] for b in eligibility["branches"] if b.lower() in departments_by_name]
        if ids:
            out.append({"id": "legacy_departments", "type": "department_in", "values": ids})
    if eligibility.get("max_backlogs") is not None:
        out.append({"id": "legacy_pending", "type": "pending_subjects_lte", "value": int(eligibility["max_backlogs"])})
    if eligibility.get("grad_years"):
        out.append({"id": "legacy_year", "type": "graduation_year_in", "values": [int(y) for y in eligibility["grad_years"]]})
    return out
