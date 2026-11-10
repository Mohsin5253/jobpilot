"""Save Gmail SMTP settings into backend/.env so "Approve & send" can email applications from your address.

  uv run python scripts/set_smtp.py

Prompts in your terminal, never echoes the password, tests the login with Gmail first and only saves
credentials Gmail accepts. Nothing is emailed.
"""

import getpass
import re
import smtplib
import sys
from pathlib import Path

ENV = Path(__file__).resolve().parents[1] / ".env"
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def check_login(user: str, password: str) -> tuple[bool, str]:
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as s:
            s.ehlo()
            s.starttls()
            s.ehlo()
            s.login(user, password)
        return True, "ok"
    except smtplib.SMTPAuthenticationError as e:
        msg = e.smtp_error.decode(errors="replace") if isinstance(e.smtp_error, bytes) else str(e.smtp_error)
        return False, f"{e.smtp_code} {' '.join(msg.split())}"
    except smtplib.SMTPServerDisconnected:
        # Gmail sometimes just hangs up on a rejected AUTH PLAIN instead of answering 535.
        return False, "Gmail closed the connection during login (it does this when the password is wrong)"
    except OSError as e:
        return False, f"Couldn't reach smtp.gmail.com: {e}"


def save(user: str, password: str) -> None:
    values = {"SMTP_HOST": "smtp.gmail.com", "SMTP_PORT": "587", "SMTP_USER": user, "SMTP_PASSWORD": password, "SMTP_FROM": user}
    lines = ENV.read_text().splitlines() if ENV.exists() else []
    seen = set()
    out = []
    for line in lines:
        key = line.split("=", 1)[0]
        if key in values:
            out.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in values.items() if k not in seen]
    ENV.write_text("\n".join(out) + "\n")
    ENV.chmod(0o600)


def main() -> int:
    user = input("Gmail address: ").strip()
    if not EMAIL.match(user):
        print("That doesn't look like an email address — nothing saved.", file=sys.stderr)
        return 1
    raw = getpass.getpass("Gmail App Password (16 letters, spaces OK): ")
    password = "".join(raw.split())  # drops every kind of whitespace, incl. non-breaking spaces from copy/paste
    if not password:
        print("No password entered — nothing saved.", file=sys.stderr)
        return 1
    print(f"Got {len(password)} characters. Checking with Gmail (nothing is emailed)…")
    ok, detail = check_login(user, password)
    if not ok:
        print(f"\nGmail did not accept it: {detail}", file=sys.stderr)
        if len(password) != 16 or not password.isalpha():
            print("That isn't the 16-letter App Password format — it looks like your normal Gmail password.", file=sys.stderr)
        print(
            "Create an App Password at https://myaccount.google.com/apppasswords (2-Step Verification must be on),\n"
            "copy the 16 letters from the yellow box, and run this again. Nothing saved.",
            file=sys.stderr,
        )
        return 1
    save(user, password)
    print("Gmail accepted the login. saved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
