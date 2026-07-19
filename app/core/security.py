"""
Security helpers: password hashing/verification and session token
creation/decoding (JWT stored in an httponly cookie).

Password hashing uses the `bcrypt` library DIRECTLY rather than going
through `passlib`. This is a deliberate choice, not an oversight:
passlib's bcrypt backend runs an internal self-test (`detect_wrap_bug`)
on first use that verifies a fixed, long test hash — and that self-test
itself breaks with a hard `ValueError: password cannot be longer than
72 bytes` on bcrypt>=4.1, because newer bcrypt enforces the 72-byte
limit strictly where older versions were lenient. This is a known,
long-unfixed incompatibility between passlib 1.7.4 and modern bcrypt —
pinning bcrypt's version in requirements.txt works only as long as
pip actually honors that pin in a given environment, which isn't
something this code should have to depend on.

Calling `bcrypt.hashpw` / `bcrypt.checkpw` directly avoids passlib's
self-test entirely, so this works correctly across every bcrypt
version without needing a fragile pin at all.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from jose import jwt, JWTError

from app.core.config import settings

# bcrypt itself has a hard 72-byte limit on the input password — not a
# passlib quirk, this is intrinsic to the bcrypt algorithm. Longer
# inputs are truncated here explicitly (rather than letting bcrypt
# raise), which matches standard bcrypt usage guidance.
_BCRYPT_MAX_BYTES = 72


def hash_password(plain_password: str) -> str:
    password_bytes = plain_password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    password_bytes = plain_password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    try:
        return bcrypt.checkpw(password_bytes, hashed_password.encode("utf-8"))
    except ValueError:
        # Malformed/foreign hash format (e.g. leftover from a different
        # scheme) — treat as "doesn't match" rather than crashing.
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return None
