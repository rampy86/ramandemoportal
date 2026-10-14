"""
Pydantic v2 request / response schemas.
"""
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional
from datetime import datetime
from app.models import DocumentCategory


# ── Auth ─────────────────────────────────────────────────────────────────────

def _lower(v: str) -> str:
    return v.strip().lower()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)

    _norm = field_validator("email", mode="after")(_lower)


class PasswordLoginRequest(LoginRequest):
    """Password sign-in with the 4-digit MFA code emailed by /password-mfa."""
    mfa_code: str = Field(pattern=r"^\d{4}$")


class OTPRequest(BaseModel):
    email: EmailStr

    _norm = field_validator("email", mode="after")(_lower)


class SetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


class MFARequest(BaseModel):
    email: EmailStr

    _norm = field_validator("email", mode="after")(_lower)
    otp_code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")

    @field_validator("otp_code")
    @classmethod
    def must_be_digits(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("OTP must be 6 digits")
        return v


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int   # seconds


class MFASentResponse(BaseModel):
    message: str
    email_masked: str    # e.g. ra***@aithonsolutions.com
    delivery: str = "email"            # email | console
    demo_otp: Optional[str] = None     # only when DEMO_SHOW_OTP=true (prototype only)
    delivery_error: Optional[str] = None   # why email failed — only when DEMO_SHOW_OTP=true


class RefreshRequest(BaseModel):
    refresh_token: str


# ── Investor ──────────────────────────────────────────────────────────────────

class InvestorProfile(BaseModel):
    id: str
    investor_code: Optional[str]
    full_name: str
    email: str
    entity_name: Optional[str]
    investor_type: Optional[str]
    status: str
    mfa_enabled: bool
    created_at: datetime
    last_login_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ── Documents ────────────────────────────────────────────────────────────────

class DocumentOut(BaseModel):
    id: str
    title: str
    original_filename: str
    file_type: str
    file_size_bytes: int
    category: DocumentCategory
    fund_name: str
    created_at: datetime
    published_at: Optional[datetime] = None
    download_url: Optional[str] = None   # Pre-signed S3 URL (populated on request)

    model_config = {"from_attributes": True}


class DocumentUploadMeta(BaseModel):
    title: Optional[str] = None
    category: DocumentCategory = DocumentCategory.other
    fund_name: str = "General"


# ── Error ─────────────────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    detail: str
