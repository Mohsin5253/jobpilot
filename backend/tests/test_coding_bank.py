"""Every coding problem's tests are checked against a reference solution, with the same comparison the browser uses."""

import pytest

from app.services.coding_bank import BY_ID, PROBLEMS, pick_problems
from app.services.coding_solutions import REF, sample_solution


def same(a, b, mode):
    if mode == "float":
        if isinstance(a, list):
            return isinstance(b, list) and len(a) == len(b) and all(abs(x - y) <= 1e-3 for x, y in zip(a, b))
        return b is not None and abs(a - b) <= 1e-3
    return a == b


@pytest.mark.parametrize("p", PROBLEMS, ids=lambda p: p.id)
def test_reference_solution_passes_every_test(p):
    import copy

    fn = REF[p.id]
    for t in p.tests:
        got = fn(*copy.deepcopy(t["args"]))
        assert same(t["expected"], got, p.compare), (p.id, t, got)
    assert any(t["visible"] for t in p.tests) and any(not t["visible"] for t in p.tests)
    pub = p.public()
    assert set(pub["starter"]) == {"python", "javascript", "java", "cpp"} and pub["fn"]["python"] in pub["starter"]["python"]


def test_levels_and_lengths():
    intern30 = pick_problems("software", "intern", 30)
    assert [p.difficulty for p in intern30] == ["easy"]
    assert [p.difficulty for p in pick_problems("software", "intern", 45)] == ["easy", "medium"]
    assert [p.difficulty for p in pick_problems("software", "fresher", 60)] == ["medium", "hard"]
    assert all("data_science" in p.industries for p in pick_problems("data_science", "intern", 60))


def test_trending_skills_pick_matching_problems():
    ai = pick_problems("data_science", "fresher", 45, trending=["RAG", "Vector Databases"])
    assert ai[0].id in ("chunk_text", "top_k_retrieval")
    assert BY_ID["chunk_text"].trend


def test_every_problem_has_a_sample_solution_for_the_report():
    for p in PROBLEMS:
        src = sample_solution(p.id)
        assert src and src.startswith(f"def {p.py}("), p.id
