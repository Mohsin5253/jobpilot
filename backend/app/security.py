import base64
import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

ALGORITHM = "HS256"
COOKIE_NAME = "jp_session"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def create_token(user_id: uuid.UUID, version: int = 0, ttl_hours: int | None = None) -> str:
    now = datetime.now(UTC)
    payload = {"sub": str(user_id), "ver": version, "iat": now, "exp": now + timedelta(hours=ttl_hours or settings.jwt_ttl_hours)}
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str) -> tuple[uuid.UUID, int] | None:
    """(user id, token version) for a valid token; the caller checks the version against the user's."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        return uuid.UUID(payload["sub"]), int(payload.get("ver", 0))
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        return None


def new_reset_token() -> tuple[str, str]:
    """(token for the email link, sha256 stored in the database)."""
    token = secrets.token_urlsafe(32)
    return token, hash_reset_token(token)


def hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@lru_cache
def _fernet() -> Fernet:
    key = settings.encryption_key
    if not key:  # dev / tests only (prod refuses to boot without ENCRYPTION_KEY)
        key = base64.urlsafe_b64encode(hashlib.sha256(f"jobpilot-dev:{settings.jwt_secret}".encode()).digest()).decode()
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str | None:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return None
