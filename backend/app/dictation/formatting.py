"""Spoken formatting (from Flowtype): "new line" and "new paragraph" become line breaks. Said at the very start or end
of a take, they're a break before or after the text, which the clean-up would otherwise trim away."""

import re

_NEWLINE = re.compile(r"[,.]?\s*\b(new (?:line|paragraph)|next line)\b[,.]?\s*", re.I)


def apply_spoken_formatting(text: str) -> str:
    def rep(m: re.Match) -> str:
        return "\n\n" if "paragraph" in m.group(1).lower() else "\n"

    out = _NEWLINE.sub(rep, text)
    out = re.sub(r"\n(\w)", lambda m: "\n" + m.group(1).upper(), out)
    return out.strip(" ")


def split_breaks(text: str) -> tuple[str, str, str]:
    """(leading breaks, body, trailing breaks): the body goes through the clean-up, the breaks are put back after."""
    body = text.strip("\n")
    return text[: len(text) - len(text.lstrip("\n"))], body, text[len(text.rstrip("\n")) :] if body else ""
