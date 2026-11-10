"""Step 6: India sources without scraping: registry, career-page watcher (JSON-LD, robots, 1/min/domain),
GitHub lists, pasted links, forwarded alert emails, dedupe."""

import json
from datetime import UTC, datetime

import httpx
import pytest
import respx
from sqlalchemy import func, select, update

from app.config import settings
from app.db import session_scope
from app.models import Job, JobMatch, Profile, User
from app.services.job_store import store_postings
from app.sources import india
from app.sources.base import Posting

LD = {
    "@context": "https://schema.org",
    "@graph": [
        {"@type": "Organization", "name": "Acme"},
        {
            "@type": "JobPosting", "title": "Data Analyst Intern", "identifier": {"value": "DA-7"},
            "hiringOrganization": {"@type": "Organization", "name": "Acme Analytics Pvt Ltd"},
            "jobLocation": {"@type": "Place", "address": {"addressLocality": "Pune", "addressCountry": "IN"}},
            "datePosted": "2026-11-01", "employmentType": "INTERN",
            "description": "<p>Work with SQL and Python on dashboards. Requirements: SQL, Excel.</p>" * 6,
            "baseSalary": {"@type": "MonetaryAmount", "currency": "INR", "value": {"minValue": 15000, "maxValue": 20000}},
        },
    ],
}
PAGE = f'<html><head><script type="application/ld+json">{json.dumps(LD)}</script></head><body>Careers</body></html>'


@pytest.fixture(autouse=True)
def _reset():
    india._last_hit.clear()
    india._robots.clear()


async def test_registry_documents_tos_and_blocks_job_boards(client, authed):
    rows = {r["id"]: r for r in (await client.get("/api/sources/registry")).json()}
    for b in ("linkedin", "internshala", "naukri", "unstop"):
        assert rows[b]["enabled"] is False and rows[b]["kind"] == "blocked" and "Never" in rows[b]["tos_notes"]
    assert rows["career_page"]["rate_limit_per_min"] == 1 and "robots.txt" in rows["career_page"]["tos_notes"]
    assert all(r["tos_notes"] for r in rows.values())
    gov = (await client.get("/api/sources/gov-portals")).json()
    assert all(".gov.in" in g["url"] or "aicte-india.org" in g["url"] for g in gov)
    async with session_scope() as s:
        await s.execute(update(User).values(is_admin=True))
    assert (await authed.put("/api/admin/sources/linkedin", json={"enabled": True})).status_code == 409


def test_jsonld_jobposting_parsing():
    [p] = india.parse_jobpostings(PAGE, "https://careers.acme.example/jobs")
    assert p.title == "Data Analyst Intern" and p.company.startswith("Acme Analytics") and "Pune" in p.location
    assert p.salary_min == 15000 and p.posted_at.year == 2026 and p.source == "career_page" and p.extra["entry_level"]


@respx.mock
async def test_career_page_respects_robots_throttle_and_blocklist():
    respx.get("https://careers.acme.example/robots.txt").mock(return_value=httpx.Response(200, text="User-agent: *\nDisallow: /private\n"))
    page = respx.get("https://careers.acme.example/jobs").mock(return_value=httpx.Response(200, text=PAGE, headers={"content-type": "text/html"}))
    private = respx.get("https://careers.acme.example/private/jobs").mock(return_value=httpx.Response(200, text=PAGE, headers={"content-type": "text/html"}))
    linkedin = respx.get(url__regex=r".*linkedin\.com.*").mock(return_value=httpx.Response(200))
    async with httpx.AsyncClient() as c:
        assert len(await india.fetch_career_page(c, "https://careers.acme.example/jobs")) == 1
        assert await india.fetch_career_page(c, "https://careers.acme.example/jobs") == []  # within a minute: skipped
        assert await india.fetch_career_page(c, "https://careers.acme.example/private/jobs") == []  # robots.txt says no
        assert await india.fetch_career_page(c, "https://www.linkedin.com/jobs/view/1") == []
    assert page.call_count == 1 and private.call_count == 0 and linkedin.call_count == 0


@respx.mock
async def test_github_listings(monkeypatch):
    monkeypatch.setattr(settings, "github_listings_urls", ["https://raw.githubusercontent.com/x/y/listings.json"])
    respx.get("https://raw.githubusercontent.com/x/y/listings.json").mock(
        return_value=httpx.Response(200, json=[
            {"id": "a1", "company_name": "Acme", "title": "SWE Intern", "locations": ["Bengaluru, India"], "url": "https://acme.example/apply", "date_posted": 1762000000, "active": True, "is_visible": True},
            {"id": "a2", "company_name": "Old", "title": "Intern", "locations": [], "url": "https://old.example", "active": False},
        ])
    )
    src = india.GitHubListingsSource()
    async with httpx.AsyncClient() as c:
        out = await src.fetch(c, __import__("app.schemas", fromlist=["Preferences"]).Preferences())
    assert [p.title for p in out] == ["SWE Intern"] and out[0].posted_at is not None


@respx.mock
async def test_pasted_links(authed):
    linkedin = respx.get(url__regex=r".*linkedin\.com.*").mock(return_value=httpx.Response(200))
    r = (await authed.post("/api/sources/link", json={"url": "https://www.linkedin.com/jobs/view/123"})).json()
    assert r["kind"] == "link_saved" and linkedin.call_count == 0
    r = (await authed.post("/api/sources/link", json={"url": "https://boards.greenhouse.io/razorpay/jobs/42"})).json()
    assert r == {**r, "kind": "board_added", "board": "razorpay"}
    respx.get("https://careers.acme.example/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://careers.acme.example/jobs").mock(return_value=httpx.Response(200, text=PAGE, headers={"content-type": "text/html"}))
    r = (await authed.post("/api/sources/link", json={"url": "https://careers.acme.example/jobs"})).json()
    assert r["kind"] == "career_page" and r["found"] == 1
    async with session_scope() as s:
        prefs = (await s.execute(select(Profile.preferences))).scalar_one()
        assert "razorpay" in prefs["greenhouse_boards"] and prefs["career_pages"] == ["https://careers.acme.example/jobs"]
        assert (await s.execute(select(func.count()).select_from(Job).where(Job.source == "career_page"))).scalar_one() == 1


async def test_forwarded_alert_emails(client, authed, monkeypatch):
    monkeypatch.setattr(settings, "inbound_email_domain", "alerts.jobpilot.test")
    monkeypatch.setattr(settings, "inbound_email_secret", "s3cret")
    addr = (await authed.get("/api/sources/inbound-address")).json()["address"]
    html = (
        '<a href="https://internshala.com/internship/detail/web-dev-intern-at-acme123">Web Development Intern at Acme</a>'
        '<a href="https://unstop.com/jobs/data-analyst-x">Beta Corp - Data Analyst Intern</a>'
        '<a href="https://evil.example/phish">Claim prize</a>'
    )
    assert (await client.post("/api/inbound/email", params={"secret": "wrong"}, json={"To": addr, "HtmlBody": html})).status_code == 403
    r = await client.post("/api/inbound/email", params={"secret": "s3cret"}, json={"To": addr, "HtmlBody": html, "TextBody": ""})
    assert r.json()["saved"] == 2
    async with session_scope() as s:
        jobs = (await s.execute(select(Job).where(Job.source == "email_alert"))).scalars().all()
        assert {(j.title, j.company, j.publisher) for j in jobs} == {("Web Development Intern", "Acme", "Internshala"), ("Data Analyst Intern", "Beta Corp", "Unstop")}
        assert all(j.verification_id for j in jobs) and (await s.execute(select(func.count()).select_from(JobMatch))).scalar_one() == 2
    assert (await client.post("/api/inbound/email", params={"secret": "s3cret"}, json={"To": "alerts+ffffff@alerts.jobpilot.test", "HtmlBody": html})).json()["saved"] == 0


async def test_dedupe_by_company_title_location_across_sources():
    now = datetime.now(UTC)
    a = Posting(source="greenhouse", external_id="acme:1", company="Acme", title="Data Analyst Intern", location="Pune, India", url="https://boards.greenhouse.io/acme/jobs/1", description="SQL " * 120)
    b = Posting(source="career_page", external_id="x1", company="Acme", title="Data Analyst Intern", location="Pune, India", url="https://careers.acme.example/jobs/da", description="SQL " * 120)
    await store_postings([a, b], now)
    async with session_scope() as s:
        jobs = (await s.execute(select(Job))).scalars().all()
    assert len(jobs) == 1 and len(jobs[0].apply_links) == 2
