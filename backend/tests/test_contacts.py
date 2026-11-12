"""Contact Finder: only real, publicly sourced addresses; senior people in the role's department first."""

import httpx
import respx

from app.config import settings
from app.models import CompanyContact, Job
from app.services import contacts as ct

HUNTER_RESPONSE = {"data": {"domain": "acme.ai", "emails": [
    {"value": "priya.rao@acme.ai", "type": "personal", "provenance": "found", "confidence": 96, "first_name": "Priya", "last_name": "Rao",
     "position": "Head of Machine Learning", "seniority": "executive", "department": "it",
     "sources": [{"uri": "https://acme.ai/blog/ml-team", "last_seen_on": "2026-10-01"}], "verification": {"status": "valid"}},
    {"value": "guess.person@acme.ai", "type": "personal", "provenance": "inferred", "confidence": 70, "first_name": "Guess", "last_name": "Person",
     "position": "Engineering Manager", "seniority": "senior", "department": "it", "sources": [], "verification": {"status": "unknown"}},
    {"value": "arjun@acme.ai", "type": "personal", "provenance": "found", "confidence": 90, "first_name": "Arjun", "last_name": "Mehta",
     "position": "Talent Partner", "seniority": "senior", "department": "hr",
     "sources": [{"uri": "https://acme.ai/careers", "last_seen_on": "2026-10-20"}], "verification": {"status": "accept_all"}},
]}}

CAREERS_HTML = '<html><title>Acme AI careers</title><a href="mailto:careers@acme.ai">Apply</a> privacy@acme.ai noreply@acme.ai sales@acme.ai</html>'


def job(**kw) -> Job:
    base = dict(id=None, company="Acme AI", title="Machine Learning Intern", track="technical", url="https://jobs.lever.co/acme/1",
                recruiter_email=None, company_domain="acme.ai", location="Bengaluru", description="", skills=[])
    base.update(kw)
    return Job(**base)


def test_registrable_and_department_mapping():
    assert ct.registrable("careers.stripe.com") == "stripe.com"
    assert ct.registrable("www.flipkart.co.in") == "flipkart.co.in"
    assert not ct._ok_company_domain("boards.greenhouse.io") and ct._ok_company_domain("acme.ai")
    assert ct.departments_for(job()) == "it,research,product,executive,hr"
    assert ct.departments_for(job(title="Growth Marketing Intern", track="non_technical")).startswith("marketing,communication")


@respx.mock
async def test_find_contacts_keeps_only_found_and_ranks_senior_ml_lead_first(monkeypatch):
    monkeypatch.setattr(settings, "hunter_api_key", "test")
    monkeypatch.setattr(settings, "website_contacts_enabled", True)
    hunter = respx.get("https://api.hunter.io/v2/domain-search").mock(return_value=httpx.Response(200, json=HUNTER_RESPONSE))
    respx.get("https://acme.ai/robots.txt").mock(return_value=httpx.Response(200, text="User-agent: *\nDisallow: /about"))
    respx.get("https://acme.ai/careers").mock(return_value=httpx.Response(200, text=CAREERS_HTML, headers={"content-type": "text/html"}))
    about = respx.get("https://acme.ai/about").mock(return_value=httpx.Response(200, text="hr@acme.ai"))
    respx.get(url__regex=r"https://acme\.ai/.*").mock(return_value=httpx.Response(404))

    ranked = await ct.find_contacts(job())
    emails = [c.email for c in ranked]
    assert "guess.person@acme.ai" not in emails  # pattern-inferred: never used
    assert {"privacy@acme.ai", "noreply@acme.ai", "sales@acme.ai"}.isdisjoint(emails)
    assert emails[0] == "priya.rao@acme.ai"  # senior ML/IT lead first
    assert "arjun@acme.ai" not in emails  # Hunter 'accept_all' isn't a verified address: never used (contact policy)
    assert "careers@acme.ai" in emails
    assert ct.official_address(ranked).email == "careers@acme.ai"
    assert about.call_count == 0  # robots.txt respected
    params = hunter.calls[0].request.url.params
    assert params["seniority"] == "senior,executive" and params["type"] == "personal" and "it" in params["department"]
    top = ranked[0]
    assert top.sources[0]["uri"] == "https://acme.ai/blog/ml-team" and top.verification == "valid"

    # Cached for the domain: a second lookup doesn't spend another Hunter credit.
    await ct.find_contacts(job())
    assert hunter.call_count == 1


async def test_posting_email_used_without_any_network():
    ranked = await ct.find_contacts(job(company_domain=None, url="https://boards.greenhouse.io/acme/1", recruiter_email="Jobs@Acme.ai"))
    assert [c.email for c in ranked] == ["jobs@acme.ai"] and ranked[0].source == "posting"


def test_rank_prefers_department_match_over_hr_and_generic():
    j = job()
    make = lambda **kw: CompanyContact(domain="acme.ai", email=kw.pop("email"), kind=kw.pop("kind", "person"), seniority=kw.pop("seniority", ""), department=kw.pop("department", ""), source=kw.pop("source", "hunter"), confidence=kw.pop("confidence", 80), verification=kw.pop("verification", "valid"), sources=[{"uri": "u"}])  # noqa: E731
    order = ct.rank([
        make(email="careers@acme.ai", kind="generic", source="website"),
        make(email="hr@acme.ai", seniority="senior", department="hr"),
        make(email="cto@acme.ai", seniority="executive", department="it"),
        make(email="rec@acme.ai", kind="generic", source="posting"),
    ], j)
    assert [c.email for c in order] == ["cto@acme.ai", "hr@acme.ai", "rec@acme.ai", "careers@acme.ai"]
    assert ct.official_address(order).email == "rec@acme.ai"  # CC'd: the posting's own address


def test_rank_founder_beats_generic_inbox():
    j = job()
    ceo = CompanyContact(domain="acme.ai", email="ceo@acme.ai", kind="person", seniority="executive", department="executive", source="hunter", confidence=95, verification="valid", sources=[{"uri": "u"}])
    posting = CompanyContact(domain="acme.ai", email="internship-queries@acme.ai", kind="generic", source="posting", confidence=0, verification="", sources=[{"uri": "u"}])
    assert [c.email for c in ct.rank([posting, ceo], j)] == ["ceo@acme.ai", "internship-queries@acme.ai"]


async def test_outreach_greets_senior_contact_by_first_name():
    from app.agents.outreach import greeting, template_draft
    from app.models import JobMatch
    from app.schemas import ResumeData

    j = job()
    lead = CompanyContact(domain="acme.ai", email="priya.rao@acme.ai", kind="person", first_name="Priya", last_name="Rao", position="Head of ML", source="hunter")
    generic = CompanyContact(domain="acme.ai", email="careers@acme.ai", kind="generic", source="website")
    assert greeting(j, lead) == "Hi Priya," and greeting(j, generic) == "Hi Acme AI team," and greeting(j, None) == "Hi Acme AI team,"
    m = JobMatch(strengths=["Python"], gaps=[])
    m.job = j
    draft = template_draft(ResumeData(name="Aarav Mehta"), m, [], lead)
    assert draft.email_body.startswith("Hi Priya,")
