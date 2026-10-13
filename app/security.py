"""
Security utilities:
  - bcrypt password hashing
  - OTP generation and hashing
  - JWT access / refresh tokens
"""
import secrets
import string
import logging
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from jwt import ExpiredSignatureError, InvalidTokenError

from app.config import settings

logger = logging.getLogger(__name__)


# ── Password hashing ─────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ── OTP ──────────────────────────────────────────────────────────────────────

def generate_otp(length: int | None = None) -> str:
    """Cryptographically secure N-digit numeric OTP (OTP_LENGTH digits unless given)."""
    digits = string.digits
    return "".join(secrets.choice(digits) for _ in range(length or settings.OTP_LENGTH))


def hash_otp(otp: str) -> str:
    """Store OTPs hashed — never in plaintext."""
    return bcrypt.hashpw(otp.encode(), bcrypt.gensalt(rounds=10)).decode()


def verify_otp(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


def otp_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=settings.OTP_EXPIRE_MINUTES)


# ── JWT ──────────────────────────────────────────────────────────────────────

def create_access_token(investor_id: str, email: str) -> str:
    payload = {
        "sub": investor_id,
        "email": email,
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(investor_id: str) -> str:
    payload = {
        "sub": investor_id,
        "type": "refresh",
        "exp": datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """
    Returns decoded payload.
    Raises jwt.ExpiredSignatureError or jwt.InvalidTokenError on failure.
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
