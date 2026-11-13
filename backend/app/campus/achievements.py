"""Student entries: exactly three kinds (internship, role / position of responsibility, award / event win), for every
field of study. Students write only these fields (an allowlist per kind: anything else, like cgpa, is a 400), plain text
only, dates checked, duplicates refused. Offer letters go through the same rules as Scam Shield."""

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.safety.untrusted import clean as clean_text

# Sub-types and categories are suggestions per field; any non-empty value up to 40 characters is accepted.
INTERNSHIP_TYPES = ["internship", "apprenticeship", "articleship", "clinical_posting", "rotation", "house_job", "residency", "moot_or_law_firm",
                    "teaching_practice", "field_work", "practicum", "industrial_training", "research_internship"]
INTERNSHIP_DEFAULTS_BY_FIELD = {  # ISCED broad / narrow code -> suggested sub-types, most common first
    "09": ["clinical_posting", "rotation", "house_job", "residency", "internship"], "042": ["moot_or_law_firm", "internship"],
    "0411": ["articleship", "internship"], "01": ["teaching_practice", "practicum", "internship"], "092": ["field_work", "practicum"],
    "07": ["industrial_training", "internship", "apprenticeship"], "05": ["research_internship", "internship"],
}
AWARD_CATEGORIES = ["hackathon", "moot_court", "case_competition", "sports", "cultural", "debate", "olympiad", "paper_or_poster", "art_exhibition",
                    "music_or_dance", "quiz", "scholarship", "fellowship", "other"]
LEVELS = ["college", "inter_college", "state", "national", "international"]
POSITIONS = ["winner", "runner_up", "finalist", "participant"]
CYBERCRIME_NOTE = "If anyone asked you to pay for this internship, don't pay. Report it at cybercrime.gov.in or call 1930."


def _plain(v: str | None, limit: int) -> str:
    v = clean_text(v or "", html=True)
    v = re.sub(r"[<>]", "", v)
    return v[:limit].strip()


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")  # anything outside the allowlist (cgpa, branch, status...) is rejected

    description: str = Field(default="", max_length=2000)
    start_date: date | None = None
    end_date: date | None = None
    ongoing: bool = False
    link: str | None = Field(default=None, max_length=500)
    show_on_proof_page: bool = False

    @field_validator("description")
    @classmethod
    def _desc(cls, v: str) -> str:
        return _plain(v, 2000)

    @field_validator("link")
    @classmethod
    def _link(cls, v: str | None) -> str | None:
        if v and not re.match(r"^https://[\w.-]+\.[a-z]{2,}(/\S*)?$", v.strip(), re.I):
            raise ValueError("Use a full https:// link")
        return v.strip() if v else None

    @model_validator(mode="after")
    def _dates(self):
        today = date.today()
        if self.start_date and self.start_date > today:
            raise ValueError("The start date can't be in the future")
        if self.end_date and self.end_date > today and not self.ongoing:
            raise ValueError("The end date can't be in the future: mark it ongoing instead")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("The end date is before the start date")
        if self.ongoing:
            self.end_date = None
        return self


class InternshipIn(_Base):
    kind: Literal["internship"]
    organisation: str = Field(min_length=2, max_length=200)  # company / hospital / firm
    title: str = Field(min_length=2, max_length=200)  # role / title
    sub_type: str = Field(default="internship", max_length=40)
    mode: Literal["onsite", "remote", "hybrid"]
    start_date: date
    stipend_inr: int | None = Field(default=None, ge=0, le=10_000_000)
    stipend_private: bool = True

    @field_validator("organisation", "title", "sub_type")
    @classmethod
    def _p(cls, v: str) -> str:
        return _plain(v, 200)


class RoleIn(_Base):
    kind: Literal["role"]
    organisation: str = Field(min_length=2, max_length=200)  # club, committee, council, NSS / NCC, team...
    title: str = Field(min_length=2, max_length=200)  # position
    start_date: date

    @field_validator("organisation", "title")
    @classmethod
    def _p(cls, v: str) -> str:
        return _plain(v, 200)


class AwardIn(_Base):
    kind: Literal["award"]
    title: str = Field(min_length=2, max_length=200)  # event name
    organisation: str = Field(default="", max_length=200)  # organiser
    category: str = Field(default="other", max_length=40)
    level: Literal["college", "inter_college", "state", "national", "international"]
    position: Literal["winner", "runner_up", "finalist", "participant"]
    start_date: date  # the date of the event

    @field_validator("organisation", "title", "category")
    @classmethod
    def _p(cls, v: str) -> str:
        return _plain(v, 200)


def parse(body: dict):
    """The right schema for the kind; any other kind (or none) is a 400."""
    kind = body.get("kind")
    schema = {"internship": InternshipIn, "role": RoleIn, "award": AwardIn}.get(kind)
    if schema is None:
        raise ValueError("Students can add only internships, roles or awards")
    return schema.model_validate(body)


def dedupe_key(entry) -> str:
    norm = re.sub(r"[^a-z0-9]+", " ", f"{entry.title} {getattr(entry, 'organisation', '')}".lower()).strip()
    pos = getattr(entry, "position", "") or ""
    return f"{entry.kind}|{norm}|{entry.start_date}|{pos}"[:300]


def offer_letter_flags(text: str) -> list[str]:
    """The Verifier / Scam Shield rules on an offer letter: money requests, personal email, lookalike domains."""
    from app.services.scam_shield import analyze

    if not text.strip():
        return []
    res = analyze(text)
    flags = [c.label for c in res.checks if c.status == "fail"]
    flags += [c.label for c in res.checks if c.status == "warn" and c.id in ("free_mail", "lookalike", "chat_only")]
    return list(dict.fromkeys(flags))[:6]
