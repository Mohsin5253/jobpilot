"""The recipient (contact) policy for Outreach and Dispatch.

An agent may address an email only to:
(a) the address printed on the posting itself (evidence: the posting URL), or
(b) a contact seen on the company's own public pages (evidence: those URLs), or
(c) a Hunter.io contact with cited public sources, a 'valid' verification (not accept_all / unknown / invalid) and
    confidence at or above HUNTER_MIN_CONFIDENCE.
For (b) and (c) the address's domain must be the company's verified domain, never a free-mail or lookalike domain.
Addresses are never built from a name pattern. An address the student types in themselves is their own decision and is
recorded as such.
"""

from dataclasses import dataclass

from app.config import settings
from app.services.scam_shield import FREE_MAIL, lookalike, registrable


@dataclass
class Verdict:
    allowed: bool
    basis: str  # posting | company_page | hunter | entered_by_you | rejected
    reason: str = ""
    evidence: list[str] | None = None


_CONFUSABLE = str.maketrans({"0": "o", "1": "l", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})


def lookalike_domain(dom: str) -> bool:
    """A brand imitation, including digits standing in for letters (g00gle, micros0ft) and Unicode lookalikes."""
    import unicodedata

    from app.services.scam_shield import _official

    plain = unicodedata.normalize("NFKC", dom)
    swapped = plain.translate(_CONFUSABLE)
    return bool(lookalike(dom) or lookalike(swapped) or (swapped != plain and _official(swapped)) or plain != dom or not plain.isascii())


def _domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower().strip() if "@" in email else ""


def contact_ok(email: str, source: str, company_domain: str, verification: str = "", confidence: int = 0, sources: list[dict] | None = None) -> Verdict:
    email = (email or "").strip().lower()
    dom = _domain(email)
    if not dom:
        return Verdict(False, "rejected", "not an email address")
    if dom in FREE_MAIL:
        return Verdict(False, "rejected", "free-mail address")
    if lookalike_domain(dom):
        return Verdict(False, "rejected", "lookalike domain")
    company = registrable((company_domain or "").lower().removeprefix("www."))
    if not company or registrable(dom) != company:
        return Verdict(False, "rejected", "not on the company's domain")
    urls = [s.get("uri") for s in (sources or []) if s.get("uri")]
    if source == "hunter":
        if (verification or "").lower() != "valid":
            return Verdict(False, "rejected", f"unverified address ({verification or 'unknown'})")
        if confidence < settings.hunter_min_confidence:
            return Verdict(False, "rejected", f"confidence {confidence} below {settings.hunter_min_confidence}")
        if not urls:
            return Verdict(False, "rejected", "no cited public source")
        return Verdict(True, "hunter", evidence=urls[:3])
    if source == "website":
        return Verdict(bool(urls), "company_page" if urls else "rejected", "" if urls else "no page cited", urls[:3])
    if source == "posting":
        return Verdict(True, "posting", evidence=urls[:1])
    return Verdict(False, "rejected", f"unknown source {source}")


def recipient_ok(to: str, *, job_recruiter_email: str | None, job_url: str, company_domain: str | None = None, contact=None) -> Verdict:
    """For a draft about to be sent: who is it going to, and on what basis?"""
    to = (to or "").strip().lower()
    if not to:
        return Verdict(False, "rejected", "no recipient")
    if job_recruiter_email and to == job_recruiter_email.strip().lower():
        # The posting printed it: allowed unless it's free-mail or a lookalike, or the company's domain is known and differs.
        dom = _domain(to)
        if dom in FREE_MAIL or lookalike_domain(dom):
            return Verdict(False, "rejected", "the posting's address is free-mail or a lookalike domain")
        if company_domain and registrable(dom) != registrable(company_domain.lower().removeprefix("www.")):
            return Verdict(False, "rejected", "the posting's address isn't on the company's domain")
        return Verdict(True, "posting", evidence=[job_url])
    if contact is not None and (contact.email or "").lower() == to:
        return contact_ok(to, contact.source, contact.domain, contact.verification, contact.confidence, contact.sources)
    return Verdict(True, "entered_by_you", "an address you typed in yourself")
