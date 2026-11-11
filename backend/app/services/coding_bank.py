"""Coding round problems, per industry and level, the kind asked in Indian internship and fresher technical interviews.

Software roles get data-structures-and-algorithms problems; AI/ML roles get problems from the current stack
(metrics, embeddings, retrieval and chunking for RAG); analytics roles get data-wrangling problems; electronics
roles get bit manipulation. Every problem has a signature per language and tests (inputs -> expected output).

Code is never run on our servers: Python and JavaScript run in the candidate's browser (a sandboxed worker), and the
results plus the code go to the AI code reviewer. Java and C++ are reviewed by the AI only. `trend` tags tie a
problem to skills that are rising in postings, so the trend refresh (question_trends.py) can favour them.
"""

import zlib
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Problem:
    id: str
    title: str
    difficulty: str  # easy | medium | hard
    industries: tuple[str, ...]
    tags: tuple[str, ...]
    statement: str
    py: str  # function name in Python
    js: str  # function name in JavaScript
    params: tuple[str, ...]
    tests: tuple[dict, ...]  # {"args": [...], "expected": ..., "visible": bool}
    compare: str = "exact"  # exact | unordered | float | nested_unordered
    minutes: int = 20
    hint_complexity: str = ""
    trend: tuple[str, ...] = field(default_factory=tuple)

    def signature(self, lang: str) -> str:
        p = ", ".join(self.params)
        if lang == "python":
            return f"def {self.py}({p}):\n    # write your solution here\n    pass\n"
        if lang == "javascript":
            return f"function {self.js}({p}) {{\n  // write your solution here\n}}\n"
        if lang == "java":
            return f"class Solution {{\n    // implement {self.js}({p})\n    public Object {self.js}(/* {p} */) {{\n        return null;\n    }}\n}}\n"
        return f"// implement {self.py}({p})\n#include <bits/stdc++.h>\nusing namespace std;\n\nauto {self.py}(/* {p} */) {{\n}}\n"

    def public(self) -> dict:
        """What the browser gets: everything needed to run the tests locally."""
        return {
            "id": self.id,
            "title": self.title,
            "difficulty": self.difficulty,
            "tags": list(self.tags),
            "statement": self.statement,
            "fn": {"python": self.py, "javascript": self.js},
            "params": list(self.params),
            "starter": {lang: self.signature(lang) for lang in ("python", "javascript", "java", "cpp")},
            "tests": [{"args": t["args"], "expected": t["expected"], "visible": t.get("visible", False)} for t in self.tests],
            "compare": self.compare,
            "minutes": self.minutes,
        }


def T(args, expected, visible=False) -> dict:
    return {"args": args, "expected": expected, "visible": visible}


PROBLEMS: tuple[Problem, ...] = (
    # ---------------------------------------------------------------- software engineering (DSA)
    Problem(
        "two_sum", "Two Sum", "easy", ("software", "data_science"), ("arrays", "hash map"),
        "Given a list of integers `nums` and an integer `target`, return the indices of the two numbers that add up to `target`, as a list `[i, j]` with `i < j`. Exactly one answer exists. Aim for better than O(n²).",
        "two_sum", "twoSum", ("nums", "target"),
        (T([[2, 7, 11, 15], 9], [0, 1], True), T([[3, 2, 4], 6], [1, 2], True), T([[3, 3], 6], [0, 1]), T([[-1, -2, -3, -4, -5], -8], [2, 4]), T([[0, 4, 3, 0], 0], [0, 3])),
        minutes=15, hint_complexity="O(n) with a hash map",
    ),
    Problem(
        "valid_parentheses", "Valid Brackets", "easy", ("software",), ("stack", "strings"),
        "Given a string `s` containing only `()[]{}`, return `True` if every bracket is closed by the same type in the right order, else `False`.",
        "is_valid", "isValid", ("s",),
        (T(["()[]{}"], True, True), T(["(]"], False, True), T(["([{}])"], True), T(["(("], False), T([""], True), T(["}{"], False), T(["([)]"], False)),
        minutes=15, hint_complexity="O(n) with a stack",
    ),
    Problem(
        "longest_unique", "Longest Substring Without Repeats", "medium", ("software",), ("sliding window", "strings", "hash map"),
        "Return the length of the longest substring of `s` with no repeated characters.",
        "longest_unique", "longestUnique", ("s",),
        (T(["abcabcbb"], 3, True), T(["bbbbb"], 1, True), T(["pwwkew"], 3), T([""], 0), T(["dvdf"], 3), T(["abba"], 2)),
        minutes=20, hint_complexity="O(n) sliding window",
    ),
    Problem(
        "merge_intervals", "Merge Meeting Slots", "medium", ("software", "operations"), ("sorting", "intervals"),
        "Given a list of `[start, end]` intervals, merge all overlapping ones (touching intervals like [1,4] and [4,5] overlap) and return them sorted by start.",
        "merge", "merge", ("intervals",),
        (T([[[1, 3], [2, 6], [8, 10], [15, 18]]], [[1, 6], [8, 10], [15, 18]], True), T([[[1, 4], [4, 5]]], [[1, 5]], True), T([[[5, 7], [1, 2]]], [[1, 2], [5, 7]]), T([[[1, 10], [2, 3], [4, 5]]], [[1, 10]]), T([[]], [])),
        minutes=20, hint_complexity="O(n log n) sort then sweep",
    ),
    Problem(
        "top_k_frequent", "Top K Frequent Items", "medium", ("software", "data_analytics", "data_science"), ("hash map", "heap", "sorting"),
        "Return the `k` most frequent values in `nums`, most frequent first; break ties by the smaller value first.",
        "top_k_frequent", "topKFrequent", ("nums", "k"),
        (T([[1, 1, 1, 2, 2, 3], 2], [1, 2], True), T([[4, 4, 5, 5, 6], 2], [4, 5], True), T([[1], 1], [1]), T([[3, 3, 1, 1, 2, 2, 2], 3], [2, 1, 3])),
        minutes=20, hint_complexity="O(n log n), or O(n log k) with a heap",
    ),
    Problem(
        "num_islands", "Count Islands", "medium", ("software",), ("graphs", "BFS/DFS", "grid"),
        "Given a grid of '1' (land) and '0' (water), count the islands. Land connects horizontally and vertically.",
        "num_islands", "numIslands", ("grid",),
        (T([[["1", "1", "0"], ["1", "0", "0"], ["0", "0", "1"]]], 2, True), T([[["1", "1", "1"], ["0", "1", "0"], ["1", "1", "1"]]], 1, True), T([[["0"]]], 0), T([[["1", "0", "1", "0", "1"]]], 3)),
        minutes=25, hint_complexity="O(rows × cols) with BFS or DFS",
    ),
    Problem(
        "coin_change", "Minimum Coins (UPI cashback)", "medium", ("software", "finance"), ("dynamic programming",),
        "Given coin values `coins` and an `amount`, return the fewest coins that add up to it, or -1 if impossible.",
        "coin_change", "coinChange", ("coins", "amount"),
        (T([[1, 2, 5], 11], 3, True), T([[2], 3], -1, True), T([[1], 0], 0), T([[2, 5, 10, 1], 27], 4), T([[186, 419, 83, 408], 6249], 20)),
        minutes=25, hint_complexity="O(amount × coins) DP",
    ),
    Problem(
        "group_anagrams", "Group Anagrams", "medium", ("software",), ("hash map", "strings", "sorting"),
        "Group the words that are anagrams of each other. Return the groups with each group's words sorted, and the groups sorted by their first word.",
        "group_anagrams", "groupAnagrams", ("words",),
        (T([["eat", "tea", "tan", "ate", "nat", "bat"]], [["ate", "eat", "tea"], ["bat"], ["nat", "tan"]], True), T([[""]], [[""]], True), T([["a"]], [["a"]]), T([["ab", "ba", "abc", "cab", "bca", "x"]], [["ab", "ba"], ["abc", "bca", "cab"], ["x"]])),
        minutes=20, hint_complexity="O(n · k log k)",
    ),
    Problem(
        "rate_limiter", "Rate Limiter Log", "hard", ("software",), ("queues", "sliding window", "system design"),
        "An API allows at most `limit` requests per user in any `window`-second window (a request at time t counts in [t - window + 1, t]). Given `requests` as `[time, user]` pairs in time order, return a list of booleans: whether each request is allowed. Rejected requests don't count.",
        "allow_requests", "allowRequests", ("requests", "limit", "window"),
        (T([[[1, "a"], [2, "a"], [3, "a"], [4, "a"]], 3, 10], [True, True, True, False], True), T([[[1, "a"], [11, "a"], [12, "a"]], 1, 10], [True, True, False], True), T([[[1, "a"], [1, "b"], [2, "a"], [2, "b"]], 1, 5], [True, True, False, False]), T([[[1, "a"], [3, "a"], [6, "a"], [7, "a"]], 2, 5], [True, True, True, False])),
        minutes=25, hint_complexity="O(n) with a queue per user",
        trend=("System design", "Backend", "Microservices"),
    ),
    # ---------------------------------------------------------------- AI / ML / data science
    Problem(
        "precision_recall", "Precision, Recall, F1", "easy", ("data_science",), ("ML metrics",),
        "Given binary labels `y_true` and predictions `y_pred` (0/1 lists), return `[precision, recall, f1]` for class 1, each rounded to 3 decimals. If a denominator is 0, that value is 0.",
        "prf", "prf", ("y_true", "y_pred"),
        (T([[1, 0, 1, 1, 0], [1, 0, 0, 1, 1]], [0.667, 0.667, 0.667], True), T([[0, 0], [0, 0]], [0, 0, 0], True), T([[1, 1, 1, 0], [1, 1, 1, 1]], [0.75, 1.0, 0.857]), T([[1, 0, 1], [0, 1, 0]], [0, 0, 0])),
        compare="float", minutes=15, hint_complexity="O(n)", trend=("Model Evaluation", "Machine Learning"),
    ),
    Problem(
        "cosine_similarity", "Cosine Similarity of Embeddings", "easy", ("data_science", "software"), ("vectors", "embeddings"),
        "Return the cosine similarity of two equal-length vectors `a` and `b`, rounded to 4 decimals. If either vector is all zeros, return 0.",
        "cosine", "cosine", ("a", "b"),
        (T([[1, 0, 0], [1, 0, 0]], 1.0, True), T([[1, 2, 3], [4, 5, 6]], 0.9746, True), T([[1, 0], [0, 1]], 0.0), T([[0, 0], [1, 1]], 0.0), T([[1, -1], [-1, 1]], -1.0)),
        compare="float", minutes=12, hint_complexity="O(n)", trend=("Embeddings", "LLMs", "Vector Databases", "RAG"),
    ),
    Problem(
        "softmax", "Numerically Stable Softmax", "easy", ("data_science",), ("deep learning", "numerics"),
        "Return the softmax of `logits` as a list rounded to 4 decimals. It must not overflow for large values like 1000.",
        "softmax", "softmax", ("logits",),
        (T([[1, 2, 3]], [0.09, 0.2447, 0.6652], True), T([[0, 0]], [0.5, 0.5], True), T([[1000, 1000]], [0.5, 0.5]), T([[1000, 0]], [1.0, 0.0])),
        compare="float", minutes=12, hint_complexity="O(n); subtract the max first", trend=("Deep Learning", "LLMs", "Transformers"),
    ),
    Problem(
        "chunk_text", "Chunk Text for RAG", "medium", ("data_science", "software"), ("strings", "RAG"),
        "Split `words` (a list of words) into chunks of `size` words where each chunk overlaps the previous one by `overlap` words, as used to index documents for retrieval. Return the chunks as space-joined strings. The last chunk may be shorter; don't emit a chunk that adds no new words.",
        "chunk", "chunk", ("words", "size", "overlap"),
        (T([["a", "b", "c", "d", "e"], 2, 1], ["a b", "b c", "c d", "d e"], True), T([["a", "b", "c", "d", "e"], 3, 1], ["a b c", "c d e"], True), T([["a", "b"], 5, 2], ["a b"]), T([[], 3, 1], []), T([["a", "b", "c", "d", "e", "f", "g"], 3, 0], ["a b c", "d e f", "g"])),
        minutes=20, hint_complexity="O(n)", trend=("RAG", "LLMs", "LangChain", "Agents"),
    ),
    Problem(
        "top_k_retrieval", "Top-k Retrieval", "medium", ("data_science", "software"), ("vectors", "sorting", "RAG"),
        "Given a `query` vector and a list of document vectors `docs`, return the indices of the `k` documents with the highest cosine similarity to the query, best first (ties: smaller index first).",
        "retrieve", "retrieve", ("query", "docs", "k"),
        (T([[1, 0], [[1, 0], [0, 1], [1, 1]], 2], [0, 2], True), T([[0, 1], [[1, 0], [0, 2], [0, 1]], 1], [1], True), T([[1, 1], [[1, 1], [2, 2], [-1, -1]], 3], [0, 1, 2])),
        minutes=20, hint_complexity="O(n·d + n log n)", trend=("RAG", "Vector Databases", "Embeddings", "LLMs"),
    ),
    Problem(
        "knn_predict", "k-Nearest Neighbours", "medium", ("data_science",), ("ML", "distance"),
        "Classify point `x` by majority vote of its `k` nearest training points (Euclidean). `X` is a list of points, `y` their labels. On a vote tie, return the smallest label.",
        "knn", "knn", ("X", "y", "x", "k"),
        (T([[[0, 0], [1, 1], [5, 5], [6, 6]], [0, 0, 1, 1], [0.5, 0.5], 3], 0, True), T([[[0, 0], [10, 10], [11, 11]], [1, 2, 2], [9, 9], 1], 2, True), T([[[0], [1], [2], [3]], [1, 0, 1, 0], [1.5], 2], 0)),
        minutes=20, hint_complexity="O(n log n)", trend=("Machine Learning", "scikit-learn"),
    ),
    Problem(
        "moving_average", "Moving Average", "easy", ("data_science", "data_analytics", "finance"), ("time series", "sliding window"),
        "Return the moving averages of `values` over windows of `k`, rounded to 2 decimals (one per full window).",
        "moving_average", "movingAverage", ("values", "k"),
        (T([[1, 2, 3, 4, 5], 2], [1.5, 2.5, 3.5, 4.5], True), T([[10, 20, 30], 3], [20.0], True), T([[5], 2], []), T([[1, 1, 1, 1], 1], [1, 1, 1, 1])),
        compare="float", minutes=12, hint_complexity="O(n) running sum", trend=("Time Series",),
    ),
    # ---------------------------------------------------------------- data analytics
    Problem(
        "second_highest", "Second Highest Salary", "easy", ("data_analytics", "software"), ("SQL logic", "sorting"),
        "Return the second highest distinct value in `salaries`, or `None` (`null` in JavaScript) if there isn't one. (The classic SQL question, in code.)",
        "second_highest", "secondHighest", ("salaries",),
        (T([[100, 200, 300]], 200, True), T([[100]], None, True), T([[100, 100]], None), T([[5, 3, 5, 4]], 4)),
        minutes=10, hint_complexity="O(n)",
    ),
    Problem(
        "group_sum", "Revenue by Region", "easy", ("data_analytics", "finance", "operations"), ("group by", "aggregation"),
        "Each row is `[region, amount]`. Return `[[region, total], ...]` sorted by total descending, then region ascending. (GROUP BY ... ORDER BY, in code.)",
        "group_sum", "groupSum", ("rows",),
        (T([[["South", 10], ["North", 5], ["South", 7]]], [["South", 17], ["North", 5]], True), T([[]], [], True), T([[["A", 1], ["B", 1]]], [["A", 1], ["B", 1]])),
        minutes=12, hint_complexity="O(n log n)",
    ),
    Problem(
        "dedupe_latest", "Latest Record per Customer", "medium", ("data_analytics", "software"), ("deduplication", "window functions"),
        "Each record is `[customer_id, timestamp, status]`. Keep only each customer's latest record (highest timestamp) and return them sorted by customer_id. (ROW_NUMBER() OVER (PARTITION BY ...), in code.)",
        "latest", "latest", ("records",),
        (T([[[2, 5, "paid"], [1, 3, "new"], [2, 9, "refund"], [1, 1, "lead"]]], [[1, 3, "new"], [2, 9, "refund"]], True), T([[]], [], True), T([[[7, 1, "a"]]], [[7, 1, "a"]])),
        minutes=15, hint_complexity="O(n log n)",
    ),
    # ---------------------------------------------------------------- electronics / embedded
    Problem(
        "count_bits", "Count Set Bits", "easy", ("core_engineering", "software"), ("bit manipulation",),
        "Return the number of 1 bits in the binary form of the non-negative integer `n`.",
        "count_bits", "countBits", ("n",),
        (T([11], 3, True), T([0], 0, True), T([255], 8), T([1024], 1)),
        minutes=10, hint_complexity="O(number of set bits)",
    ),
    Problem(
        "checksum", "Packet Checksum", "medium", ("core_engineering",), ("bit manipulation", "embedded"),
        "A sensor packet is a list of bytes (0-255). Its checksum is the bytes summed with 8-bit wraparound, then bitwise-inverted (also 8-bit). Return the checksum.",
        "checksum", "checksum", ("packet",),
        (T([[1, 2, 3]], 249, True), T([[255, 1]], 255, True), T([[]], 255), T([[200, 100]], 211)),
        minutes=15, hint_complexity="O(n)", trend=("Embedded systems", "IoT"),
    ),
)

BY_ID = {p.id: p for p in PROBLEMS}

# Which industries get a coding round at all, and how many problems per interview length.
CODING_INDUSTRIES = {"software", "data_science", "data_analytics", "core_engineering"}
PROBLEMS_FOR_MINUTES = {30: 1, 45: 2, 60: 2}


def pick_problems(industry: str, level: str, minutes: int, trending: list[str] | None = None, seed: int = 0) -> list[Problem]:
    """Problems for this field and level. Interns get easy then medium; freshers (entry-level jobs) medium and a
    harder one in a 60-minute interview. Problems tied to skills trending in this field's postings come first."""
    n = PROBLEMS_FOR_MINUTES.get(minutes, 2)
    pool = [p for p in PROBLEMS if industry in p.industries] or [p for p in PROBLEMS if "software" in p.industries]
    trend = {t.lower() for t in trending or []}

    def rank(p: Problem) -> tuple:
        hot = -sum(1 for t in p.trend if t.lower() in trend)
        primary = 0 if p.industries[0] == industry else 1  # a software intern gets DSA before an electronics bit puzzle
        return (hot, primary, zlib.crc32(f"{p.id}:{seed}".encode()) % 97)

    want = (["easy", "medium"] if level == "intern" else ["medium", "hard" if minutes >= 60 else "medium"])[:n] if n > 1 else (["easy"] if level == "intern" and minutes <= 30 else ["medium"])
    chosen: list[Problem] = []
    for d in want:
        options = sorted((p for p in pool if p.difficulty == d and p not in chosen), key=rank)
        if not options:
            options = sorted((p for p in pool if p not in chosen), key=rank)
        if options:
            chosen.append(options[0])
    return chosen
