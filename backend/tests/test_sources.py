from datetime import UTC, datetime, timedelta

import httpx
import respx

from app.schemas import Preferences
from app.sources.base import Posting, classify_track, clean_company, is_relevant, location_ok
from app.sources.providers import AshbySource, GreenhouseSource, JobicySource, LeverSource, MuseSource, RemotiveSource

PREFS = Preferences(greenhouse_boards=[], lever_boards=[], ashby_boards=[])  # India + Remote, both tracks
NOW = datetime(2026, 10, 31, tzinfo=UTC)


def P(title, location="Bengaluru", remote=False, **kw):
    return Posting(source="t", external_id="1", company="C", title=title, location=location, remote=remote, **kw)


def test_track_classification():
    assert classify_track("Software Engineer, Intern") == "technical"
    assert classify_track("Data Analyst Intern") == "technical"
    assert classify_track("Growth Marketing Intern") == "non_technical"
    assert classify_track("Talent Acquisition Intern - IT Recruitment") == "non_technical"  # "IT" doesn't make HR technical
    assert clean_company("HackerRank Careers") == "HackerRank" and clean_company("Rubrik Job Board") == "Rubrik"


def test_location_rules_for_india_and_remote():
    assert location_ok(P("Intern", "Gurugram, Haryana"), PREFS)
    assert location_ok(P("Intern", "Remote - India", remote=True), PREFS)
    assert location_ok(P("Intern", "Worldwide", remote=True), PREFS)
    assert not location_ok(P("Intern", "San Francisco, California", remote=False), PREFS)
    assert not location_ok(P("Intern", "Coraopolis, PA · Flexible / Remote", remote=True), PREFS)  # US-only remote
    assert not location_ok(P("Intern", "Remote - EMEA", remote=True), PREFS)


def test_relevance_level_track_freshness_keywords():
    assert is_relevant(P("Software Engineer Intern"), PREFS, NOW)
    assert not is_relevant(P("Senior Software Engineer"), PREFS, NOW)
    assert is_relevant(P("Customer Support Associate", extra={"entry_level": True}), PREFS, NOW)  # feed-tagged entry level
    assert not is_relevant(P("Marketing Intern"), PREFS.model_copy(update={"tracks": ["technical"]}), NOW)
    stale = P("Data Intern", posted_at=NOW - timedelta(days=90))
    assert not is_relevant(stale, PREFS, NOW)
    focused = PREFS.model_copy(update={"keywords": ["machine learning"]})
    assert is_relevant(P("ML Intern", description="We do machine learning"), focused, NOW)
    assert not is_relevant(P("Finance Intern", description="Excel"), focused, NOW)


@respx.mock
async def test_greenhouse_lists_then_fetches_details_with_retry():
    listing = {"jobs": [
        {"id": 1, "title": "Machine Learning Intern", "absolute_url": "https://x/1", "location": {"name": "Remote - India"}, "updated_at": "2026-10-20T00:00:00Z"},
        {"id": 2, "title": "Senior Account Executive", "absolute_url": "https://x/2", "location": {"name": "NYC"}},
    ]}
    lst = respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").mock(side_effect=[httpx.Response(503), httpx.Response(200, json=listing)])
    detail = respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs/1").mock(
        return_value=httpx.Response(200, json={"content": "&lt;p&gt;Python. Questions: jobs@acme.io&lt;/p&gt;", "company_name": "Acme Careers"})
    )
    async with httpx.AsyncClient() as c:
        [p] = await GreenhouseSource().fetch(c, PREFS.model_copy(update={"greenhouse_boards": ["acme"]}))
    assert lst.call_count == 2 and detail.call_count == 1  # senior role never downloaded
    assert p.external_id == "acme:1" and p.remote and p.company == "Acme" and p.recruiter_email == "jobs@acme.io"
    assert "Python" in p.description and "<p>" not in p.description


@respx.mock
async def test_lever_filters_and_parses_lists():
    respx.get("https://api.lever.co/v0/postings/beta-co").mock(return_value=httpx.Response(200, json=[
        {"id": "a", "text": "Data Science Intern", "hostedUrl": "https://jobs.lever.co/beta-co/a", "categories": {"location": "Bengaluru"},
         "descriptionPlain": "Analyze data.", "lists": [{"text": "Requirements", "content": "<li>SQL</li>"}], "createdAt": 1790000000000},
        {"id": "b", "text": "Staff Engineer", "categories": {"location": "Bengaluru"}},
    ]))
    async with httpx.AsyncClient() as c:
        [p] = await LeverSource().fetch(c, PREFS.model_copy(update={"lever_boards": ["beta-co"]}))
    assert p.company == "Beta Co" and "SQL" in p.description and p.posted_at is not None


@respx.mock
async def test_ashby_marks_intern_employment_type():
    respx.get("https://api.ashbyhq.com/posting-api/job-board/sarvam").mock(return_value=httpx.Response(200, json={"jobs": [
        {"id": "x", "title": "Growth Marketing", "employmentType": "Intern", "location": "Bengaluru", "isListed": True,
         "descriptionPlain": "Run campaigns.", "jobUrl": "https://jobs.ashbyhq.com/sarvam/x", "publishedAt": "2026-10-23T00:00:00Z"},
        {"id": "y", "title": "Hidden Intern", "isListed": False, "location": "Bengaluru"},
    ]}))
    async with httpx.AsyncClient() as c:
        [p] = await AshbySource().fetch(c, PREFS.model_copy(update={"ashby_boards": ["sarvam"]}))
    assert p.title == "Growth Marketing (Intern)" and p.url.endswith("/x") and classify_track(p.title) == "non_technical"


@respx.mock
async def test_public_feeds_parse():
    respx.get(url__startswith="https://www.themuse.com/api/public/jobs").mock(return_value=httpx.Response(200, json={"page_count": 1, "results": [
        {"id": 7, "name": "Finance Associate", "company": {"name": "Muse Co"}, "locations": [{"name": "Mumbai, India"}],
         "levels": [{"name": "Entry Level"}], "contents": "<p>Excel</p>", "publication_date": "2026-10-30T00:00:00Z", "refs": {"landing_page": "https://themuse.com/j/7"}},
    ]}))
    respx.get(url__startswith="https://remotive.com/api/remote-jobs").mock(return_value=httpx.Response(200, json={"jobs": [
        {"id": 9, "title": "Junior QA Engineer", "company_name": "R", "candidate_required_location": "Worldwide", "url": "https://remotive.com/j/9",
         "description": "<p>Test things</p>", "publication_date": "2026-10-29T10:00:00", "job_type": "full_time"},
    ]}))
    respx.get(url__startswith="https://jobicy.com/api/v2/remote-jobs").mock(return_value=httpx.Response(200, json={"jobs": [
        {"id": 3, "jobTitle": "Content Writer", "companyName": "J &amp; Co", "jobGeo": "APAC", "jobLevel": "Entry", "url": "https://jobicy.com/j/3",
         "jobDescription": "<p>Write</p>", "pubDate": "2026-10-28 08:00:00"},
    ]}))
    async with httpx.AsyncClient() as c:
        [m] = await MuseSource().fetch(c, PREFS)
        remotive = await RemotiveSource().fetch(c, PREFS)
        [j] = await JobicySource().fetch(c, PREFS)
    assert m.extra["entry_level"] and is_relevant(m, PREFS, NOW)
    assert remotive[0].remote and is_relevant(remotive[0], PREFS, NOW)
    assert j.company == "J & Co" and j.extra["entry_level"] and is_relevant(j, PREFS, NOW)
