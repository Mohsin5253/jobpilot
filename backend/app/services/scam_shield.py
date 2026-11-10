"""Scam Shield: checks an internship offer (a pasted WhatsApp / Telegram / email message, a link, or an offer letter)
for the signs of India's common internship scams, and explains each finding.

Every check returns pass / warn / fail (or "unverified" when we can't check) with the evidence it found. Rules come
first, in English, Hindi, Marathi and Hinglish, so a verdict is fast, free and reproducible. When an LLM is
configured it gives a second opinion that can only make the verdict stricter, and it answers with a category, never
free text, so nothing it writes is stored.

Nothing pasted is stored: callers persist only a hash of the input and each check's status. The same rules run on
every posting the Scout finds (see agents/verifier.py).
"""

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlparse

Status = Literal["pass", "warn", "fail", "unverified"]
Verdict = Literal["Likely safe", "Suspicious", "Likely scam"]

FREE_MAIL = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "yahoo.in", "outlook.com", "hotmail.com", "live.com", "rediffmail.com",
    "proton.me", "protonmail.com", "icloud.com", "aol.com", "ymail.com", "zoho.in", "mail.com", "gmx.com",
}
# Applicant-tracking systems and job platforms: a link here is a real application, not a chat.
ATS_HOSTS = (
    "greenhouse.io", "lever.co", "ashbyhq.com", "myworkdayjobs.com", "smartrecruiters.com", "workable.com", "icims.com", "taleo.net",
    "bamboohr.com", "recruitee.com", "teamtailor.com", "zohorecruit.com", "keka.com", "darwinbox.in", "successfactors.com",
)
# Brands scammers impersonate most, with their real domains (a subdomain of these is fine).
BRANDS: dict[str, tuple[str, ...]] = {
    "google": ("google.com", "careers.google.com"),
    "amazon": ("amazon.com", "amazon.in", "amazon.jobs"),
    "microsoft": ("microsoft.com",),
    "tcs": ("tcs.com",),
    "infosys": ("infosys.com",),
    "wipro": ("wipro.com",),
    "flipkart": ("flipkart.com", "flipkartcareers.com"),
    "accenture": ("accenture.com",),
    "deloitte": ("deloitte.com",),
    "cognizant": ("cognizant.com",),
    "hcltech": ("hcltech.com", "hcl.com"),
    "zomato": ("zomato.com",),
    "swiggy": ("swiggy.com", "swiggy.in"),
    "paytm": ("paytm.com",),
    "reliance": ("ril.com", "jio.com", "relianceretail.com"),
    "isro": ("isro.gov.in",),
    "drdo": ("drdo.gov.in",),
    "internshala": ("internshala.com",),
    "naukri": ("naukri.com",),
    "unstop": ("unstop.com",),
    "linkedin": ("linkedin.com",),
}
GOV_SUFFIXES = (".gov.in", ".nic.in", ".gov")

# ── Patterns. Each list mixes English, Hindi (Devanagari), Marathi and Hinglish. ──

_FEE = re.compile(
    r"(registration|training|certificate|certification|joining|processing|onboarding|verification|security|document|id[- ]?card|"
    r"kit|uniform|laptop|courier|caution|enrol+ment|enrollment)\s*(fee|fees|charge|charges|amount|deposit|money)"
    r"|refundable\s*(deposit|amount|fee|fees)?|(amount|money|fee|fees|deposit)\s*(will be|is|are)\s*(fully\s*)?refund"
    r"|(pay|deposit|transfer|send)\s*(a\s*|the\s*|only\s*|just\s*)?(small\s*|nominal\s*|one[- ]time\s*)?(fee|fees|amount|charges|deposit)"
    r"|(pay|deposit|transfer|send)\s*(rs\.?|inr|₹)\s*\d"
    r"|(rs\.?|inr|₹)\s*\d[\d,]*\s*(/-)?\s*(only\s*)?(to|for)\s*(confirm|book|reserve|secure|register|block|activate|unlock)"
    # Hinglish
    r"|fees?\s*(jama|deni|dena|bharna|bharo|bhare)|(paise|paisa|amount|charge)\s*(jama|dena|bhejo|bhejna)|(pay|payment)\s*karna\s*(hoga|padega|hai)|ka\s*payment|payment\s*(karo|kare|karein|bhejo)"
    r"|refundable\s*hai|wapas\s*mil\s*jayeg"
    # Hindi
    r"|पंजीकरण\s*शुल्क|रजिस्ट्रेशन\s*(फीस|शुल्क|चार्ज)|ट्रेनिंग\s*(फीस|शुल्क)|प्रशिक्षण\s*शुल्क|सर्टिफिकेट\s*(फीस|शुल्क)"
    r"|(फीस|शुल्क|राशि|रुपये|पैसे)\s*(जमा|भरें|भरना|दें|देने)|जमा\s*(करें|कराएं|करना|करवाएं)|सिक्योरिटी\s*डिपॉजिट|वापस\s*(कर\s*दी|मिल)"
    # Marathi
    r"|नोंदणी\s*शुल्क|प्रशिक्षण\s*फी|प्रमाणपत्र\s*शुल्क|(शुल्क|फी|रक्कम)\s*(भरा|भरावे|भरावी|भरणे)|अनामत\s*रक्कम|परत\s*मिळेल",
    re.IGNORECASE,
)
_UPI_ID = re.compile(
    r"\b[a-z0-9][a-z0-9.\-_]{1,60}@(ok(?:axis|sbi|hdfcbank|icici)|ybl|ibl|axl|paytm|upi|apl|yapl|ikwik|fbl|pz|kotak|icici|sbi|hdfcbank|"
    r"axisbank|barodampay|freecharge|jupiteraxis|slc|timecosmos|waaxis|wahdfcbank|waicici|wasbi|airtel|idfcbank|indus|rbl|federal)(?![\w-]|\.[a-z])",
    re.IGNORECASE,
)
_PAY_APP = re.compile(
    r"\b(upi\s*(id|pin)?|g\s?pay|google\s*pay|phone\s?pe|paytm\s*(number|no|karo|kar)|bhim|scan\s*(the|this|our)?\s*(qr|code)|qr\s*code)\b|क्यूआर\s*कोड",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"\b[a-z0-9._%+\-]+@([a-z0-9\-]+(?:\.[a-z0-9\-]+)+)\b", re.IGNORECASE)
_URL = re.compile(r"\b((?:https?://|www\.)[^\s<>\"')]+|(?:t\.me|wa\.me|bit\.ly|tinyurl\.com)/[^\s<>\"')]+)", re.IGNORECASE)
_BARE_DOMAIN = re.compile(r"\b((?:[a-z0-9\-]+\.)+(?:com|in|co\.in|org|net|io|online|site|xyz|info|top|live|club|work|jobs))\b", re.IGNORECASE)
_COMPANY_CLAIM = re.compile(r"\b(pvt\.?\s*ltd|private\s+limited|limited|ltd\.?|llp|inc\.?|technologies|solutions|infotech|softech|consultancy|corporation)\b", re.IGNORECASE)
_NO_INTERVIEW = re.compile(
    r"without\s*(any\s*)?interview|no\s*interview|direct\s*(selection|joining|hiring)|selected\s*directly|(you|u)\s*(are|have\s*been|r)\s*(selected|shortlisted)"
    r"|congratulations?[!,.\s]+.{0,40}(selected|shortlisted)|aapka\s*selection|selection\s*ho\s*gaya"
    r"|बिना\s*(किसी\s*)?इंटरव्यू|आपका\s*(चयन|सिलेक्शन)|मुलाखतीशिवाय|आपली\s*निवड",
    re.IGNORECASE,
)
_INTERVIEW = re.compile(r"\binterview|technical\s*round|coding\s*(round|test)|assessment|assignment|इंटरव्यू|साक्षात्कार|मुलाखत", re.IGNORECASE)
_URGENT = re.compile(
    r"within\s*([1-9]|1\d|2[0-4])\s*(hours?|hrs?)\b|within\s*\d+\s*(minutes?|mins?)|today\s*(itself|only)|last\s*(chance|date\s*(is\s*)?today)|limited\s*(seats|slots|positions)|hurry"
    r"|\burgent(ly)?\b|immediately|seats?\s*(are\s*)?filling|offer\s*(expires|valid\s*till\s*today)|before\s*\d{1,2}\s*(pm|am)\s*today"
    r"|\bjaldi\b|\baaj\s*hi\b|\bturant\b|जल्दी|तुरंत|आज\s*ही|लवकर|आजच|ताबडतोब",
    re.IGNORECASE,
)
_SECRET = re.compile(r"\b(otp|one[- ]time\s*password|atm\s*pin|upi\s*pin|mpin|cvv|net\s*banking\s*(password|login)|card\s*number)\b|ओटीपी", re.IGNORECASE)
_ID_DOCS = re.compile(
    r"\b(aadhaa?r|aadhar|pan\s*card|pan\s*number|bank\s*(account|a/c)\s*(details|number|no)|passbook|cancel+ed\s*cheque)\b|आधार|पैन\s*कार्ड|बैंक\s*खाते",
    re.IGNORECASE,
)
# Sending documents over chat or email is the risk; bringing them to HR on the joining day is normal.
_SEND_DOCS = re.compile(r"\b(send|share|upload|forward|whats\s?app|mail|email|submit|bhejo|bhejiye)\b|भेज|पाठवा", re.IGNORECASE)
_CHAT = re.compile(
    r"(contact|message|ping|dm|reach|text|whatsapp)\s*(us|me|hr)?\s*(on|via|at)?\s*(whats\s?app|telegram)|join\s*(our|the)?\s*telegram|telegram\s*(group|channel|@)"
    r"|whats\s?app\s*(me|us|hr|no|number|:|pe|par)\b|\bt\.me/|\bwa\.me/|व्हाट्सएप\s*(पर|वर)|टेलीग्राम",
    re.IGNORECASE,
)
_TASK = re.compile(
    r"\blike\s*(and\s*subscribe\s*)?(youtube\s*)?videos|subscribe\s*(to\s*)?(youtube\s*)?channels?\s*(and|&)\s*earn|rate\s*(hotels?|products?|restaurants?|movies?)"
    r"|(give|post|write)\s*(5[- ]star\s*)?(google\s*)?(map\s*)?reviews?\s*(and|&|to)\s*earn|prepaid\s*tasks?|merchant\s*tasks?|recharge\s*tasks?|vip\s*tasks?"
    r"|commission\s*per\s*task|per\s*task\s*(rs|₹|inr)|(rs\.?|₹|inr)\s*\d+\s*(per|for\s*each|/)\s*(like|task|review|video)"
    r"|(earn|kamao|kamaye)\s*(rs\.?|₹|inr)?\s*\d[\d,]*\s*(\+\s*)?(per|a|/|daily|roz|rozana)\s*(day|din)?",
    re.IGNORECASE,
)
_GOV = re.compile(
    r"\b(government|govt\.?|sarkari|ministry\s*of|pm\s*internship|prime\s*minister'?s?\s*internship|digital\s*india\s*internship|central\s*government"
    r"|isro|drdo|niti\s*aayog|nic\s*internship)\b|सरकारी|प्रधानमंत्री\s*इंटर्नशिप|शासकीय",
    re.IGNORECASE,
)
_MONEY = re.compile(r"(?:rs\.?|inr|₹)\s*(\d[\d,]*)(?:\s*(k|lakh|lac))?|(\d[\d,]*)\s*(?:rs|rupees|रुपये|रुपए)", re.IGNORECASE)
_PER_DAY = re.compile(r"(per|a|/)\s*day|daily|roz|प्रतिदिन|रोज", re.IGNORECASE)
_NO_FEE = re.compile(r"\b(no|zero|never\s*(ask|charge)\s*(for\s*)?(any\s*)?)\s*(fee|fees|charges|payment)s?\b|free\s*of\s*(cost|charge)|we\s*never\s*charge", re.IGNORECASE)


@dataclass
class Check:
    id: str
    label: str
    status: Status
    evidence: list[str] = field(default_factory=list)
    weight: int = 0  # risk points when warn


@dataclass
class ShieldResult:
    verdict: Verdict
    score: int  # risk, 0 (nothing found) to 100
    checks: list[Check]
    input_hash: str
    llm_category: str | None = None

    def as_dict(self) -> dict:
        return {"verdict": self.verdict, "score": self.score, "checks": [asdict(c) for c in self.checks], "input_hash": self.input_hash, "llm_category": self.llm_category}

    def redacted_checks(self) -> list[dict]:
        """What may be stored: each check's id and status, never the evidence quoted from the message."""
        return [{"id": c.id, "status": c.status} for c in self.checks]

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if c.status == "fail"]

    @property
    def warned(self) -> list[Check]:
        return [c for c in self.checks if c.status == "warn"]


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text or "")).strip()


def input_hash(text: str, url: str = "") -> str:
    return hashlib.sha256(f"{normalize(text).lower()}\n{(url or '').strip().lower()}".encode()).hexdigest()


def _snip(text: str, m: re.Match, pad: int = 30) -> str:
    a, b = max(0, m.start() - pad), min(len(text), m.end() + pad)
    return ("…" if a else "") + text[a:b].strip() + ("…" if b < len(text) else "")


def _all(pattern: re.Pattern, text: str, limit: int = 2) -> list[str]:
    """Up to `limit` quoted snippets, skipping matches that overlap the previous snippet."""
    out, last_end = [], None
    for m in pattern.finditer(text):
        if last_end is not None and m.start() <= last_end:
            continue
        out.append(_snip(text, m))
        last_end = m.end() + 60
        if len(out) == limit:
            break
    return out


def _host(url: str) -> str:
    try:
        u = url if "://" in url else f"http://{url}"
        return (urlparse(u).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def registrable(host: str) -> str:
    """example.co.in from careers.example.co.in (good enough for the TLDs scammers use)."""
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in ("co.in", "gov.in", "nic.in", "org.in", "net.in", "ac.in", "edu.in", "co.uk"):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _lev(a: str, b: str) -> int:
    if abs(len(a) - len(b)) > 2:
        return 3
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _official(host: str) -> str | None:
    """The brand whose real domain this host belongs to, if any."""
    for brand, domains in BRANDS.items():
        if any(host == d or host.endswith("." + d) for d in domains):
            return brand
    return None


def lookalike(host: str) -> str | None:
    """A reason when a host imitates a brand: the brand's name on someone else's domain, or a near-miss spelling."""
    if not host or _official(host) or host.endswith(ATS_HOSTS) or host.endswith(GOV_SUFFIXES):
        return None
    reg = registrable(host)
    label = reg.split(".")[0]
    for brand, domains in BRANDS.items():
        real_labels = {registrable(d).split(".")[0] for d in domains}
        if brand in re.split(r"[^a-z0-9]+", label) or (brand in label and len(brand) >= 5 and label not in real_labels):
            return f"{host} uses the name “{brand}” but isn’t {brand}’s domain ({domains[0]})"
        if any(len(r) >= 5 and 0 < _lev(label, r) <= (1 if len(r) <= 6 else 2) for r in real_labels):
            return f"{host} looks like a misspelling of {domains[0]}"
    return None


def _money_values(text: str) -> list[int]:
    out = []
    for m in _MONEY.finditer(text):
        raw = (m.group(1) or m.group(3) or "").replace(",", "")
        if not raw.isdigit():
            continue
        v = int(raw)
        unit = (m.group(2) or "").lower()
        v *= 1000 if unit == "k" else 100_000 if unit in ("lakh", "lac") else 1
        out.append(v)
    return out


def analyze(text: str, url: str = "", *, domain_ages: dict[str, int] | None = None, known_company_domain: str | None = None) -> ShieldResult:
    """Rule-based checks. `domain_ages` (domain -> days since registration, from RDAP) is looked up by the caller,
    so this function stays pure and fast."""
    text = normalize(text)
    full = f"{text}\n{url}".strip()
    checks: list[Check] = []

    emails = [(m.group(0), m.group(1).lower()) for m in _EMAIL.finditer(text)]
    upi_ids = [m.group(0) for m in _UPI_ID.finditer(text)]
    emails = [(e, d) for e, d in emails if e not in upi_ids]
    hosts = {_host(u) for u in _URL.findall(full)} | {d.lower() for d in _BARE_DOMAIN.findall(text)} | ({_host(url)} if url else set())
    hosts |= {d for _, d in emails}
    hosts = {h for h in hosts if h and "." in h}
    company_hosts = {h for h in hosts if registrable(h) not in FREE_MAIL and not h.startswith(("t.me", "wa.me", "bit.ly", "tinyurl"))}

    # 1. Money demanded.
    fee = _all(_FEE, text)
    no_fee_promise = bool(_NO_FEE.search(text))
    if fee and not (no_fee_promise and not _PAY_APP.search(text) and not upi_ids):
        checks.append(Check("fee", "Asks you to pay a fee or deposit", "fail", fee))
    else:
        checks.append(Check("fee", "No fee or deposit asked for", "pass"))

    # 2. UPI IDs / QR codes / payment apps.
    pay = [*upi_ids[:2], *_all(_PAY_APP, text, 1)]
    if upi_ids or (pay and (fee or _money_values(text))):
        checks.append(Check("upi", "Gives a UPI ID, QR code or payment app to pay", "fail", pay))
    elif pay:
        checks.append(Check("upi", "Mentions a payment app", "warn", pay, 15))
    else:
        checks.append(Check("upi", "No UPI ID or QR code", "pass"))

    # 3. Recruiter on a free mail domain while claiming to be a company.
    free = [e for e, d in emails if registrable(d) in FREE_MAIL]
    company_claimed = bool(_COMPANY_CLAIM.search(text)) or any(b in text.lower() for b in BRANDS)
    if free and company_claimed:
        checks.append(Check("free_mail", "A company recruiter writing from a personal email", "warn", free[:2], 20))
    elif free:
        checks.append(Check("free_mail", "Uses a personal email address", "warn", free[:2], 10))
    elif emails:
        checks.append(Check("free_mail", "Email is on a company domain", "pass", [emails[0][0]]))

    # 4. Lookalike domains, and very new domains.
    looks = [r for h in sorted(company_hosts) if (r := lookalike(h))]
    young = [f"{d} was registered {age} days ago" for d, age in (domain_ages or {}).items() if age < 180]
    if looks:
        checks.append(Check("lookalike", "Uses a lookalike of a well-known company’s domain", "fail", looks[:2]))
    elif young:
        checks.append(Check("lookalike", "Website registered only recently", "warn", young[:2], 20))
    elif company_hosts:
        checks.append(Check("lookalike", "No lookalike domains found", "pass", sorted(company_hosts)[:2]))

    # 5. Company identity: there's no free, official MCA/GST lookup API to call, so we say so instead of guessing.
    on_ats = any(h.endswith(ATS_HOSTS) for h in hosts)
    official_brand = next((b for h in hosts if (b := _official(h))), None)
    if on_ats or official_brand or (known_company_domain and any(h == known_company_domain or h.endswith("." + known_company_domain) for h in hosts)):
        checks.append(Check("identity", "Links to the company’s own careers site", "pass", [official_brand or "company careers system"]))
    else:
        checks.append(Check("identity", "Company identity not verified (no MCA/GST record checked)", "unverified"))

    # 6. Selected without an interview.
    selected = _all(_NO_INTERVIEW, text, 1)
    if selected and not (_INTERVIEW.search(text) and not re.search(r"without|no\s*interview|बिना|शिवाय", text, re.IGNORECASE)):
        checks.append(Check("no_interview", "Says you’re selected without an interview", "warn", selected, 20))
    else:
        checks.append(Check("no_interview", "No “selected without interview” claim", "pass"))

    # 7. Pay that's too good, or paid by the day.
    money = _money_values(text)
    per_day = bool(_PER_DAY.search(text)) and bool(money)
    if per_day and not fee:
        checks.append(Check("stipend", "Promises pay per day, typical of task scams", "warn", _all(_MONEY, text, 1), 20))
    elif money and max(money) >= 100_000 and re.search(r"intern|trainee|fresher|इंटर्न", text, re.IGNORECASE) and not re.search(r"lpa|ctc|per\s*annum|annual", text, re.IGNORECASE):
        checks.append(Check("stipend", "Stipend looks implausibly high for an internship", "warn", _all(_MONEY, text, 1), 15))
    else:
        checks.append(Check("stipend", "No implausible pay promised", "pass"))

    # 8. Pressure.
    urgent = _all(_URGENT, text)
    checks.append(Check("urgency", "Pushes you to act fast", "warn", urgent, 15) if urgent else Check("urgency", "No pressure tactics", "pass"))

    # 9. Secrets and ID documents.
    secrets = _all(_SECRET, text, 1)
    ids = _all(_ID_DOCS, text, 1)
    if secrets:
        checks.append(Check("ids", "Asks for an OTP, PIN or card details", "fail", secrets))
    elif ids and _SEND_DOCS.search(text) and not _INTERVIEW.search(text):
        checks.append(Check("ids", "Asks you to send Aadhaar, PAN or bank details before any interview", "warn", ids, 25))
    elif ids and _SEND_DOCS.search(text):
        checks.append(Check("ids", "Asks you to send ID documents", "warn", ids, 10))
    else:
        checks.append(Check("ids", "No request for OTPs, PINs or ID documents", "pass"))

    # 10. Chat-only hiring.
    chat = _all(_CHAT, text, 1)
    if chat and not (on_ats or official_brand or (company_hosts - {"t.me", "wa.me"})):
        checks.append(Check("chat_only", "Hiring happens only over WhatsApp or Telegram", "warn", chat, 25))
    elif chat:
        checks.append(Check("chat_only", "Moves the conversation to WhatsApp or Telegram", "warn", chat, 10))
    else:
        checks.append(Check("chat_only", "Not a chat-only offer", "pass"))

    # 11. Task scams: paid likes, reviews or "prepaid tasks".
    task = _all(_TASK, text, 1)
    checks.append(Check("task", "Pays for likes, reviews or tasks (a task scam)", "fail", task) if task else Check("task", "No paid-task scheme", "pass"))

    # 12. Fake government internships.
    gov = _GOV.search(text)
    if gov:
        gov_hosts = {h for h in hosts if h.endswith(GOV_SUFFIXES)}
        other = {h for h in company_hosts if not h.endswith(GOV_SUFFIXES)}
        if fee or upi_ids or free:
            checks.append(Check("gov", "Claims to be a government internship but asks for money or uses personal email", "fail", [_snip(text, gov)]))
        elif other and not gov_hosts:
            checks.append(Check("gov", "Claims to be a government internship but links to a non-government site", "warn", [*sorted(other)[:1], _snip(text, gov)], 30))
        else:
            checks.append(Check("gov", "Government links use official .gov.in / .nic.in sites", "pass", sorted(gov_hosts)[:1]))

    score = min(100, 45 * sum(c.status == "fail" for c in checks) + sum(c.weight for c in checks if c.status == "warn"))
    verdict: Verdict = "Likely scam" if any(c.status == "fail" for c in checks) or score >= 60 else "Suspicious" if score >= 25 else "Likely safe"
    return ShieldResult(verdict, score, checks, input_hash(text, url))


def stricter(result: ShieldResult, category: str) -> ShieldResult:
    """Applies an LLM second opinion: it can raise the verdict, never lower it."""
    if category in ("fee_scam", "task_scam", "fake_government", "identity_theft"):
        result.checks.append(Check("llm", "The AI reviewer also reads this as a scam", "fail", [category.replace("_", " ")]))
        result.verdict, result.score = "Likely scam", max(result.score, 70)
    elif category == "suspicious" and result.verdict == "Likely safe":
        result.checks.append(Check("llm", "The AI reviewer found it suspicious", "warn", [], 25))
        result.verdict, result.score = "Suspicious", max(result.score, 30)
    result.llm_category = category
    return result


ADVICE = {
    "Likely scam": [
        "Don’t pay anything. Real internships never charge a fee, deposit or certificate charge.",
        "Don’t share OTPs, PINs, Aadhaar or bank details.",
        "Report it at cybercrime.gov.in or call 1930 (National Cyber Crime Helpline), especially if you’ve paid.",
        "Report the message or profile on the platform where you got it (WhatsApp, Telegram, Instagram or the job site).",
    ],
    "Suspicious": [
        "Don’t pay anything or share ID documents until you’ve checked.",
        "Find the company’s own website yourself (not from the message) and apply or confirm there.",
        "Ask for an interview and an official email from the company’s domain. Scammers usually avoid both.",
        "If you’ve already paid or shared details, report it at cybercrime.gov.in or call 1930.",
    ],
    "Likely safe": [
        "Nothing we check for was found, but stay careful: never pay to get an internship.",
        "Apply through the company’s own site, and keep everything in writing.",
    ],
}


def redact(text: str) -> str:
    """For an opt-in scam report: keeps the scam's shape, drops personal details (phones, emails' user parts, IDs)."""
    t = normalize(text)
    t = _UPI_ID.sub(lambda m: "[upi]@" + m.group(0).split("@")[1], t)
    t = _EMAIL.sub(lambda m: "[email]@" + m.group(1), t)
    t = re.sub(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)", "[phone]", t)
    t = re.sub(r"\b\d{4}\s?\d{4}\s?\d{4}\b", "[aadhaar]", t)
    t = re.sub(r"\b[A-Z]{5}\d{4}[A-Z]\b", "[pan]", t)
    t = re.sub(r"\b\d{9,18}\b", "[number]", t)
    return t[:5000]


def now() -> datetime:
    return datetime.now(UTC)
