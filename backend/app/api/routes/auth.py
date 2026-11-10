from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import func, select, update

from app.api.deps import RealUserDep, SessionDep, UserDep
from app.config import settings
from app.logging import log
from app.models import PasswordReset, Profile, User
from app.schemas import ChangePasswordIn, ForgotPasswordIn, LoginIn, Preferences, RegisterIn, ResetPasswordIn, TokenOut, UserOut
from app.security import COOKIE_NAME, create_token, hash_password, hash_reset_token, new_reset_token, verify_password
from app.services.consent import grant
from app.services.mailer import send_system_email
from app.services.ratelimit import client_ip, hit

router = APIRouter(prefix="/auth", tags=["auth"])
RESET_TTL = timedelta(hours=1)


def user_out(user: User) -> UserOut:
    out = UserOut.model_validate(user)
    out.is_admin = user.is_admin or user.email.lower() in {e.lower() for e in settings.admin_emails}
    return out


def _issue(response: Response, user: User) -> TokenOut:
    ttl = settings.demo_ttl_hours if user.is_demo else settings.jwt_ttl_hours
    token = create_token(user.id, user.token_version, ttl_hours=ttl)
    response.set_cookie(COOKIE_NAME, token, max_age=ttl * 3600, httponly=True, secure=settings.cookie_secure, samesite="lax", path="/")
    return TokenOut(access_token=token, user=user_out(user))


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterIn, request: Request, response: Response, session: SessionDep) -> TokenOut:
    await hit("register", client_ip(request))
    if not body.consent:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Please accept the privacy notice to create an account")
    email = body.email.lower()
    if (await session.execute(select(User).where(func.lower(User.email) == email))).scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    user = User(email=email, name=body.name.strip(), password_hash=hash_password(body.password), is_admin=email in {e.lower() for e in settings.admin_emails})
    session.add(user)
    await session.flush()
    session.add(Profile(user_id=user.id, resume={}, preferences=Preferences().model_dump()))
    await grant(session, user.id, "core")
    await session.commit()
    await session.refresh(user)
    return _issue(response, user)


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, request: Request, response: Response, session: SessionDep) -> TokenOut:
    ip = client_ip(request)
    await hit("login", f"{ip}:{body.email.lower()}")  # guessing one account's password
    await hit("login", ip)  # spraying many accounts from one address (counted separately)
    user = (await session.execute(select(User).where(func.lower(User.email) == body.email.lower(), User.is_demo.is_(False)))).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    return _issue(response, user)


@router.post("/demo", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def demo(request: Request, response: Response, session: SessionDep) -> TokenOut:
    """A private, throwaway copy of the showcase account (see services/demo.py)."""
    from app.services.demo import create_demo_user

    if not settings.demo_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The demo is turned off")
    await hit("demo", client_ip(request))
    user = await create_demo_user(session)
    return _issue(response, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(user: RealUserDep, response: Response, session: SessionDep) -> None:
    """Sign out on every device: older tokens carry the previous version and stop working."""
    await session.execute(update(User).where(User.id == user.id).values(token_version=User.token_version + 1))
    await session.commit()
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/me", response_model=UserOut)
async def me(user: UserDep) -> UserOut:
    return user_out(user)


@router.post("/change-password", response_model=TokenOut)
async def change_password(body: ChangePasswordIn, user: RealUserDep, response: Response, session: SessionDep) -> TokenOut:
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Your current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1  # other devices are signed out; this one gets a fresh session
    await session.commit()
    return _issue(response, user)


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(body: ForgotPasswordIn, request: Request, session: SessionDep) -> dict:
    """Always answers the same way, so it can't be used to find out who has an account."""
    await hit("password_reset", client_ip(request))
    await hit("password_reset", body.email.lower())
    user = (await session.execute(select(User).where(func.lower(User.email) == body.email.lower(), User.is_demo.is_(False)))).scalar_one_or_none()
    if user:
        token, digest = new_reset_token()
        session.add(PasswordReset(token_hash=digest, user_id=user.id, expires_at=datetime.now(UTC) + RESET_TTL))
        await session.commit()
        link = f"{settings.app_url.rstrip('/')}/reset-password?token={token}"
        sent = await send_system_email(
            user.email,
            "Reset your JobPilot password",
            f"Hi {user.name or 'there'},\n\nReset your password here (the link works once, for one hour):\n{link}\n\n"
            "If you didn't ask for this, you can ignore this email.\n\n— JobPilot",
        )
        if not sent and settings.env == "dev":
            log.info("auth.reset_link_dev_only", link=link)  # no system mail configured locally
    return {"detail": "If that email has an account, a reset link is on its way."}


@router.post("/reset-password", response_model=TokenOut)
async def reset_password(body: ResetPasswordIn, response: Response, session: SessionDep) -> TokenOut:
    now = datetime.now(UTC)
    row = (
        await session.execute(select(PasswordReset).where(PasswordReset.token_hash == hash_reset_token(body.token)).with_for_update())
    ).scalar_one_or_none()
    if row is None or row.used_at or row.expires_at < now:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This reset link has expired or was already used. Ask for a new one.")
    user = await session.get(User, row.user_id)
    row.used_at = now
    user.password_hash = hash_password(body.password)
    user.token_version += 1  # every existing session ends
    await session.commit()
    return _issue(response, user)
