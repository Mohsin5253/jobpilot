"""Switch an account's plan (no payments yet), or make it an admin.

  uv run python -m scripts.set_plan someone@example.com pro
  uv run python -m scripts.set_plan someone@example.com free
  uv run python -m scripts.set_plan you@example.com admin     # can open /admin
"""

import asyncio
import sys

from sqlalchemy import func, select

from app.config import PLAN_LIMITS
from app.db import session_scope
from app.models import User


async def main(email: str, what: str) -> int:
    async with session_scope() as s:
        user = (await s.execute(select(User).where(func.lower(User.email) == email.lower()))).scalar_one_or_none()
        if user is None:
            print(f"No account with email {email}")
            return 1
        if what == "admin":
            user.is_admin = True
        elif what in PLAN_LIMITS:
            user.plan = what
        else:
            print(f"Use one of: {', '.join(PLAN_LIMITS)}, admin")
            return 1
        print(f"{user.email}: plan={user.plan} admin={user.is_admin}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(asyncio.run(main(sys.argv[1], sys.argv[2])))
