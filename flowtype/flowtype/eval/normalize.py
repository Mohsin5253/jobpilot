"""Text normalisation for scoring, so a clean-up that writes numbers the way people write them isn't counted as an
error: "twelve thousand five hundred rupees" and "₹12,500" both become "12500 rupees"; "four thirty" and "4:30"
both become "4 30"; "the third of December" and "the 3rd of December" both become "the 3 of december"."""

import re

UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split())}
TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}
SCALES = {"hundred": 100, "thousand": 1000, "lakh": 100_000, "lakhs": 100_000, "million": 1_000_000, "crore": 10_000_000, "crores": 10_000_000}
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
            "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fifteenth": 15, "twentieth": 20, "thirtieth": 30}


def words_to_digits(tokens: list[str]) -> list[str]:
    out: list[str] = []
    total = cur = 0
    started = False
    prev = ""

    def flush():
        nonlocal total, cur, started
        if started:
            out.append(str(total + cur))
        total = cur = 0
        started = False

    for w in tokens:
        if w in UNITS or w in TENS:
            v = UNITS.get(w, TENS.get(w, 0))
            if started and not (prev in TENS and w in UNITS and v < 10) and prev not in SCALES and prev != "and":
                flush()
            cur += v
            started = True
        elif w in SCALES and started:
            cur = max(cur, 1) * SCALES[w]
            if SCALES[w] >= 1000:
                total, cur = total + cur, 0
        elif w == "and" and started and prev in SCALES:
            pass
        else:
            flush()
            out.append(w)
        prev = w
    flush()
    return out


def normalize(text: str, ordinals: bool = True) -> str:
    t = text.lower().replace("’", "'")
    t = re.sub(r"(?<=[a-z])[-\u2010\u2011\u2013](?=[a-z])", "", t)  # stand-up / stand‑up / standup are one word
    t = re.sub(r"(?:₹|\brs\.?\s?|\binr\s?)(\d[\d,]*(?:\.\d+)?)", r"\1 rupees", t)
    t = re.sub(r"(\d),(?=\d{2,3}\b)", r"\1", t)  # 12,500 / 1,00,000
    t = re.sub(r"(\d+)[:.](\d\d)\b(?!\.\d)", r"\1 \2", t)  # 4:30, 4.30 (times)
    t = re.sub(r"(\d+)\s?%", r"\1 percent", t)
    t = re.sub(r"\b(\d+)(st|nd|rd|th)\b", r"\1", t)
    t = re.sub(r"[^\w\s']", " ", t)
    tokens = [w.strip("'") for w in t.split() if w.strip("'")]
    if ordinals:
        tokens = [str(ORDINALS[w]) if w in ORDINALS and i > 0 and tokens[i - 1] == "the" else w for i, w in enumerate(tokens)]
    return " ".join(words_to_digits(tokens))
