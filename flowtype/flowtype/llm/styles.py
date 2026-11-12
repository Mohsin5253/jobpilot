"""App-style detection: the clean-up writes differently for an email, a chat message, code or a terminal. The style
comes from the focused app's process name and window title; `[styles] apps` in config.toml overrides it."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Style:
    name: str
    clean: bool  # False = paste exactly what was said (terminals: a rewrite could change a command)
    guide: str


STYLES = {
    "email": Style("email", True, "email: complete sentences and paragraphs; a spoken greeting or sign-off goes on its own line."),
    "chat": Style("chat", True, "chat message: casual and short; keep the speaker's tone; no greeting or sign-off unless spoken; a one-line message needs no final full stop."),
    "code": Style("code", True, "code editor or IDE: when the speaker spells out an identifier, write it as code (getUserById, user_id); no markdown fences; comments in plain sentences."),
    "document": Style("document", True, "document: clear sentences and paragraphs; lists when the speaker enumerates."),
    "terminal": Style("terminal", False, "terminal"),
    "general": Style("general", True, "general text: clear sentences."),
}

# (style, process-name pattern, window-title pattern). The first match wins; processes are matched without ".exe".
RULES: list[tuple[str, str, str]] = [
    ("terminal", r"^(windowsterminal|cmd|powershell|pwsh|wezterm(-gui)?|alacritty|kitty|conhost|mintty|terminal|iterm2?|warp|hyper)$", ""),
    ("email", r"^(outlook|olk|thunderbird|mail|spark|airmail|superhuman)$", r"\b(gmail|outlook|inbox|compose|proton ?mail|yahoo mail)\b"),
    ("chat", r"^(slack|teams|ms-teams|discord|whatsapp|telegram|signal|messages|messenger|zoom|skype|element)$", r"\b(slack|whatsapp|discord|messenger|teams|telegram)\b"),
    ("code", r"^(code|code - insiders|cursor|windsurf|devenv|pycharm\d*|idea\d*|webstorm\d*|clion\d*|goland\d*|rider\d*|android studio|studio\d*|xcode|sublime_text|sublime text|zed|nvim|vim|gvim|emacs|notepad\+\+)$", r"\b(github|gitlab|visual studio code|stack overflow|leetcode|codepen|replit)\b"),
    ("document", r"^(winword|word|microsoft word|notepad|wordpad|pages|textedit|notion|obsidian|onenote|evernote|bear|craft|libreoffice|soffice|scrivener)$", r"\b(google docs|docs\.google|notion|confluence|medium|substack|overleaf)\b"),
]


def detect_style(app: str | None, title: str | None = None, overrides: dict[str, str] | None = None) -> Style:
    proc = re.sub(r"\.(exe|app)$", "", (app or "").strip().lower())
    ttl = (title or "").lower()
    for key, style in (overrides or {}).items():
        if key.lower() in proc or (ttl and key.lower() in ttl):
            return STYLES.get(style, STYLES["general"])
    for name, proc_rx, title_rx in RULES:
        if proc and re.search(proc_rx, proc):
            return STYLES[name]
    for name, _proc_rx, title_rx in RULES:  # browsers: decide by the page title
        if title_rx and ttl and re.search(title_rx, ttl):
            return STYLES[name]
    return STYLES["general"]
