import html
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

import httpx
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from app.config import settings
from app.schemas import Preferences

USER_AGENT = "JobPilot/1.0 (+https://github.com/jobpilot; personal internship tracker)"


@dataclass
class Posting:
    source: str
    external_id: str
    company: str
    title: str
    location: str = ""
    remote: bool = False
    url: str = ""
    description: str = ""
    salary_min: float | None = None
    salary_max: float | None = None
    recruiter_email: str | None = None
    posted_at: datetime | None = None
    publisher: str | None = None  # LinkedIn, Indeed, Naukri, Glassdoor, Wellfound, company site...
    apply_links: list[dict] = field(default_factory=list)  # [{publisher, url, direct}]
    company_domain: str | None = None
    extra: dict = field(default_factory=dict)


class JobSource(Protocol):
    name: str

    def enabled(self, prefs: Preferences) -> bool: ...

    async def fetch(self, client: httpx.AsyncClient, prefs: Preferences) -> list[Posting]: ...


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (408, 425, 429) or exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


_CACHE: dict[str, tuple[float, object]] = {}


async def get_json(client: httpx.AsyncClient, url: str, params: dict | None = None):
    """GET with exponential backoff on network errors, 429 and 5xx (3 attempts). Answers are shared for
    `source_cache_s`, so checking boards every couple of minutes for many users stays one request per board."""
    key = f"{url}?{sorted((params or {}).items()) if isinstance(params, dict) else params}"
    hit = _CACHE.get(key)
    if hit and time.monotonic() - hit[0] < settings.source_cache_s:
        return hit[1]
    data = await _get_json(client, url, params)
    if settings.source_cache_s > 0:
        if len(_CACHE) > 500:
            _CACHE.clear()
        _CACHE[key] = (time.monotonic(), data)
    return data


async def _get_json(client: httpx.AsyncClient, url: str, params: dict | None = None):
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=0.5, max=8),
        retry=retry_if_exception(_retryable),
        reraise=True,
    ):
        with attempt:
            resp = await client.get(url, params=params, timeout=settings.source_timeout_s)
            resp.raise_for_status()
            return resp.json()


_TAG = re.compile(r"<[^>]+>")
_BLOCK = re.compile(r"</?(p|div|br|li|ul|ol|h[1-6])[^>]*>", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", re.IGNORECASE)


def html_to_text(raw: str) -> str:
    text = html.unescape(raw or "")
    text = _BLOCK.sub("\n", text)
    text = html.unescape(_TAG.sub("", text))
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def find_recruiter_email(text: str) -> str | None:
    for m in _EMAIL.finditer(text or ""):
        email = m.group(0)
        local = email.lower().split("@", 1)[0]
        if "example.com" not in email.lower() and not re.search(
            r"no-?reply|privacy|accessib|accommodat|disabilit|eeo|fraud|scam|benefits|payroll|security|legal", local
        ):
            return email
    return None


_EARLY = re.compile(
    r"\b(intern|interns|internship|trainee|co-?op|apprentice(ship)?|graduate|new[- ]grad|campus|fresher|"
    r"entry[- ]level|junior|jr\.?|summer analyst|student|associate trainee)\b",
    re.IGNORECASE,
)
_SENIOR = re.compile(r"\b(senior|sr\.?|staff|principal|lead|manager|director|head|vp|chief|architect)\b", re.IGNORECASE)

_TECH = re.compile(
    r"\b(engineer(ing)?|developer|software|sde|swe|programmer|data|machine learning|ml|ai|artificial intelligence|"
    r"scientist|research(er)?|devops|sre|security|cyber|cloud|backend|back-end|frontend|front-end|full[- ]?stack|"
    r"mobile|android|ios|qa|test(ing)?|automation|analytics|bi|it|infrastructure|platform|embedded|firmware|"
    r"hardware|network|database|quant(itative)?|computer|technical|technology|tech)\b",
    re.IGNORECASE,
)

INDIA_PLACES = re.compile(
    r"india|bengaluru|bangalore|mumbai|pune|hyderabad|gurgaon|gurugram|delhi|noida|chennai|kolkata|ahmedabad|"
    r"jaipur|kochi|chandigarh|indore|coimbatore|thiruvananthapuram|trivandrum|nagpur|lucknow|bhubaneswar|mohali",
    re.IGNORECASE,
)
_WORLDWIDE = re.compile(r"worldwide|anywhere|global|apac|asia", re.IGNORECASE)
# Remote roles restricted to another region ("Remote - US", "Seattle, WA", "EMEA") aren't open to someone in India.
_ELSEWHERE = re.compile(
    r"\b(us|usa|u\.s\.?|united states|canada|uk|united kingdom|england|ireland|europe|eu|emea|latam|americas|"
    r"north america|south america|germany|france|spain|italy|portugal|netherlands|belgium|switzerland|austria|"
    r"poland|sweden|norway|denmark|finland|greece|romania|czech|hungary|ukraine|turkey|israel|uae|dubai|"
    r"brazil|mexico|argentina|colombia|chile|australia|new zealand|japan|korea|china|singapore|philippines|"
    r"vietnam|indonesia|malaysia|thailand|south africa|nigeria|kenya|egypt|"
    r"california|new york|san francisco|seattle|texas|austin|boston|chicago|atlanta|denver|toronto|vancouver|"
    r"london|berlin|paris|amsterdam|dublin|sydney|melbourne|tokyo)\b",
    re.IGNORECASE,
)
_US_STATE = re.compile(r"(?:,|\s-|\s–)\s?(A[KLRZ]|C[AOT]|D[CE]|FL|GA|HI|I[ADLN]|K[SY]|LA|M[ADEINOST]|N[CDEHJMVY]|O[HKR]|PA|RI|S[CD]|T[NX]|UT|V[AT]|W[AIVY])\b")


def _foreign(text: str) -> bool:
    return bool(_ELSEWHERE.search(text) or _US_STATE.search(text))


def is_early_career(title: str) -> bool:
    return bool(_EARLY.search(title)) and not _SENIOR.search(title)


def is_internship(title: str) -> bool:  # kept for callers that only care about the title
    return is_early_career(title)


_NON_TECH = re.compile(
    r"\b(recruit(ment|ing|er)?|talent|hr|human resources|people|payroll|marketing|brand|growth|sales|"
    r"business development|account(ing|ant)?|finance|legal|content|communications?|social media|operations|"
    r"customer|support|success|admin|procurement|supply chain)\b",
    re.IGNORECASE,
)
_STRONG_TECH = re.compile(r"\b(engineer|developer|software|sde|swe|data scien\w*|machine learning|ml|devops|programmer)\b", re.IGNORECASE)


def classify_track(title: str) -> str:
    """technical (engineering, data, research, IT, QA...) vs non_technical (marketing, HR, sales, ops,
    finance, design, content...). Title-based: descriptions of non-tech roles mention tech constantly.
    A non-tech function word wins over a weak tech word ("IT Recruitment Intern" is HR)."""
    if _NON_TECH.search(title) and not _STRONG_TECH.search(title):
        return "non_technical"
    return "technical" if _TECH.search(title) else "non_technical"


_BOARD_SUFFIX = re.compile(r"\s+(careers?|job board|jobs|hiring|recruiting)$", re.IGNORECASE)


def clean_company(name: str) -> str:
    return _BOARD_SUFFIX.sub("", (name or "").strip()) or name


def location_ok(p: Posting, prefs: Preferences) -> bool:
    if not prefs.locations:
        return True
    loc = p.location or ""
    for want in prefs.locations:
        w = want.strip().lower()
        if w == "remote":
            open_to_india = INDIA_PLACES.search(loc) or _WORLDWIDE.search(loc) or not _foreign(f"{loc} {p.title}")
            if prefs.remote_ok and p.remote and open_to_india:
                return True
        elif w == "india":
            if INDIA_PLACES.search(loc):
                return True
        elif w and w in loc.lower():
            return True
    return False


def is_relevant(p: Posting, prefs: Preferences, now: datetime | None = None) -> bool:
    tagged_entry = bool(p.extra.get("entry_level")) and not _SENIOR.search(p.title)
    if prefs.internships_only and not (is_early_career(p.title) or tagged_entry):
        return False
    if classify_track(p.title) not in prefs.tracks:
        return False
    if not location_ok(p, prefs):
        return False
    if p.posted_at and now and (now - p.posted_at).days > prefs.max_age_days:
        return False
    if prefs.keywords:
        haystack = f"{p.title}\n{p.description[:3000]}".lower()
        return any(
            (words := [w for w in re.findall(r"[a-z0-9+#.]+", kw.lower()) if w not in _STOP]) and all(w in haystack for w in words)
            for kw in prefs.keywords
        )
    return True


_STOP = {"intern", "internship", "and", "or", "the", "a", "of", "for", "in"}
