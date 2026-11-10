import json
from pathlib import Path

from app.agents.guard import check_bullet, check_freeform, resume_skillset
from app.resume_parser import heuristic_parse
from app.skills import extract_skills, skill_overlap

SAMPLE = Path(__file__).resolve().parents[1] / "evals" / "data" / "sample_resume.md"


def test_extract_skills_aliases_and_boundaries():
    found = extract_skills("Built ML models with sklearn and PyTorch, served via FastAPI in Docker on AWS; html")
    assert {"Machine Learning", "scikit-learn", "PyTorch", "FastAPI", "Docker", "AWS", "HTML/CSS"} <= set(found)
    # "ml" inside "html" and lowercase "go" must not count
    assert "Go" not in extract_skills("go to the html page")
    assert extract_skills("C++ and C#") == ["C++", "C#"]


def test_skill_overlap():
    strengths, gaps, cov = skill_overlap(["Python", "SQL"], ["Python", "Docker"])
    assert strengths == ["Python"] and gaps == ["Docker"] and cov == 50.0


def test_heuristic_parse_sample_resume():
    resume = heuristic_parse(SAMPLE.read_text())
    assert resume.name == "Aarav Mehta"
    assert resume.email == "aarav.mehta@example.com"
    assert len(resume.experience) == 1 and len(resume.experience[0].bullets) == 3
    assert [p.name for p in resume.projects] == ["Movie Recommender", "Sales Forecasting"]
    assert len(resume.bullet_index()) == 7


def test_guard_cases():
    text = SAMPLE.read_text()
    resume = heuristic_parse(text)
    skills = resume_skillset(resume, text)
    cases = json.loads((SAMPLE.parent / "guard_cases.json").read_text())
    for c in cases:
        verdict = check_bullet(c["rewritten"], c["context"], skills)
        assert verdict.ok == (c["expect"] == "ok"), c["why"]


def test_freeform_guard_flags_unknown_tools():
    assert check_freeform("I have shipped Kubernetes clusters", {"Python"}) == ["Kubernetes"]
    assert check_freeform("I love machine learning", {"Python"}) == []
