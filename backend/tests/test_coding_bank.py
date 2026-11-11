"""Every coding problem's tests are checked against a reference solution, with the same comparison the browser uses."""

import math
from collections import Counter, defaultdict, deque

import pytest

from app.services.coding_bank import BY_ID, PROBLEMS, pick_problems


def two_sum(nums, target):
    seen = {}
    for i, n in enumerate(nums):
        if target - n in seen:
            return [seen[target - n], i]
        seen[n] = i


def is_valid(s):
    st, pair = [], {")": "(", "]": "[", "}": "{"}
    for ch in s:
        if ch in pair:
            if not st or st.pop() != pair[ch]:
                return False
        else:
            st.append(ch)
    return not st


def longest_unique(s):
    last, start, best = {}, 0, 0
    for i, ch in enumerate(s):
        if last.get(ch, -1) >= start:
            start = last[ch] + 1
        last[ch] = i
        best = max(best, i - start + 1)
    return best


def merge(intervals):
    out = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def top_k_frequent(nums, k):
    c = Counter(nums)
    return sorted(c, key=lambda x: (-c[x], x))[:k]


def num_islands(grid):
    g = [row[:] for row in grid]
    n = 0
    for r in range(len(g)):
        for c in range(len(g[0])):
            if g[r][c] == "1":
                n += 1
                q = deque([(r, c)])
                g[r][c] = "0"
                while q:
                    y, x = q.popleft()
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        yy, xx = y + dy, x + dx
                        if 0 <= yy < len(g) and 0 <= xx < len(g[0]) and g[yy][xx] == "1":
                            g[yy][xx] = "0"
                            q.append((yy, xx))
    return n


def coin_change(coins, amount):
    dp = [0] + [math.inf] * amount
    for a in range(1, amount + 1):
        for c in coins:
            if c <= a:
                dp[a] = min(dp[a], dp[a - c] + 1)
    return -1 if dp[amount] == math.inf else dp[amount]


def group_anagrams(words):
    g = defaultdict(list)
    for w in words:
        g["".join(sorted(w))].append(w)
    return sorted(sorted(v) for v in g.values())


def allow_requests(requests, limit, window):
    q = defaultdict(deque)
    out = []
    for t, u in requests:
        while q[u] and q[u][0] <= t - window:
            q[u].popleft()
        ok = len(q[u]) < limit
        if ok:
            q[u].append(t)
        out.append(ok)
    return out


def prf(y_true, y_pred):
    tp = sum(1 for a, b in zip(y_true, y_pred) if a == 1 and b == 1)
    fp = sum(1 for a, b in zip(y_true, y_pred) if a == 0 and b == 1)
    fn = sum(1 for a, b in zip(y_true, y_pred) if a == 1 and b == 0)
    p = tp / (tp + fp) if tp + fp else 0
    r = tp / (tp + fn) if tp + fn else 0
    f = 2 * p * r / (p + r) if p + r else 0
    return [round(p, 3), round(r, 3), round(f, 3)]


def cosine(a, b):
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return 0 if not na or not nb else round(sum(x * y for x, y in zip(a, b)) / (na * nb), 4)


def softmax(logits):
    m = max(logits)
    e = [math.exp(x - m) for x in logits]
    return [round(x / sum(e), 4) for x in e]


def chunk(words, size, overlap):
    out, i = [], 0
    while i < len(words):
        out.append(" ".join(words[i : i + size]))
        if i + size >= len(words):
            break
        i += size - overlap
    return out


def retrieve(query, docs, k):
    return sorted(range(len(docs)), key=lambda i: (-cosine(query, docs[i]), i))[:k]


def knn(X, y, x, k):
    near = sorted(range(len(X)), key=lambda i: sum((a - b) ** 2 for a, b in zip(X[i], x)))[:k]
    c = Counter(y[i] for i in near)
    return sorted(c, key=lambda l: (-c[l], l))[0]


def moving_average(values, k):
    return [round(sum(values[i : i + k]) / k, 2) for i in range(len(values) - k + 1)]


def second_highest(salaries):
    s = sorted(set(salaries), reverse=True)
    return s[1] if len(s) > 1 else None


def group_sum(rows):
    t = defaultdict(int)
    for r, a in rows:
        t[r] += a
    return sorted(([r, v] for r, v in t.items()), key=lambda x: (-x[1], x[0]))


def latest(records):
    best = {}
    for r in records:
        if r[0] not in best or r[1] > best[r[0]][1]:
            best[r[0]] = r
    return [best[k] for k in sorted(best)]


def count_bits(n):
    return bin(n).count("1")


def checksum(packet):
    return (~(sum(packet) & 0xFF)) & 0xFF


REF = {
    "two_sum": two_sum, "valid_parentheses": is_valid, "longest_unique": longest_unique, "merge_intervals": merge,
    "top_k_frequent": top_k_frequent, "num_islands": num_islands, "coin_change": coin_change, "group_anagrams": group_anagrams,
    "rate_limiter": allow_requests, "precision_recall": prf, "cosine_similarity": cosine, "softmax": softmax,
    "chunk_text": chunk, "top_k_retrieval": retrieve, "knn_predict": knn, "moving_average": moving_average,
    "second_highest": second_highest, "group_sum": group_sum, "dedupe_latest": latest, "count_bits": count_bits, "checksum": checksum,
}


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
