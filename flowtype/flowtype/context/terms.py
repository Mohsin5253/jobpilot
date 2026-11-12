"""Context terms for the bias prompt: the names, identifiers and jargon visible around the cursor (window title and
the text before the caret). Whisper then spells "Kubernetes" or "getUserById" the way the document already does.

Only these terms are used, never the raw text, and they're ordered least relevant first: the words nearest the
caret are last, where Whisper weighs them most."""

import re

from flowtype.dictionary.phonetic import COMMON

_TOKEN = re.compile(r"[A-Za-z][\w'+#.-]*[\w+#]|[A-Za-z]")
# Window-title chrome that isn't content.
_TITLE_NOISE = re.compile(r"\s[-—|·]\s(google chrome|microsoft edge|firefox|safari|brave|opera|arc|visual studio code|cursor|notepad|word|outlook|slack|microsoft teams)\s*$", re.I)
_STOP = COMMON | set("i you we they he she it a an the this that these those here there".split())


def _interesting(tok: str, sentence_start: bool) -> bool:
    if len(tok) < 3 or tok.lower() in _STOP:
        return False
    if re.search(r"[a-z][A-Z]|_|\d|[+#]", tok):  # camelCase, snake_case, digits, C++/C#
        return True
    if tok.isupper() and len(tok) <= 8:  # acronyms
        return True
    return tok[0].isupper() and not sentence_start  # a capitalised word mid-sentence is probably a name


def extract_terms(title: str | None, before_text: str, limit: int = 20) -> list[str]:
    found: list[str] = []
    for source in (_TITLE_NOISE.sub("", title or ""), before_text[-600:]):
        prev = "."
        for m in re.finditer(r"\S+", source):
            raw = m.group(0)
            for tok in _TOKEN.findall(raw):
                if _interesting(tok.rstrip(".'"), prev.endswith((".", "?", "!", ":", "\n")) or prev == "."):
                    found.append(tok.rstrip(".'"))
            prev = raw
    out: list[str] = []
    seen: set[str] = set()
    for t in reversed(found):  # nearest the caret wins a duplicate
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return list(reversed(out[:limit]))
