"""Campus v2, every case the spec lists: staff-only portal, staff verification, RLS scope by campus / department /
programme / batch, consent, achievements, capacity and waitlists, drill-down totals, rules as data across fields, and
no hardcoded engineering assumptions."""

import io
import re
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from app.campus import jobs as cjobs
from app.campus import otp
from app.campus.access import campus_session
from app.config import settings
from app.db import session_scope

ROOT = Path(__file__).resolve().parents[1]
CODES: dict[str, str] = {}


@pytest.fixture(autouse=True)
def mail(monkeypatch):
    async def send(email, subject, body):
        CODES[email.lower()] = re.search(r"\b(\d{6})\b", body).group(1)
        return True

    monkeypatch.setattr(otp, "send", send)
    monkeypatch.setattr(settings, "admin_emails", ["admin@jobpilot.example"])
    CODES.clear()


async def _user(client, email: str, name: str = "") -> dict:
    r = await client.post("/api/auth/register", json={"consent": True, "adult": True, "email": email, "password": "password123", "name": name or email.split("@")[0]})
    assert r.status_code == 201, r.text
    client.cookies.clear()
    return {"authorization": f"Bearer {r.json()['access_token']}"}


async def _call(client, method: str, url: str, h: dict, **kw):
    r = await client.request(method, url, headers=h, **kw)
    client.cookies.clear()
    return r


async def _staff_token(client, h: dict, email: str) -> dict:
    r = await _call(client, "POST", "/api/campus/staff-session/otp", h, json={})
    assert r.status_code == 200, r.text
    body = {"otp": CODES[email]} if r.json()["needed"] else {}
    r = await _call(client, "POST", "/api/campus/staff-session", h, json=body)
    assert r.status_code == 200, r.text
    return {**h, "x-staff-token": r.json()["staff_token"]}


class World:
    """A college with Computer + Mechanical departments, B.E. programmes, two Computer batches (2024, 2025), a TPO,
    and a roster of 6 students imported from CSV."""

    async def build(self, client, domain: str = "college.edu.in", name: str = "Test College of Engineering", admin: dict | None = None):
        self.client = client
        self.admin = admin or await _user(client, "admin@jobpilot.example")
        r = await _call(client, "POST", "/api/admin/campuses", self.admin, json={"name": name, "city": "Pune", "state": "Maharashtra", "allowed_email_domains": [domain]})
        assert r.status_code == 201, r.text
        self.campus_id = r.json()["id"]
        self.domain = domain
        self.tpo_email = f"tpo@{domain}"
        self.tpo_h = await _user(client, self.tpo_email, "Tpo")
        assert (await _call(client, "POST", f"/api/admin/campuses/{self.campus_id}/staff", self.admin, json={"email": self.tpo_email})).status_code == 200
        self.tpo = await _staff_token(client, self.tpo_h, self.tpo_email)
        await self.put("/api/campus/staff/settings", {"score_scale": {"type": "cgpa", "max": 10}, "student_id_label": "Roll no.", "pending_subjects_label": "ATKT"})
        be = next(d for d in (await self.get("/api/campus/staff/degrees?q=B.E.")) if d["abbreviation"] == "B.E.")
        assert (await _call(client, "PUT", "/api/campus/staff/degrees/offered", self.tpo, json={"degree_ids": [be["id"]]})).status_code == 200
        self.comp = (await self.post("/api/campus/staff/departments", {"name": "Computer Engineering"}))["id"]
        self.mech = (await self.post("/api/campus/staff/departments", {"name": "Mechanical Engineering"}))["id"]
        self.p_comp = (await self.post("/api/campus/staff/programs", {"department_id": self.comp, "degree_id": be["id"], "field_code": "0613", "duration_years": 4, "intake_per_year": 120}))["id"]
        self.p_mech = (await self.post("/api/campus/staff/programs", {"department_id": self.mech, "degree_id": be["id"], "field_code": "0715", "duration_years": 4, "intake_per_year": 60}))["id"]
        self.b24 = (await self.post("/api/campus/staff/batches", {"program_id": self.p_comp, "admission_year": 2024}))["id"]
        self.b25 = (await self.post("/api/campus/staff/batches", {"program_id": self.p_comp, "admission_year": 2025}))["id"]
        csv_text = (
            "Roll No,Name,Department,Degree,Admission Year,Semester,CGPA,ATKT,College Email\n"
            "C24-1,Asha Rao,Computer Engineering,B.E.,2024,5,8.4,0,asha@student.college.edu.in\n"
            "C24-2,Bilal Khan,Computer Engineering,B.E.,2024,5,6.1,2,bilal@student.college.edu.in\n"
            "C25-1,Chitra Iyer,Computer Engineering,B.E.,2025,3,9.0,0,chitra@student.college.edu.in\n"
            "M24-1,Dev Patil,Mechanical Engineering,B.E.,2024,5,7.5,0,dev@student.college.edu.in\n"
            "M24-2,Esha Nair,Mechanical Engineering,B.E.,2024,5,7.9,1,esha@student.college.edu.in\n"
            "X-1,,Computer Engineering,B.E.,2024,5,11,0,bad-email\n"
        )
        r = await _call(client, "POST", "/api/campus/staff/roster/import", self.tpo, files={"file": ("roster.csv", csv_text.encode(), "text/csv")})
        assert r.status_code == 202, r.text
        self.import_job = r.json()["job_id"]
        await cjobs.run_pending(10)
        return self

    async def get(self, url, h=None):
        r = await _call(self.client, "GET", url, h or self.tpo)
        assert r.status_code == 200, (url, r.status_code, r.text)
        return r.json()

    async def post(self, url, body, h=None):
        r = await _call(self.client, "POST", url, h or self.tpo, json=body)
        assert r.status_code in (200, 201, 202), (url, r.status_code, r.text)
        return r.json()

    async def put(self, url, body, h=None):
        r = await _call(self.client, "PUT", url, h or self.tpo, json=body)
        assert r.status_code == 200, (url, r.status_code, r.text)
        return r.json()

    async def staff(self, email: str, role: str, **scope) -> dict:
        """Join as staff (code + institutional email OTP), get approved by the TPO, open a staff session."""
        code = (await self.post("/api/campus/staff/staff-code", {"expires_in_days": 30}))["code"]
        h = await _user(self.client, email)
        r = await _call(self.client, "POST", "/api/campus/staff-join/start", h, json={"code": code, "email": email})
        assert r.status_code == 200, r.text
        r = await _call(self.client, "POST", "/api/campus/staff-join/verify", h, json={"otp": CODES[email], "role": role, **scope})
        assert r.status_code == 200, r.text
        m = next(x for x in await self.get("/api/campus/staff/members?status=pending") if x["email"] == email)
        await self.post(f"/api/campus/staff/members/{m['membership_id']}", {"action": "approve"})
        return await _staff_token(self.client, h, email)

    async def student(self, email: str, college_email: str, share: bool = True) -> dict:
        h = await _user(self.client, email, email.split("@")[0].title())
        if share:
            assert (await _call(self.client, "PUT", "/api/consents/college_share", h, json={"granted": True})).status_code == 200
        r = await _call(self.client, "POST", "/api/campus-profile/claim/start", h, json={"campus_id": self.campus_id, "college_email": college_email})
        assert r.status_code == 200
        r = await _call(self.client, "POST", "/api/campus-profile/claim/verify", h, json={"otp": CODES[college_email]})
        assert r.status_code == 200, r.text
        return h

    async def roster(self, sid: str) -> dict:
        async with session_scope() as s:
            row = (await s.execute(text("SELECT id FROM roster_students WHERE campus_id = :c AND student_id_at_institution = :s"), {"c": self.campus_id, "s": sid})).first()
        return str(row.id)


@pytest.fixture
async def world(client):
    return await World().build(client)


# ---------------------------------------- roster import ----------------------------------------


async def test_roster_import_creates_records_and_an_error_report(world):
    job = await world.get(f"/api/campus/staff/jobs/{world.import_job}")
    assert job["status"] == "done" and job["result"]["imported"] == 5 and job["error_count"] >= 2
    errs = (await world.client.get(f"/api/campus/staff/jobs/{world.import_job}/errors.csv", headers=world.tpo)).text
    assert "name is empty" in errs and "outside the college's scale" in errs and "not an email address" in errs
    page = await world.get("/api/campus/staff/students?limit=2")
    assert len(page["items"]) == 2 and page["next_cursor"]
    rest = await world.get(f"/api/campus/staff/students?limit=10&cursor={page['next_cursor']}")
    assert len(rest["items"]) == 3 and not {i["id"] for i in rest["items"]} & {i["id"] for i in page["items"]}  # keyset, no repeats
    async with session_scope() as s:  # imports create invites, never accounts
        assert (await s.execute(text("SELECT count(*) FROM roster_students WHERE claimed_user_id IS NOT NULL AND campus_id = :c"), {"c": world.campus_id})).scalar_one() == 0


# ---------------------------------------- the staff-only portal ----------------------------------------


async def test_a_student_gets_403_on_every_staff_endpoint(world):
    from app.main import app

    stu = await world.student("asha.s@gmail.com", "asha@student.college.edu.in")
    paths = {p: m for p, m in app.openapi()["paths"].items() if p.startswith("/api/campus/staff/")}
    assert len(paths) >= 25
    for path, methods in paths.items():
        url = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)
        for method in methods:
            r = await _call(world.client, method.upper(), url, stu, json={})
            assert r.status_code == 403, (method, path, r.status_code)
    r = await _call(world.client, "POST", "/api/campus/staff-session", stu, json={})
    assert r.status_code == 403
    forged = {**stu, "x-staff-token": world.tpo["x-staff-token"]}  # the TPO's token in a student's request
    assert (await _call(world.client, "GET", "/api/campus/staff/me", forged)).status_code == 403


async def test_staff_codes_need_an_institutional_email_and_lock_after_brute_force(world, client):
    code = (await world.post("/api/campus/staff/staff-code", {}))["code"]
    stu = await _user(client, "someone@gmail.com")
    r = await _call(client, "POST", "/api/campus/staff-join/start", stu, json={"code": code, "email": "someone@gmail.com"})
    assert r.status_code == 422 and "institutional" in r.json()["detail"]
    r = await _call(client, "POST", "/api/campus/staff-join/start", stu, json={"code": code, "email": "x@other-college.ac.in"})
    assert r.status_code == 422
    for _ in range(5):
        assert (await _call(client, "POST", "/api/campus/staff-join/start", stu, json={"code": "STAFF-WRNG-CODE-0000", "email": f"x@{world.domain}"})).status_code == 403
    r = await _call(client, "POST", "/api/campus/staff-join/start", stu, json={"code": code, "email": f"x@{world.domain}"})
    assert r.status_code == 429  # locked, even with the right code now


async def test_pending_staff_see_nothing(world, client):
    code = (await world.post("/api/campus/staff/staff-code", {}))["code"]
    h = await _user(client, f"newhod@{world.domain}")
    await _call(client, "POST", "/api/campus/staff-join/start", h, json={"code": code, "email": f"newhod@{world.domain}"})
    r = await _call(client, "POST", "/api/campus/staff-join/verify", h, json={"otp": CODES[f"newhod@{world.domain}"], "role": "hod", "department_ids": [world.comp]})
    assert r.status_code == 200 and r.json()["status"] == "pending"
    assert (await _call(client, "POST", "/api/campus/staff-session", h, json={})).status_code == 403
    me = (await _call(client, "GET", "/api/auth/me", h)).json()
    async with campus_session("none", uuid.UUID(me["id"]), [uuid.UUID(world.campus_id)]) as s:  # RLS alone, as a pending member
        assert (await s.execute(text("SELECT count(*) FROM roster_students"))).scalar_one() == 0


async def test_deactivated_staff_lose_their_session_at_once(world):
    hod = await world.staff(f"hod@{world.domain}", "hod", department_ids=[world.comp])
    assert (await _call(world.client, "GET", "/api/campus/staff/me", hod)).status_code == 200
    m = next(x for x in await world.get("/api/campus/staff/members?status=active") if x["email"] == f"hod@{world.domain}")
    await world.post(f"/api/campus/staff/members/{m['membership_id']}", {"action": "deactivate"})
    assert (await _call(world.client, "GET", "/api/campus/staff/me", hod)).status_code == 401


async def test_tpo_of_one_campus_reads_nothing_of_another(world, client):
    other = await World().build(client, domain="second.ac.in", name="Second College", admin=world.admin)
    r = await _call(client, "GET", f"/api/campus/staff/students/{await other.roster('C24-1')}", world.tpo)
    assert r.status_code == 404
    me = (await _call(client, "GET", "/api/auth/me", world.tpo_h)).json()
    async with campus_session("tpo", uuid.UUID(me["id"]), [uuid.UUID(world.campus_id)]) as s:
        assert (await s.execute(text("SELECT count(*) FROM roster_students WHERE campus_id = :b"), {"b": other.campus_id})).scalar_one() == 0
        assert (await s.execute(text("SELECT count(*) FROM roster_students"))).scalar_one() == 5


async def test_scope_by_role_department_programme_and_batch(world):
    hod = await world.staff(f"hod@{world.domain}", "hod", department_ids=[world.comp])
    fac = await world.staff(f"fac@{world.domain}", "faculty", batch_ids=[world.b25])
    tpo_ids = {i["student_id"] for i in (await world.get("/api/campus/staff/students?limit=50"))["items"]}
    hod_ids = {i["student_id"] for i in (await world.get("/api/campus/staff/students?limit=50", hod))["items"]}
    fac_ids = {i["student_id"] for i in (await world.get("/api/campus/staff/students?limit=50", fac))["items"]}
    assert tpo_ids == {"C24-1", "C24-2", "C25-1", "M24-1", "M24-2"}
    assert hod_ids == {"C24-1", "C24-2", "C25-1"}  # every programme and batch of their department, nothing else
    assert fac_ids == {"C25-1"}  # their 2025 batch only: not 2024, not Mechanical
    r = await _call(world.client, "GET", f"/api/campus/staff/students/{await world.roster('M24-1')}", fac)
    assert r.status_code == 404
    # A self-requested assignment is unusable until someone else approves it.
    await world.post("/api/campus/staff/assignments", {"department_id": world.mech}, fac)
    assert {i["student_id"] for i in (await world.get("/api/campus/staff/students?limit=50", fac))["items"]} == {"C25-1"}
    pending = await world.get("/api/campus/staff/assignments")
    assert any(a["department_id"] == world.mech for a in pending)


# ---------------------------------------- students: joining and achievements ----------------------------------------


async def test_self_selected_programme_stays_pending_until_confirmed(world, client):
    h = await _user(client, "newstudent@gmail.com")
    assert (await _call(client, "POST", "/api/campus-profile/join", h, json={"campus_id": world.campus_id, "program_id": world.p_mech, "admission_year": 2024})).json()["status"] == "pending"
    prof = (await _call(client, "GET", "/api/campus-profile", h)).json()
    assert prof["membership"]["status"] == "pending" and prof["membership"]["locked"] is False
    hod = await world.staff(f"mhod@{world.domain}", "hod", department_ids=[world.mech])
    req = await world.get("/api/campus/staff/students-pending", hod)
    assert len(req) == 1
    assert (await world.post(f"/api/campus/staff/students/memberships/{req[0]['membership_id']}", {"approve": True}, hod))["status"] == "active"


INTERN = {"kind": "internship", "organisation": "Nimbus Labs", "title": "Data intern", "mode": "remote", "start_date": "2025-05-01", "end_date": "2025-07-31", "description": "<b>Built</b> dashboards"}


async def test_students_add_only_internships_roles_and_awards(world):
    h = await world.student("asha.s@gmail.com", "asha@student.college.edu.in")
    for bad in ({"kind": "project", "title": "X"}, {**INTERN, "cgpa": 9.9}, {**INTERN, "status": "verified"}, {**INTERN, "branch": "CSE"}):
        r = await _call(world.client, "POST", "/api/campus-profile/achievements", h, json=bad)
        assert r.status_code == 400, bad
    r = await _call(world.client, "POST", "/api/campus-profile/achievements", h, json=INTERN)
    assert r.status_code == 201 and r.json()["status"] == "self_reported" and r.json()["description"] == "Built dashboards"  # HTML stripped
    assert (await _call(world.client, "POST", "/api/campus-profile/achievements", h, json=INTERN)).status_code == 409  # duplicate
    future = (date.today() + timedelta(days=10)).isoformat()
    assert (await _call(world.client, "POST", "/api/campus-profile/achievements", h, json={**INTERN, "title": "Later", "start_date": future})).status_code == 400
    assert (await _call(world.client, "POST", "/api/campus-profile/achievements", h, json={**INTERN, "title": "Backwards", "end_date": "2025-01-01"})).status_code == 400
    award = {"kind": "award", "title": "Smart India Hackathon", "organiser": "x"}
    assert (await _call(world.client, "POST", "/api/campus-profile/achievements", h, json=award)).status_code == 400  # unknown field + missing level
    ok = {"kind": "award", "title": "National Moot Court", "organisation": "NLU", "category": "moot_court", "level": "national", "position": "winner", "start_date": "2025-02-10"}
    assert (await _call(world.client, "POST", "/api/campus-profile/achievements", h, json=ok)).status_code == 201
    role = {"kind": "role", "organisation": "NSS unit", "title": "Volunteer lead", "start_date": "2024-08-01", "ongoing": True}
    assert (await _call(world.client, "POST", "/api/campus-profile/achievements", h, json=role)).status_code == 201


async def test_editing_others_entries_verification_and_reset(world):
    asha = await world.student("asha.s@gmail.com", "asha@student.college.edu.in")
    chitra = await world.student("chitra.s@gmail.com", "chitra@student.college.edu.in")
    a = (await _call(world.client, "POST", "/api/campus-profile/achievements", asha, json=INTERN)).json()
    url = f"/api/campus-profile/achievements/{a['campus_id']}/{a['id']}"
    assert (await _call(world.client, "PUT", url, chitra, json=INTERN)).status_code == 404  # someone else's entry: no rows
    assert (await _call(world.client, "DELETE", url, chitra)).status_code == 404
    mech_fac = await world.staff(f"mfac@{world.domain}", "faculty", department_ids=[world.mech])
    hod = await world.staff(f"hod@{world.domain}", "hod", department_ids=[world.comp])
    v = {"decision": "verified"}
    assert (await _call(world.client, "POST", f"/api/campus/staff/achievements/{a['id']}/verify", mech_fac, json=v)).status_code == 404  # other department
    assert (await _call(world.client, "POST", f"/api/campus/staff/achievements/{a['id']}/verify", hod, json=v)).status_code == 200
    mine = (await _call(world.client, "GET", "/api/campus-profile", asha)).json()["achievements"]
    assert mine[0]["status"] == "verified"
    r = await _call(world.client, "PUT", url, asha, json={**INTERN, "title": "Senior data intern"})
    assert r.status_code == 200 and r.json()["status"] == "self_reported"  # an edit resets verification
    rej = await _call(world.client, "POST", f"/api/campus/staff/achievements/{a['id']}/verify", hod, json={"decision": "rejected", "reason": "Offer letter doesn't match"})
    assert rej.status_code == 200
    mine = (await _call(world.client, "GET", "/api/campus-profile", asha)).json()["achievements"]
    assert mine[0]["status"] == "rejected" and mine[0]["reject_reason"] == "Offer letter doesn't match"
    bulk = await _call(world.client, "POST", "/api/campus/staff/achievements/bulk", hod, json={"ids": [a["id"]], "decision": "verified"})
    assert bulk.status_code == 422  # bulk needs an explicit confirm


async def test_without_consent_staff_see_only_counts(world):
    quiet = await world.student("bilal.s@gmail.com", "bilal@student.college.edu.in", share=False)
    await _call(world.client, "POST", "/api/campus-profile/achievements", quiet, json=INTERN)
    queue = await world.get("/api/campus/staff/achievements")
    assert queue["items"] == []
    detail = await world.get(f"/api/campus/staff/students/{await world.roster('C24-2')}")
    assert detail["achievements"] == [] and detail["note"] and detail["record"]["name"] == "Bilal Khan"  # the college record stays visible
    await cjobs.rebuild_rollups(uuid.UUID(world.campus_id))
    dash = await world.get("/api/campus/staff/dashboard")
    assert dash["metrics"]["internship_all"] == 1  # counted
    assert (await _call(world.client, "PUT", "/api/consents/college_share", quiet, json={"granted": True})).status_code == 200
    assert len((await world.get("/api/campus/staff/achievements"))["items"]) == 1  # with consent: by name


def _pdf(text_: str) -> bytes:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    y = 800
    for line in text_.split("\n"):
        c.drawString(40, y, line)
        y -= 16
    c.save()
    return buf.getvalue()


async def test_proof_uploads_and_fee_asking_offer_letters(world):
    h = await world.student("asha.s@gmail.com", "asha@student.college.edu.in")
    a = (await _call(world.client, "POST", "/api/campus-profile/achievements", h, json=INTERN)).json()
    url = f"/api/campus-profile/achievements/{a['campus_id']}/{a['id']}/proof"
    big = b"%PDF-1.4\n" + b"0" * (5 * 1024 * 1024 + 10)
    assert (await _call(world.client, "POST", url, h, files={"file": ("x.pdf", big, "application/pdf")})).status_code == 422
    assert (await _call(world.client, "POST", url, h, files={"file": ("x.exe", b"MZ\x90\x00binary", "application/pdf")})).status_code == 422
    js = b"%PDF-1.4\n1 0 obj << /OpenAction << /S /JavaScript /JS (app.alert(1)) >> >> endobj\n%%EOF"
    assert (await _call(world.client, "POST", url, h, files={"file": ("x.pdf", js, "application/pdf")})).status_code == 422
    letter = _pdf("Offer letter - Global Solutions Pvt Ltd\nCongratulations on your selection as Data Intern.\nPay a refundable registration fee of Rs 1999 to confirm.\nContact hr.globalsolutions@gmail.com")
    r = await _call(world.client, "POST", url, h, files={"file": ("offer.pdf", letter, "application/pdf")})
    assert r.status_code == 200 and r.json()["flags"] and "1930" in r.json()["warning"]
    staff_view = (await world.get("/api/campus/staff/achievements"))["items"][0]
    assert staff_view["verifier_flags"] and staff_view["has_proof"]


async def test_images_lose_exif_and_gps():
    from PIL import Image

    from app.campus.storage import clean

    img = Image.new("RGB", (40, 40), "red")
    exif = Image.Exif()
    exif[0x8825] = {2: (18.0, 31.0, 0.0)}  # GPSInfo
    exif[0x010F] = "PhoneMaker"
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif.tobytes())
    data, mime = clean(buf.getvalue())
    assert mime == "image/jpeg" and not Image.open(io.BytesIO(data)).getexif()


# ---------------------------------------- structure: capacity, drill-down ----------------------------------------


async def test_capacity_children_never_exceed_parents_and_history_is_kept(world):
    await world.put("/api/campus/staff/capacity", {"level": "campus", "capacity": 100})
    r = await _call(world.client, "PUT", "/api/campus/staff/capacity", world.tpo, json={"level": "department", "ref_id": world.comp, "capacity": 150})
    assert r.status_code == 422 and "college total" in str(r.json())
    await world.put("/api/campus/staff/capacity", {"level": "program", "ref_id": world.p_comp, "capacity": 4})
    r = await _call(world.client, "PUT", "/api/campus/staff/capacity", world.tpo, json={"level": "batch", "ref_id": world.b24, "capacity": 5})
    assert r.status_code == 422  # a batch can't exceed its programme
    async with session_scope() as s:
        hist = (await s.execute(text("SELECT count(*) FROM capacity_history WHERE campus_id = :c"), {"c": world.campus_id})).scalar_one()
    assert hist == 2
    # Full programme: the next student waits on a list (and the TPO is told); nobody is silently blocked.
    await cjobs.rebuild_rollups(uuid.UUID(world.campus_id))
    await world.put("/api/campus/staff/capacity", {"level": "program", "ref_id": world.p_comp, "capacity": 3})
    h = await _user(world.client, "late@gmail.com")
    await _call(world.client, "POST", "/api/campus-profile/join", h, json={"campus_id": world.campus_id, "program_id": world.p_comp, "admission_year": 2025})
    req = await world.get("/api/campus/staff/students-pending")
    assert (await world.post(f"/api/campus/staff/students/memberships/{req[0]['membership_id']}", {"approve": True}))["status"] == "waitlisted"


async def test_drill_down_totals_add_up(world):
    await world.student("asha.s@gmail.com", "asha@student.college.edu.in")
    await cjobs.rebuild_rollups(uuid.UUID(world.campus_id))
    top = await world.get("/api/campus/staff/dashboard")
    assert top["metrics"]["students"] == 5 and top["updated_at"]
    depts = [c for c in top["children"] if c["level"] == "department"]
    assert sum(c["metrics"].get("students", 0) for c in depts) == top["metrics"]["students"]
    comp = await world.get(f"/api/campus/staff/dashboard?level=department&ref_id={world.comp}")
    assert sum(c["metrics"].get("students", 0) for c in comp["children"]) == comp["metrics"]["students"] == 3
    prog = await world.get(f"/api/campus/staff/dashboard?level=program&ref_id={world.p_comp}")
    assert sum(c["metrics"].get("students", 0) for c in prog["children"]) == prog["metrics"]["students"]
    hod = await world.staff(f"mhod@{world.domain}", "hod", department_ids=[world.mech])
    assert (await _call(world.client, "GET", f"/api/campus/staff/dashboard?level=department&ref_id={world.comp}", hod)).status_code == 403


async def test_exports_stay_in_scope_and_are_logged(world):
    fac = await world.staff(f"fac@{world.domain}", "faculty", batch_ids=[world.b25])
    csv_ = (await world.client.get("/api/campus/staff/export.csv", headers=fac)).text
    world.client.cookies.clear()
    assert "C25-1" in csv_ and "C24-1" not in csv_ and "M24-1" not in csv_
    log = await world.get("/api/campus/staff/audit")
    assert {"export", "login", "staff_approve"} <= {e["action"] for e in log}


# ---------------------------------------- every field and degree ----------------------------------------

COLLEGES = [  # (department, degree abbreviation, ISCED field, scale, pending label, roster score, drive rule)
    ("Computer Engineering", "B.Tech.", "0613", {"type": "cgpa", "max": 10}, "KT", 8.1, {"type": "score_gte", "value": 7}),
    ("Medicine", "M.B.B.S.", "0912", {"type": "percentage", "max": 100}, None, 68, {"type": "score_gte", "value": 60}),
    ("Law", "B.A. L.L.B.", "0421", {"type": "cgpa", "max": 7}, "Supplementary", 5.2, {"type": "score_gte", "value": 4.5}),
    ("Commerce", "B.Com.", "0411", {"type": "percentage", "max": 100}, "ATKT", 72, {"type": "score_gte", "value": 75}),
    ("History", "B.A.", "0222", {"type": "division", "max": None, "labels": ["First", "Second", "Third"]}, None, None, {"type": "field_in", "values": ["022"]}),
    ("Nursing", "B.Sc.(Nursing)", "0913", {"type": "percentage", "max": 100}, None, 61, {"type": "custom_yes", "key": "nursing_registration"}),
    ("Design", "B.Des.", "0212", {"type": "gpa", "max": 4}, "Resit", 3.4, {"type": "score_gte", "value": 3.0}),
]


@pytest.mark.parametrize("dept,degree,field,scale,pending_label,score,rule", COLLEGES)
async def test_campus_mode_works_for_every_field(client, dept, degree, field, scale, pending_label, score, rule):
    w = World()
    w.client = client
    w.admin = await _user(client, "admin@jobpilot.example")
    w.campus_id = (await _call(client, "POST", "/api/admin/campuses", w.admin, json={"name": f"{dept} College", "allowed_email_domains": ["inst.ac.in"]})).json()["id"]
    h = await _user(client, "tpo@inst.ac.in")
    await _call(client, "POST", f"/api/admin/campuses/{w.campus_id}/staff", w.admin, json={"email": "tpo@inst.ac.in"})
    w.tpo = await _staff_token(client, h, "tpo@inst.ac.in")
    sc = {k: v for k, v in scale.items() if k != "labels" or v}
    if sc["type"] == "division":
        sc["max"] = 1
    await w.put("/api/campus/staff/settings", {"score_scale": sc, "pending_subjects_label": pending_label or "", "student_id_label": "Registration no.",
                                               "custom_fields": [{"key": "nursing_registration", "label": "Valid nursing registration", "type": "yes_no"}]})
    deg = next(d for d in await w.get(f"/api/campus/staff/degrees?q={degree}") if d["abbreviation"] == degree)
    await w.put("/api/campus/staff/degrees/offered", {"degree_ids": [deg["id"]]})
    dep = (await w.post("/api/campus/staff/departments", {"name": dept}))["id"]
    await w.post("/api/campus/staff/programs", {"department_id": dep, "degree_id": deg["id"], "field_code": field})
    rows = "Registration No,Name,Department,Degree,Admission Year,Score,nursing_registration\n"
    rows += f"R1,Student One,{dept},{degree},2023,{'' if score is None else score},yes\nR2,Student Two,{dept},{degree},2023,,no\n"
    job = (await w.post("/api/campus/staff/roster/import", None) if False else (await _call(client, "POST", "/api/campus/staff/roster/import", w.tpo, files={"file": ("r.csv", rows.encode(), "text/csv")})).json())["job_id"]
    await cjobs.run_pending(5)
    assert (await w.get(f"/api/campus/staff/jobs/{job}"))["result"]["imported"] == 2
    drive = await w.post("/api/campus/staff/drives", {"company": "Acme", "role": "Graduate trainee", "rules": [rule], "rounds": [{"name": "Interview", "type": "subject_interview"}]})
    await cjobs.run_pending(5)
    drives = await w.get("/api/campus/staff/drives")
    eligible = next(d for d in drives if d["id"] == drive["id"])["eligible_in_scope"]
    expected = {"score_gte": 1 if score is not None and score >= rule.get("value", 0) else 0, "field_in": 2, "custom_yes": 1}[rule["type"]]
    assert eligible == expected, (dept, eligible)
    me = await w.get("/api/campus/staff/me")
    assert me["campus"]["score_scale"]["type"] == sc["type"] and me["campus"]["student_id_label"] == "Registration no."


async def test_a_foreign_university_with_its_own_degree_and_gpa():
    from app.campus.rules import Record, evaluate, validate

    rules = validate([{"type": "level_in", "values": [7]}, {"type": "score_gte", "value": 3.3}, {"type": "graduation_year_in", "values": [2026]}])
    assert evaluate(rules, Record(isced_level=7, score=3.6, graduation_year=2026)) == (True, [])
    ok, failed = evaluate(rules, Record(isced_level=6, score=3.6, graduation_year=2026))
    assert not ok and failed == ["r1"]
    assert evaluate(rules, Record(isced_level=7, score=None, graduation_year=2026))[1] == ["r2"]  # unknown never silently passes
    with pytest.raises(Exception):
        validate([{"type": "gender_in", "values": ["F"]}])  # only when the campus explicitly allows it


def test_no_hardcoded_engineering_assumptions_in_campus_code():
    """Branch names, "CGPA out of 10" and backlog-only wording may not appear in campus code (labels and scales are
    data). The v1 rule converter is the one allowed place that reads the old keys."""
    files = [*(ROOT / "app" / "campus").glob("*.py"), ROOT / "app" / "api" / "routes" / "campus_staff.py", ROOT / "app" / "api" / "routes" / "campus_profile.py",
             ROOT / "app" / "services" / "campus_v2.py"]
    frontend = ROOT.parent / "frontend"
    files += [p for p in (frontend / "app" / "(app)" / "campus").rglob("*.tsx")] + [p for p in (frontend / "app" / "(app)" / "campus-profile").rglob("*.tsx")]
    files += [p for p in (frontend / "components" / "campus").rglob("*.tsx")]
    allowed = {"rules.py", "taxonomy.py"}
    bad = []
    for f in files:
        if f.name in allowed or not f.exists():
            continue
        src = f.read_text()
        for pat in (r"\b(CSE|ECE|EEE|MECH|CIVIL|AIDS|AIML)\b", r"(?i)cgpa\s*/\s*10|out of 10\b", r"\bB\.?Tech\b", r"\bmax_backlogs\b", r"\bmin_cgpa\b"):
            for m in re.finditer(pat, src):
                line = src[: m.start()].count("\n") + 1
                bad.append(f"{f.relative_to(ROOT.parent)}:{line}: {m.group(0)}")
    assert not bad, bad


# ---------------------------------------- branches and the 20-lakh college limit ----------------------------------------


async def test_one_college_with_an_engineering_and_a_law_branch(world, client):
    assert (await _call(client, "POST", "/api/campus/staff/branches", world.tpo, json={"branch": "Law"})).status_code == 409  # name this branch first
    assert (await world.put("/api/campus/staff/branch-name", {"branch": "Engineering"}))["name"].endswith("— Engineering")
    law = await world.post("/api/campus/staff/branches", {"branch": "Law"})
    assert law["name"] == "Test College of Engineering — Law"
    assert (await _call(client, "POST", "/api/campus/staff/branches", world.tpo, json={"branch": "law"})).status_code == 409  # no duplicates
    branches = await world.get("/api/campus/staff/branches")
    assert {b["branch"] for b in branches} == {"Engineering", "Law"} and all(b["limit"] == 2_000_000 for b in branches)
    # The TPO switches to the Law branch: its own staff session, its own (empty) students, its own fields.
    mine = (await _call(client, "GET", "/api/campus/my-staff-campuses", world.tpo_h)).json()
    assert len(mine) == 2
    r = await _call(client, "POST", "/api/campus/staff-session/otp", world.tpo_h, json={"campus_id": law["id"]})
    assert r.json()["needed"]
    r = await _call(client, "POST", "/api/campus/staff-session", world.tpo_h, json={"campus_id": law["id"], "otp": CODES[world.tpo_email]})
    law_tpo = {**world.tpo_h, "x-staff-token": r.json()["staff_token"]}
    me = (await _call(client, "GET", "/api/campus/staff/me", law_tpo)).json()
    assert me["campus"]["branch"] == "Law" and me["campus"]["college"] == "Test College of Engineering"
    assert (await _call(client, "GET", "/api/campus/staff/students?limit=50", law_tpo)).json()["items"] == []  # engineering students stay separate
    llb = next(d for d in (await _call(client, "GET", "/api/campus/staff/degrees?q=L.L.B.", law_tpo)).json() if d["abbreviation"] == "L.L.B.")
    assert (await _call(client, "PUT", "/api/campus/staff/degrees/offered", law_tpo, json={"degree_ids": [llb["id"]]})).status_code == 200
    # Students find both branches by the college's name (once JobPilot has reviewed a college added by hand).
    stu = await _user(client, "lawstudent@gmail.com")
    assert (await _call(client, "GET", "/api/campus-profile/colleges?q=Test College", stu)).json() == []
    assert (await _call(client, "POST", f"/api/admin/campuses/{world.campus_id}/approve", world.admin)).json()["approved"] == 2
    found = (await _call(client, "GET", "/api/campus-profile/colleges?q=Test College", stu)).json()
    assert {f["name"] for f in found} == {"Test College of Engineering — Engineering", "Test College of Engineering — Law"}


async def test_each_college_or_branch_holds_up_to_20_lakh_students(world):
    assert (await _call(world.client, "PUT", "/api/campus/staff/capacity", world.tpo, json={"level": "campus", "capacity": 2_500_000})).status_code == 422
    await world.put("/api/campus/staff/capacity", {"level": "campus", "capacity": 2_000_000})
    tree = await world.get("/api/campus/staff/capacity")
    assert tree["capacity"] == 2_000_000


# ---------------------------------------- the Department plan ----------------------------------------


async def _register_department(client, admin: dict, email: str, department: str, college: str = "Sunrise Institute of Technology", branch: str = "Engineering") -> tuple[dict, dict]:
    h = await _user(client, email)
    r = await _call(client, "POST", "/api/campus/department-requests/start", h, json={"college_name": college, "branch": branch, "department_name": department, "city": "Nagpur", "state": "Maharashtra", "email": email})
    assert r.status_code == 200, r.text
    r = await _call(client, "POST", "/api/campus/department-requests/verify", h, json={"otp": CODES[email]})
    assert r.status_code == 200 and r.json()["status"] == "pending", r.text
    req = next(x for x in (await _call(client, "GET", "/api/admin/campuses/department-requests", admin)).json() if x["email"] == email)
    r = await _call(client, "POST", f"/api/admin/campuses/department-requests/{req['id']}", admin, json={"approve": True})
    assert r.status_code == 200, r.text
    return h, r.json()


async def test_a_department_registers_itself_and_is_live_after_verification(client):
    admin = await _user(client, "admin@jobpilot.example")
    h = await _user(client, "hod.cs@sunrise.ac.in")
    body = {"college_name": "Sunrise Institute of Technology", "branch": "Engineering", "department_name": "Computer Science", "email": "hod.cs@gmail.com"}
    assert (await _call(client, "POST", "/api/campus/department-requests/start", h, json=body)).status_code == 422  # personal email
    body["email"] = "hod.cs@sunrise.ac.in"
    assert (await _call(client, "POST", "/api/campus/department-requests/start", h, json=body)).status_code == 200
    assert (await _call(client, "POST", "/api/campus/department-requests/verify", h, json={"otp": "000000" if CODES["hod.cs@sunrise.ac.in"] != "000000" else "111111"})).status_code == 422
    r = await _call(client, "POST", "/api/campus/department-requests/verify", h, json={"otp": CODES["hod.cs@sunrise.ac.in"]})
    assert r.json()["status"] == "pending"
    # Pending: no portal access yet, and only JobPilot admins see the queue.
    assert (await _call(client, "POST", "/api/campus/staff-session/otp", h, json={})).status_code in (403, 404)
    assert (await _call(client, "GET", "/api/admin/campuses/department-requests", h)).status_code == 403
    mine = (await _call(client, "GET", "/api/campus/department-requests/mine", h)).json()
    assert [m["status"] for m in mine] == ["pending"]
    queue = (await _call(client, "GET", "/api/admin/campuses/department-requests", admin)).json()
    req = next(x for x in queue if x["email"] == "hod.cs@sunrise.ac.in")
    assert req["existing_campus"] is None and req["department_name"] == "Computer Science"
    assert (await _call(client, "POST", f"/api/admin/campuses/department-requests/{req['id']}", admin, json={"approve": False})).status_code == 422  # a rejection needs a reason
    ok = (await _call(client, "POST", f"/api/admin/campuses/department-requests/{req['id']}", admin, json={"approve": True})).json()
    assert ok["plan"] == "department"
    hod = await _staff_token(client, h, "hod.cs@sunrise.ac.in")
    me = (await _call(client, "GET", "/api/campus/staff/me", hod)).json()
    assert me["role"] == "hod" and me["lead"] and not me["whole_campus"] and me["plan"] == "department"
    assert me["scope"]["departments"] == [{"id": ok["department_id"], "name": "Computer Science", "plan_limit": 300}]
    assert me["campus"]["name"] == "Sunrise Institute of Technology — Engineering"
    # 300 seats per department; the HOD can't size the whole college.
    cap = lambda b: _call(client, "PUT", "/api/campus/staff/capacity", hod, json=b)  # noqa: E731
    assert (await cap({"level": "department", "ref_id": ok["department_id"], "capacity": 301})).status_code == 422
    assert (await cap({"level": "department", "ref_id": ok["department_id"], "capacity": 300})).status_code == 200
    assert (await cap({"level": "campus", "capacity": 5000})).status_code == 403
    # Registering the same department twice is refused.
    again = await _user(client, "someone@sunrise.ac.in")
    assert (await _call(client, "POST", "/api/campus/department-requests/start", again, json=body | {"email": "someone@sunrise.ac.in"})).status_code == 409


async def test_departments_of_one_college_share_a_campus_and_stay_apart(client):
    admin = await _user(client, "admin@jobpilot.example")
    cs_h, cs = await _register_department(client, admin, "hod.cs@sunrise.ac.in", "Computer Science")
    ecs_h, ecs = await _register_department(client, admin, "hod.ecs@sunrise.ac.in", "Electronics and Computer Science")
    assert cs["campus_id"] == ecs["campus_id"] and cs["department_id"] != ecs["department_id"]
    hod_cs = await _staff_token(client, cs_h, "hod.cs@sunrise.ac.in")
    hod_ecs = await _staff_token(client, ecs_h, "hod.ecs@sunrise.ac.in")
    # Each HOD sets up their own department: degrees, programmes, batches. Not the other's.
    be = next(d for d in (await _call(client, "GET", "/api/campus/staff/degrees?q=B.E.", hod_cs)).json() if d["abbreviation"] == "B.E.")
    assert (await _call(client, "PUT", "/api/campus/staff/degrees/offered", hod_cs, json={"degree_ids": [be["id"]]})).status_code == 200
    prog = {"degree_id": be["id"], "field_code": "0613", "duration_years": 4, "intake_per_year": 60}
    assert (await _call(client, "POST", "/api/campus/staff/programs", hod_cs, json=prog | {"department_id": ecs["department_id"]})).status_code in (403, 404)
    p_cs = (await _call(client, "POST", "/api/campus/staff/programs", hod_cs, json=prog | {"department_id": cs["department_id"]})).json()["id"]
    b_cs = (await _call(client, "POST", "/api/campus/staff/batches", hod_cs, json={"program_id": p_cs, "admission_year": 2024})).json()["id"]
    assert (await _call(client, "PUT", "/api/campus/staff/capacity", hod_ecs, json={"level": "department", "ref_id": cs["department_id"], "capacity": 100})).status_code == 403
    # Roster: an HOD imports their own department; another department's rows are errors.
    csv_text = (
        "Roll No,Name,Department,Degree,Admission Year,College Email\n"
        "CS-1,Asha Rao,Computer Science,B.E.,2024,asha@student.sunrise.ac.in\n"
        "CS-2,Bilal Khan,Computer Science,B.E.,2024,bilal@student.sunrise.ac.in\n"
        "CS-3,Chitra Iyer,Computer Science,B.E.,2024,chitra@student.sunrise.ac.in\n"
        "E-1,Dev Patil,Electronics and Computer Science,,2024,dev@student.sunrise.ac.in\n"
    )
    r = await _call(client, "POST", "/api/campus/staff/roster/import", hod_cs, files={"file": ("roster.csv", csv_text.encode(), "text/csv")})
    assert r.status_code == 202, r.text
    await cjobs.run_pending(10)
    job = (await _call(client, "GET", f"/api/campus/staff/jobs/{r.json()['job_id']}", hod_cs)).json()
    assert job["result"]["imported"] == 3 and job["error_count"] == 1
    assert (await _call(client, "GET", "/api/campus/staff/students?limit=50", hod_ecs)).json()["items"] == []
    assert len((await _call(client, "GET", "/api/campus/staff/students?limit=50", hod_cs)).json()["items"]) == 3
    # The department's own staff code: faculty join this department only, and its HOD approves them.
    code = (await _call(client, "POST", "/api/campus/staff/staff-code", hod_cs, json={"expires_in_days": 30})).json()
    assert code["department_id"] == cs["department_id"]
    other = await _user(client, "prof2@sunrise.ac.in")
    await _call(client, "POST", "/api/campus/staff-join/start", other, json={"code": code["code"], "email": "prof2@sunrise.ac.in"})
    r = await _call(client, "POST", "/api/campus/staff-join/verify", other, json={"otp": CODES["prof2@sunrise.ac.in"], "role": "tpo"})
    assert r.status_code in (403, 422)  # a department code never makes a TPO
    fac = await _user(client, "prof@sunrise.ac.in")
    start = (await _call(client, "POST", "/api/campus/staff-join/start", fac, json={"code": code["code"], "email": "prof@sunrise.ac.in"})).json()
    assert [d["name"] for d in start["departments"]] == ["Computer Science"] and start["campus"].endswith("· Computer Science")
    r = await _call(client, "POST", "/api/campus/staff-join/verify", fac, json={"otp": CODES["prof@sunrise.ac.in"], "role": "faculty", "batch_ids": [b_cs]})
    assert r.status_code == 200, r.text
    assert (await _call(client, "GET", "/api/campus/staff/members?status=pending", hod_ecs)).json() == []  # not their department
    m = next(x for x in (await _call(client, "GET", "/api/campus/staff/members?status=pending", hod_cs)).json() if x["email"] == "prof@sunrise.ac.in")
    assert (await _call(client, "POST", f"/api/campus/staff/members/{m['membership_id']}", hod_ecs, json={"action": "approve"})).status_code == 403
    assert (await _call(client, "POST", f"/api/campus/staff/members/{m['membership_id']}", hod_cs, json={"action": "approve", "role": "tpo"})).status_code == 403  # no promotions to TPO
    assert (await _call(client, "POST", f"/api/campus/staff/members/{m['membership_id']}", hod_cs, json={"action": "approve"})).status_code == 200
    prof = await _staff_token(client, fac, "prof@sunrise.ac.in")
    assert len((await _call(client, "GET", "/api/campus/staff/students?limit=50", prof)).json()["items"]) == 3  # their Computer Science batch
    # Seats: when the department is full, the next student waits (never a silent block). Exact count, not the rollup.
    async with session_scope() as s:
        await s.execute(text("UPDATE departments SET plan_limit = 2 WHERE id = :d"), {"d": cs["department_id"]})
    statuses = []
    for name in ("asha", "bilal", "chitra"):
        stu = await _user(client, f"{name}@gmail.com")
        mail = f"{name}@student.sunrise.ac.in"
        assert (await _call(client, "POST", "/api/campus-profile/claim/start", stu, json={"campus_id": cs["campus_id"], "college_email": mail})).status_code == 200
        statuses.append((await _call(client, "POST", "/api/campus-profile/claim/verify", stu, json={"otp": CODES[mail]})).json()["status"])
    assert statuses == ["active", "active", "waitlisted"]
