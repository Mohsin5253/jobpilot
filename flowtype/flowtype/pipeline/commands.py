"""Spoken formatting and command mode.

- Spoken formatting (always on): "new line" and "new paragraph" become line breaks.
- Command mode (hold Shift with the hotkey): what you say is an instruction, not text. With text selected, the
  selection is rewritten ("make this more formal", "translate to Hindi", "turn this into bullet points") and the
  result replaces it. With nothing selected, the instruction is a request for text ("write a two-line reply saying
  I'll be late") that's inserted at the cursor."""

import re
from dataclasses import dataclass

from flowtype.llm.base import LLMError

_NEWLINE = re.compile(r"[,.]?\s*\b(new (?:line|paragraph)|next line)\b[,.]?\s*", re.I)

COMMAND_SYSTEM = """You are a text tool inside a dictation app. The user selected some text and spoke an instruction. Apply the instruction to the SELECTED TEXT and output ONLY the resulting text: no preface, no quotes, no explanation, no markdown fences unless the text is code.
If there is no selected text, write the text the instruction asks for, as the user (first person), ready to paste.
Keep names, numbers and facts from the selected text exactly; never invent facts."""

_PREFACE = re.compile(r"^\s*(sure|certainly|of course|here(?:'s| is| are)\b[^:\n]*:|okay|ok)[,.!:]?\s*", re.I)


def apply_spoken_formatting(text: str) -> str:
    def rep(m: re.Match) -> str:
        return "\n\n" if "paragraph" in m.group(1).lower() else "\n"

    out = _NEWLINE.sub(rep, text)
    out = re.sub(r"\n(\w)", lambda m: "\n" + m.group(1).upper(), out)
    return out.strip(" ")


@dataclass
class CommandResult:
    text: str
    status: str  # ok | empty | error | rejected
    reason: str = ""


def run_command(llm, instruction: str, selected: str, timeout_s: float = 8.0) -> CommandResult:
    if not instruction.strip():
        return CommandResult("", "empty", "no instruction")
    user = f"INSTRUCTION: {instruction.strip()}\nSELECTED TEXT:\n{selected[:6000] if selected else '(none)'}"
    max_tokens = min(2000, max(200, int(len(selected.split()) * 2.5) + 150))
    try:
        out = llm.chat([{"role": "system", "content": COMMAND_SYSTEM}, {"role": "user", "content": user}], max_tokens=max_tokens, timeout_s=timeout_s)
    except LLMError as exc:
        return CommandResult("", "error", str(exc))
    out = out.strip()
    for _ in range(2):  # "Sure, here's the formal version:" is two prefaces
        out = _PREFACE.sub("", out, count=1).strip()
    if out.startswith("```") and not selected.lstrip().startswith("```"):
        out = re.sub(r"^```\w*\n?|\n?```$", "", out).strip()
    if not out:
        return CommandResult("", "empty", "the model returned nothing")
    if selected and len(out.split()) > 4 * len(selected.split()) + 200:
        return CommandResult("", "rejected", "output far longer than the selection")
    return CommandResult(out, "ok")
