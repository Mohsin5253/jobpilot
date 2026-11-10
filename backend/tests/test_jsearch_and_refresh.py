"""JSearch (LinkedIn / Indeed / Naukri / Glassdoor / Wellfound via Google for Jobs), authenticity checks,
cross-board de-duplication and the every-minute refresh schedule."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import respx
from sqlalchemy import select

from app.config import settings
from app.db import session_scope
from app.models import Job
from app.schemas import Preferences
from app.services.ingest import ingest_tick
from app.services.runs import claim_next, execute_run
from app.sources.authenticity import check_link, dedupe_key, looks_legit
from app.sources.base import Posting
from app.sources.providers import JSearchSource

SAMPLE = Path(__file__).resolve().parents[1] / "evals" / "data" / "sample_resume.md"
LONG = "We are hiring a machine learning intern to build Python models with scikit-learn and SQL. " * 5


def jsearch_payload(*jobs):
    return {"status": "OK", "data": {"cursor": "next-123", "jobs": list(jobs)}}  # v5 shape


def jjob(job_id, title, employer, publisher="LinkedIn", city="Bengaluru", desc=LONG, link="https://www.linkedin.com/jobs/view/1", options=None, site="https://acme.ai"):
    return {
        "job_id": job_id, "job_title": title, "employer_name": employer, "employer_website": site,
        "job_publisher": publisher, "job_apply_link": link, "job_apply_is_direct": False,
        "apply_options": options if options is not None else [
            {"publisher": publisher, "apply_link": link, "is_direct": False},
            {"publisher": "Acme Careers", "apply_link": "https://acme.ai/careers/ml-intern", "is_direct": True},
        ],
        "job_description": desc, "job_is_remote": False, "job_city": city, "job_state": "Karnataka", "job_country": "IN",
        "job_posted_at_datetime_utc": (datetime.now(UTC) - timedelta(days=2)).isoformat(), "job_employment_type": "INTERN",
    }


async def _upload(c):
    r = await c.post("/api/profile/resume", files={"file": ("resume.md", SAMPLE.read_bytes(), "text/markdown")})
    assert r.status_code == 200


async def _work():
    claimed = await claim_next("test-worker")
    assert claimed is not None
    return await execute_run(claimed.id, claimed.user_id)


def test_scam_and_thin_postings_are_rejected():
    ok = Posting(source="jsearch", external_id="1", company="Acme", title="ML Intern", description=LONG)
    assert looks_legit(ok)[0]
    assert not looks_legit(Posting(source="jsearch", external_id="2", company="Acme", title="ML Intern", description="short"))[0]
    scam = Posting(source="jsearch", external_id="3", company="Acme", title="Data Entry Intern", description=LONG + " Registration fee of Rs 999 required.")
    assert looks_legit(scam) == (False, "scam pattern")
    assert not looks_legit(Posting(source="jsearch", external_id="4", company="Confidential", title="Intern", description=LONG))[0]


def test_dedupe_key_matches_same_role_across_boards():
    a = dedupe_key("Acme Technologies Pvt Ltd", "Machine Learning Intern (Summer 2026)", "Bengaluru, Karnataka")
    b = dedupe_key("Acme", "Machine Learning Intern", "Bengaluru · India")
    assert a == b


@respx.mock
async def test_link_check_detects_closed_and_blocked_pages():
    async with httpx.AsyncClient() as c:
        respx.get("https://a.example/open").mock(return_value=httpx.Response(200, text="<h1>ML Intern</h1> Apply now"))
        respx.get("https://a.example/closed").mock(return_value=httpx.Response(200, text="Sorry, this job is no longer available."))
        respx.get("https://a.example/gone").mock(return_value=httpx.Response(404))
        respx.get("https://www.linkedin.com/jobs/view/9").mock(return_value=httpx.Response(999))
        assert await check_link(c, "https://a.example/open") == "ok"
        assert await check_link(c, "https://a.example/closed") == "dead"
        assert await check_link(c, "https://a.example/gone") == "dead"
        assert await check_link(c, "https://www.linkedin.com/jobs/view/9") == "unverified"
        # A live page whose framework bundles a "Job Not Found" template in its scripts is still open.
        respx.get("https://a.example/spa").mock(return_value=httpx.Response(200, text=(
            '<title>ML Intern at Acme</title><h1>ML Intern</h1>'
            '<script>self.__next_f.push(["h1",{"children":"Job Not Found"}])</script>')))
        assert await check_link(c, "https://a.example/spa") == "ok"


@respx.mock
async def test_jsearch_parses_publishers_apply_links_and_domain(monkeypatch):
    monkeypatch.setattr(settings, "jsearch_api_key", "k")
    route = respx.get("https://jsearch.p.rapidapi.com/search").mock(return_value=httpx.Response(200, json=jsearch_payload(jjob("j1", "Machine Learning Intern", "Acme AI"))))
    async with httpx.AsyncClient() as c:
        [p] = await JSearchSource().fetch(c, Preferences(), "internship jobs in India")
    req = route.calls[0].request
    assert req.headers["X-RapidAPI-Key"] == "k" and req.url.params["country"] == "in" and req.url.params["num_pages"] == "1"
    assert "page" not in req.url.params  # v5 pages with a cursor
    assert p.publisher == "LinkedIn" and p.company_domain == "acme.ai" and p.extra["entry_level"]
    assert {a["publisher"] for a in p.apply_links} == {"LinkedIn", "Acme Careers"} and any(a["direct"] for a in p.apply_links)
    assert JSearchSource().min_interval_minutes == 216  # 200 free requests spread over a month, for the whole service


@respx.mock
async def test_pipeline_with_jsearch_dedupes_and_drops_dead_links(authed, monkeypatch):
    monkeypatch.setattr(settings, "jsearch_api_key", "k")
    monkeypatch.setattr(settings, "verify_links", True)
    monkeypatch.setattr(settings, "demo_source", False)
    live = jjob("live", "Machine Learning Intern", "Acme AI")
    twin = jjob("twin", "Machine Learning Intern (Summer 2026)", "Acme AI Pvt Ltd", publisher="Naukri", link="https://www.naukri.com/job/123",
                options=[{"publisher": "Naukri", "apply_link": "https://www.naukri.com/job/123", "is_direct": False}])
    closed = jjob("closed", "Data Analyst Intern", "Beta Corp", link="https://beta.example/jobs/1", options=[], site="https://beta.example")
    respx.get("https://jsearch.p.rapidapi.com/search").mock(return_value=httpx.Response(200, json=jsearch_payload(live, twin, closed)))
    respx.get("https://acme.ai/careers/ml-intern").mock(return_value=httpx.Response(200, text="Machine Learning Intern — apply"))
    respx.get("https://www.naukri.com/job/123").mock(return_value=httpx.Response(200, text="Machine Learning Intern at Acme"))
    respx.get("https://beta.example/jobs/1").mock(return_value=httpx.Response(200, text="This position has been filled."))

    await _upload(authed)
    await authed.post("/api/runs")
    await _work()
    async with session_scope() as s:
        jobs = (await s.execute(select(Job).where(Job.source == "jsearch"))).scalars().all()
    assert len(jobs) == 1  # the closed listing was dropped; the Naukri twin merged into the LinkedIn one
    job = jobs[0]
    assert job.link_status == "ok" and job.publisher == "LinkedIn" and job.company_domain == "acme.ai"
    assert {a["publisher"] for a in job.apply_links} == {"LinkedIn", "Acme Careers", "Naukri"}
    item = (await authed.get("/api/matches")).json()["items"][0]["job"]
    assert item["publisher"] == "LinkedIn" and item["link_status"] == "ok" and len(item["apply_links"]) == 3


async def test_ingest_tick_wakes_the_user_once_and_empty_refreshes_are_pruned(authed):
    await _upload(authed)
    first = await ingest_tick()
    assert first["new"] > 0 and first["runs"] == 1  # new jobs close to the resume: the user's agents wake up
    await _work()
    runs = (await authed.get("/api/runs")).json()
    assert runs and runs[0]["trigger"] == "refresh" and runs[0]["stats"]["new_jobs"] > 0

    # The demo feed is listed again a minute later, but nothing in it is new: nobody is woken.
    again = await ingest_tick()
    assert again["new"] == 0 and again["runs"] == 0


def test_jsearch_accepts_v4_and_v5_shapes():
    from app.sources.providers import jsearch_jobs

    job = {"job_id": "1", "job_title": "ML Intern"}
    assert jsearch_jobs({"data": [job]}) == [job]
    assert jsearch_jobs({"data": {"cursor": "c", "jobs": [job]}}) == [job]
    assert jsearch_jobs({"data": {"cursor": "c", "results": [job]}}) == [job]
    assert jsearch_jobs({"status": "ERROR"}) == []


# Trimmed from a real JSearch v5 response (RapidAPI playground, "developer jobs in chicago").
V5_REAL = {
    "status": "OK",
    "parameters": {"query": "developer jobs in chicago", "date_posted": "all", "country": "us", "language": "en"},
    "data": {
        "jobs": [
            {
                "job_id": "PjUC9oZVlnm8rP7DAAAAAA==", "job_title": "Associate Application Developer AWS 2026 - FutureNow - Chicago",
                "employer_name": "IBM", "employer_website": None, "job_publisher": "LinkedIn",
                "job_employment_type": "Full-time", "job_employment_types": ["FULLTIME"],
                "job_apply_link": "https://www.linkedin.com/jobs/view/associate-application-developer-aws-2026-futurenow-chicago-at-ibm-4405599796",
                "job_apply_is_direct": False,
                "apply_options": [{"apply_link": "https://www.linkedin.com/jobs/view/associate-application-developer-aws-2026-futurenow-chicago-at-ibm-4405599796", "is_direct": False, "publisher": "LinkedIn"}],
                "job_description": "The Associate Application Developer at IBM is an entry-level role.", "job_is_remote": False,
                "job_posted_at_datetime_utc": "2026-04-28T00:00:00.000Z", "job_location": "Chicago, IL",
                "job_city": "Chicago", "job_state": "Illinois", "job_country": "US", "job_min_salary": None, "job_max_salary": None,
            },
            {
                "job_id": "aUxpjZGwAgf0g9DZAAAAAA==", "job_title": "Principal Developer - IT", "employer_name": "United Airlines",
                "employer_website": "https://www.united.com", "job_publisher": "United Airlines Jobs",
                "job_employment_type": "Full-time", "job_employment_types": ["FULLTIME"],
                "job_apply_link": "https://careers.united.com/us/en/job/WHQ00026134/Principal-Developer-IT", "job_apply_is_direct": False,
                "apply_options": [{"apply_link": "https://careers.united.com/us/en/job/WHQ00026134/Principal-Developer-IT", "is_direct": False, "publisher": "United Airlines Jobs"}],
                "job_description": "To request an accommodation, contact JobAccommodations@united.com", "job_is_remote": False,
                "job_posted_at_datetime_utc": "2026-04-30T00:00:00.000Z", "job_city": "Chicago", "job_state": "Illinois", "job_country": "US",
            },
            {
                "job_id": "swy2i9S8NQqQTR4hAAAAAA==", "job_title": "Mainframe Developer", "employer_name": "Cognizant",
                "employer_website": "https://www.cognizant.com", "job_publisher": "Indeed",
                "job_employment_type": "Full-time", "job_employment_types": ["FULLTIME"],
                "job_apply_link": "https://www.indeed.com/viewjob?jk=df97dc9d5b8837f6", "job_apply_is_direct": False,
                "apply_options": [{"apply_link": "https://www.indeed.com/viewjob?jk=df97dc9d5b8837f6", "is_direct": False, "publisher": "Indeed"}],
                "job_description": "Mainframe Development in COBOL Db2 JCL Python.", "job_is_remote": False,
                "job_posted_at_datetime_utc": "2026-04-24T00:00:00.000Z", "job_city": "Chicago", "job_state": "Illinois", "job_country": "US",
                "job_min_salary": 50000, "job_max_salary": 93500,
            },
        ],
        "cursor": "EowECswDQU1uMy15UVRNb21s",
    },
}


@respx.mock
async def test_jsearch_parses_real_v5_response(monkeypatch):
    monkeypatch.setattr(settings, "jsearch_api_key", "k")
    respx.get("https://jsearch.p.rapidapi.com/search").mock(return_value=httpx.Response(200, json=V5_REAL))
    async with httpx.AsyncClient() as c:
        ibm, united, cognizant = await JSearchSource().fetch(c, Preferences(), "developer jobs in chicago")
    assert (ibm.publisher, ibm.company, ibm.company_domain) == ("LinkedIn", "IBM", None)
    assert ibm.posted_at == datetime(2026, 4, 28, tzinfo=UTC) and ibm.location == "Chicago, Illinois, US"
    assert not ibm.extra["entry_level"]  # v5 says "Full-time", not an internship
    assert united.publisher == "United Airlines Jobs" and united.company_domain == "united.com"
    assert united.recruiter_email is None  # accommodation inboxes are not recruiters
    assert cognizant.publisher == "Indeed" and (cognizant.salary_min, cognizant.salary_max) == (50000, 93500)
    assert cognizant.apply_links == [{"publisher": "Indeed", "url": "https://www.indeed.com/viewjob?jk=df97dc9d5b8837f6", "direct": False}]


@respx.mock
async def test_jsearch_falls_back_when_gateway_moves_the_endpoint(monkeypatch):
    monkeypatch.setattr(settings, "jsearch_api_key", "k")
    monkeypatch.setattr(JSearchSource, "_path_ok", "/search")
    respx.get("https://jsearch.p.rapidapi.com/search").mock(return_value=httpx.Response(404, json={"message": "Endpoint '/search' does not exist"}))
    v2 = respx.get("https://jsearch.p.rapidapi.com/search-v2").mock(return_value=httpx.Response(200, json=V5_REAL))
    async with httpx.AsyncClient() as c:
        jobs = await JSearchSource().fetch(c, Preferences(), "developer jobs in chicago")
    assert len(jobs) == 3 and v2.called and JSearchSource._path_ok == "/search-v2"  # remembered for next time


def test_jsearch_queries_follow_the_resume():
    prefs = Preferences(locations=["India", "Remote"], tracks=["technical", "non_technical"], internships_only=True)
    qs = JSearchSource().queries(prefs, ["Python", "Machine Learning", "Pandas", "SQL", "FastAPI"])
    assert qs[0] == "machine learning intern in India"
    assert {"data science intern in India", "data analyst intern in India", "python developer intern in India"} <= set(qs)
    assert "business analyst intern in India" in qs  # non-technical track is on
    assert JSearchSource().queries(Preferences(tracks=["technical"], internships_only=False), []) == ["software developer fresher in India"]


@respx.mock
async def test_jsearch_small_indian_towns_pass_and_bulk_ads_collapse(monkeypatch):
    monkeypatch.setattr(settings, "jsearch_api_key", "k")
    towns = ["Nashik", "Maddur", "Kikkeri", "Byakod"]
    bulk = [dict(jjob(f"b{i}", "Entry-Level Jobs", "CareOff", city=t), job_state="Karnataka") for i, t in enumerate(towns)]
    one = jjob("ml", "Machine Learning Intern", "Acme AI", city="Nashik")
    respx.get("https://jsearch.p.rapidapi.com/search").mock(return_value=httpx.Response(200, json=jsearch_payload(one, *bulk)))
    async with httpx.AsyncClient() as c:
        posts = await JSearchSource().fetch(c, Preferences(), "machine learning intern in India")
    assert [p.title for p in posts] == ["Machine Learning Intern", "Entry-Level Jobs"]
    assert posts[0].location == "Nashik, Karnataka, India" and posts[1].location.endswith("(+3 more locations)")
    from app.sources.base import location_ok

    assert location_ok(posts[0], Preferences(locations=["India"]))


@respx.mock
async def test_adzuna_one_search_per_fetch_from_the_resume(monkeypatch):
    from app.sources.providers import AdzunaSource

    monkeypatch.setattr(settings, "adzuna_app_id", "id")
    monkeypatch.setattr(settings, "adzuna_app_key", "key")
    route = respx.get("https://api.adzuna.com/v1/api/jobs/in/search/1").mock(return_value=httpx.Response(200, json={"count": 1, "results": [{
        "id": 4711, "title": "Machine Learning Intern", "company": {"display_name": "Acme AI"}, "location": {"display_name": "Nashik, Maharashtra"},
        "description": LONG, "redirect_url": "https://www.adzuna.in/details/4711", "created": "2026-11-01T08:00:00Z",
    }]}))
    prefs = Preferences(locations=["India", "Remote"], internships_only=True)
    src = AdzunaSource()
    assert src.queries(prefs, ["Python", "Machine Learning"])[0] == "machine learning intern"
    async with httpx.AsyncClient() as c:
        [p] = await src.fetch(c, prefs, "machine learning intern")
    assert route.call_count == 1 and route.calls[0].request.url.params["what"] == "machine learning intern"
    assert p.publisher == "Adzuna" and p.location == "Nashik, Maharashtra, India" and p.apply_links[0]["url"].endswith("/4711")
    assert src.min_interval_minutes == 43  # 1,000 free requests a month, one per fetch
