"""Snippets: say a cue phrase, get the expansion ("my email address" -> "kavya@example.com", "my calendar link" ->
a URL). The cue must be spoken as a whole phrase; small mishearings are tolerated (rapidfuzz), and the expansion is
inserted verbatim after the clean-up, so the LLM can't alter it."""

import re

from rapidfuzz import fuzz


def _n(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def expand(text: str, snippets: list[tuple[str, str]], threshold: int = 90) -> tuple[str, list[str]]:
    """(text with cues replaced, cues used). A dictation that is only the cue becomes only the expansion."""
    used: list[str] = []
    for cue, expansion in sorted(snippets, key=lambda s: -len(s[0].split())):
        cue_n = _n(cue)
        k = len(cue_n.split())
        if not k:
            continue
        tokens = re.findall(r"\S+", text)
        bare = [_n(t) for t in tokens]
        for i in range(0, len(tokens) - k + 1):
            if fuzz.ratio(" ".join(bare[i : i + k]), cue_n) >= threshold:
                whole = all(not b for b in bare[:i]) and all(not b for b in bare[i + k :])
                if whole:
                    text = expansion
                else:
                    lead = re.match(r"^\W*", tokens[i]).group(0)
                    trail = re.search(r"[,;:]?$", tokens[i + k - 1]).group(0) if tokens[i + k - 1][-1:] in ",;:" else ""
                    text = " ".join([*tokens[:i], f"{lead}{expansion}{trail}", *tokens[i + k :]])
                used.append(cue)
                break
    return text, used
