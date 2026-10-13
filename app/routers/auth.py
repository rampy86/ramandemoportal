"""
Auth router — two ways to sign in:

  A) Email + password (no code)
     POST /api/auth/login-password  — validate credentials, return JWT tokens

  B) Email one-time code (passwordless; new emails can self-register)
     POST /api/auth/request-otp     — email a 6-digit code (creates the account if
                                      ALLOW_OTP_SIGNUP=true and the email is new)
     POST /api/auth/verify-mfa      — validate the code, return JWT tokens

  Also:
     POST /api/auth/login           — password + emailed code (2-step MFA, kept for compatibility)
     POST /api/auth/set-password    — signed-in user sets/changes their password
     POST /api/auth/refresh         — refresh access token
     GET  /api/auth/me              — current investor profile
     POST /api/auth/logout          — audit log entry (client drops tokens)
"""
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.email_service import send_mfa_email
from app.models import AuditLog, Investor, InvestorStatus, OTPCode
from app.schemas import (
    LoginRequest, MFARequest, MFASentResponse, OTPRequest, SetPasswordRequest,
    RefreshRequest, TokenResponse, InvestorProfile,
)
from app.security import (
    create_access_token, create_refresh_token, decode_token,
    generate_otp, hash_otp, hash_password, otp_expiry, verify_otp, verify_password,
)

router = APIRouter()
bearer = HTTPBearer()
logger = logging.getLogger(__name__)

OTP_RESEND_SECONDS = 30


def _mask_email(email: str) -> str:
    local, domain = email.split("@", 1)
    return local[:2] + "***@" + domain


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes even for timezone=True columns — treat them as UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    return forwarded.split(",")[0].strip() if forwarded else request.client.host


async def _log(db: AsyncSession, investor_id: str | None, action: str,
               detail: str | None, request: Request):
    db.add(AuditLog(
        investor_id=investor_id,
        action=action,
        detail=detail,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("User-Agent", "")[:300],
    ))


async def _get_investor(db: AsyncSession, email: str) -> Investor | None:
    result = await db.execute(select(Investor).where(Investor.email == email))
    return result.scalar_one_or_none()


def _check_usable(investor: Investor) -> None:
    if investor.status != InvestorStatus.active and investor.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Account is not active. Contact Investor Relations.")
    locked_until = _aware(investor.otp_locked_until)
    if locked_until and locked_until > datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="Account temporarily locked due to too many failed attempts.")


def _tokens(investor: Investor) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(investor.id, investor.email),
        refresh_token=create_refresh_token(investor.id),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


def _name_from_email(email: str) -> str:
    local = email.split("@", 1)[0]
    words = [w for w in re.split(r"[._\-+]+", local) if w and not w.isdigit()]
    return " ".join(w.capitalize() for w in words) or "New Investor"


async def _new_investor_code(db: AsyncSession) -> str:
    for _ in range(20):
        code = f"MCP-LP-{secrets.randbelow(9000) + 1000}"
        exists = (await db.execute(select(Investor).where(Investor.investor_code == code))).scalar_one_or_none()
        if not exists:
            return code
    return f"MCP-LP-{secrets.token_hex(3).upper()}"


async def _issue_otp(db: AsyncSession, investor: Investor, request: Request) -> MFASentResponse:
    """Create, store (hashed) and email a login code. Shared by /login and /request-otp."""
    # Throttle: one code per OTP_RESEND_SECONDS per investor
    recent_cutoff = otp_expiry() - timedelta(seconds=OTP_RESEND_SECONDS)
    recent = (await db.execute(
        select(OTPCode).where(
            OTPCode.investor_id == investor.id,
            OTPCode.purpose == "login",
            OTPCode.expires_at > recent_cutoff,
        ).limit(1)
    )).scalar_one_or_none()
    if recent:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail=f"A code was just sent. Please wait {OTP_RESEND_SECONDS} seconds before requesting another.")

    otp = generate_otp()
    db.add(OTPCode(
        investor_id=investor.id,
        code_hash=hash_otp(otp),
        purpose="login",
        expires_at=otp_expiry(),
        ip_address=_client_ip(request),
    ))
    await _log(db, investor.id, "otp_sent", None, request)

    # Send email in a worker thread so the event loop isn't blocked
    sent = await run_in_threadpool(send_mfa_email, investor.email, investor.full_name, otp)
    if not sent and not settings.DEMO_SHOW_OTP:
        logger.error(f"Failed to send OTP email to {investor.email}")
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Could not send the verification email. Please try again.")

    return MFASentResponse(
        message=("Verification code sent to your email address." if sent
                 else "Email delivery is not configured — demo code shown on screen."),
        email_masked=_mask_email(investor.email),
        delivery="email" if sent else "console",
        demo_otp=otp if settings.DEMO_SHOW_OTP else None,
    )


async def _password_ok_or_401(db: AsyncSession, investor: Investor | None, body: LoginRequest,
                              request: Request) -> Investor:
    if not investor or not verify_password(body.password, investor.hashed_password):
        await _log(db, investor.id if investor else None, "login_failed", f"email={body.email}", request)
        await db.commit()   # persist audit entry before the error response rolls back the session
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Incorrect email or password.")
    return investor


# ── Option A: email + password → tokens ──────────────────────────────────────

@router.post("/login-password", response_model=TokenResponse)
async def login_password(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    investor = await _password_ok_or_401(db, await _get_investor(db, body.email), body, request)
    _check_usable(investor)
    investor.last_login_at = datetime.now(timezone.utc)
    await _log(db, investor.id, "login_success", "method=password", request)
    return _tokens(investor)


# ── Option B: email one-time code (passwordless, self sign-up) ───────────────

@router.post("/request-otp", response_model=MFASentResponse)
async def request_otp(body: OTPRequest, request: Request, db: AsyncSession = Depends(get_db)):
    investor = await _get_investor(db, body.email)
    if not investor:
        if not settings.ALLOW_OTP_SIGNUP:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="No investor account uses this email. Contact Investor Relations.")
        investor = Investor(
            investor_code=await _new_investor_code(db),
            full_name=_name_from_email(body.email),
            email=body.email,
            # unusable random password until the user sets one in Settings
            hashed_password=hash_password(secrets.token_urlsafe(32)),
            entity_name=None,
            investor_type="Institutional LP",
            status=InvestorStatus.active,
            mfa_enabled=True,
            mfa_email=True,
        )
        db.add(investor)
        await db.flush()
        await _log(db, investor.id, "signup_otp", None, request)
    _check_usable(investor)
    return await _issue_otp(db, investor, request)


# ── Legacy 2-step: password, then emailed code ───────────────────────────────

@router.post("/login", response_model=MFASentResponse, status_code=status.HTTP_200_OK)
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    investor = await _password_ok_or_401(db, await _get_investor(db, body.email), body, request)
    _check_usable(investor)
    return await _issue_otp(db, investor, request)


# ── Step 2: Verify MFA — validate OTP, return tokens ─────────────────────────

@router.post("/verify-mfa", response_model=TokenResponse, status_code=status.HTTP_200_OK)
async def verify_mfa(
    body: MFARequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Investor).where(Investor.email == body.email))
    investor = result.scalar_one_or_none()
    if not investor:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid request.")

    locked_until = _aware(investor.otp_locked_until)
    if locked_until and locked_until > datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="Account temporarily locked due to too many failed attempts.")

    # Fetch latest unused login OTP for this investor
    otp_result = await db.execute(
        select(OTPCode)
        .where(
            OTPCode.investor_id == investor.id,
            OTPCode.purpose == "login",
            OTPCode.used == False,          # noqa: E712
            OTPCode.expires_at > datetime.now(timezone.utc),
        )
        .order_by(OTPCode.created_at.desc())
        .limit(1)
    )
    otp_record = otp_result.scalar_one_or_none()

    if not otp_record or not verify_otp(body.otp_code, otp_record.code_hash):
        # Increment failed attempts
        investor.failed_otp_attempts = (investor.failed_otp_attempts or 0) + 1
        locked = investor.failed_otp_attempts >= settings.MAX_OTP_ATTEMPTS
        if locked:
            investor.otp_locked_until = datetime.now(timezone.utc) + timedelta(minutes=30)
            investor.failed_otp_attempts = 0
            # burn outstanding codes so a locked account can't keep guessing
            if otp_record:
                otp_record.used = True
            await _log(db, investor.id, "otp_locked", "Too many failed attempts", request)
        await _log(db, investor.id, "otp_failed", None, request)
        await db.commit()   # persist the attempt counter — the error response would otherwise roll it back
        if locked:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                                detail="Too many failed attempts. Account locked for 30 minutes.")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired verification code.")

    # Success — mark OTP used, reset counters
    otp_record.used = True
    investor.failed_otp_attempts = 0
    investor.otp_locked_until = None
    investor.last_login_at = datetime.now(timezone.utc)
    await _log(db, investor.id, "login_success", "method=email_code", request)

    access_token  = create_access_token(investor.id, investor.email)
    refresh_token = create_refresh_token(investor.id)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ── Refresh token ─────────────────────────────────────────────────────────────

@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        payload = decode_token(body.refresh_token)
        if payload.get("type") != "refresh":
            raise ValueError("Wrong token type")
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired refresh token.")

    result = await db.execute(select(Investor).where(Investor.id == payload["sub"]))
    investor = result.scalar_one_or_none()
    if not investor or investor.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Investor not found.")

    return TokenResponse(
        access_token=create_access_token(investor.id, investor.email),
        refresh_token=create_refresh_token(investor.id),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ── Dependency: get current investor from Bearer token ───────────────────────

async def get_current_investor(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
    db: AsyncSession = Depends(get_db),
) -> Investor:
    token = credentials.credentials
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise ValueError
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired token.")
    result = await db.execute(select(Investor).where(Investor.id == payload["sub"]))
    investor = result.scalar_one_or_none()
    if not investor or investor.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Investor not found.")
    return investor


# ── Profile ───────────────────────────────────────────────────────────────────

@router.get("/me", response_model=InvestorProfile)
async def get_me(current: Annotated[Investor, Depends(get_current_investor)]):
    return current


@router.post("/set-password", status_code=status.HTTP_204_NO_CONTENT)
async def set_password(
    body: SetPasswordRequest,
    request: Request,
    current: Annotated[Investor, Depends(get_current_investor)],
    db: AsyncSession = Depends(get_db),
):
    """Signed-in investor sets (or changes) the password used for email + password sign-in."""
    current.hashed_password = hash_password(body.new_password)
    await _log(db, current.id, "password_set", None, request)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    current: Annotated[Investor, Depends(get_current_investor)],
    db: AsyncSession = Depends(get_db),
):
    await _log(db, current.id, "logout", None, request)
