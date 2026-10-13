"""
Database models: Investor, OTPCode, Document, AuditLog
"""
from sqlalchemy import (
    Column, String, Boolean, DateTime, Integer,
    ForeignKey, Text, Enum as SAEnum
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid
import enum


def new_uuid():
    return str(uuid.uuid4())


class InvestorStatus(str, enum.Enum):
    active = "active"
    suspended = "suspended"
    pending = "pending"


class DocumentCategory(str, enum.Enum):
    report = "report"
    legal = "legal"
    notice = "notice"
    tax = "tax"
    presentation = "presentation"
    other = "other"


# ── Investor (user) ──────────────────────────────────────────────────────────

class Investor(Base):
    __tablename__ = "investors"

    id              = Column(String, primary_key=True, default=new_uuid)
    investor_code   = Column(String(20), unique=True, index=True)   # e.g. MCP-LP-2847
    full_name       = Column(String(120), nullable=False)
    email           = Column(String(200), unique=True, index=True, nullable=False)
    hashed_password = Column(String(200), nullable=False)
    entity_name     = Column(String(200))
    investor_type   = Column(String(80), default="LP")
    status          = Column(SAEnum(InvestorStatus), default=InvestorStatus.active)

    # MFA settings
    mfa_enabled     = Column(Boolean, default=True)
    mfa_email       = Column(Boolean, default=True)   # send code via email
    failed_otp_attempts = Column(Integer, default=0)
    otp_locked_until    = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    last_login_at   = Column(DateTime(timezone=True), nullable=True)

    otp_codes  = relationship("OTPCode",  back_populates="investor", cascade="all, delete-orphan")
    documents  = relationship("Document", back_populates="uploaded_by", foreign_keys="Document.uploaded_by_id")
    audit_logs = relationship("AuditLog", back_populates="investor", cascade="all, delete-orphan")


# ── OTP Code ─────────────────────────────────────────────────────────────────

class OTPCode(Base):
    __tablename__ = "otp_codes"

    id           = Column(String, primary_key=True, default=new_uuid)
    investor_id  = Column(String, ForeignKey("investors.id", ondelete="CASCADE"), nullable=False)
    code_hash    = Column(String(200), nullable=False)  # bcrypt hash of the 6-digit code
    purpose      = Column(String(40), default="login")  # login | password_reset
    used         = Column(Boolean, default=False)
    expires_at   = Column(DateTime(timezone=True), nullable=False)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    ip_address   = Column(String(50), nullable=True)

    investor = relationship("Investor", back_populates="otp_codes")


# ── Document ─────────────────────────────────────────────────────────────────

class Document(Base):
    __tablename__ = "documents"

    id               = Column(String, primary_key=True, default=new_uuid)
    title            = Column(String(300), nullable=False)
    original_filename = Column(String(300), nullable=False)
    file_type        = Column(String(10), nullable=False)     # pdf, docx, xlsx …
    file_size_bytes  = Column(Integer, default=0)
    category         = Column(SAEnum(DocumentCategory), default=DocumentCategory.other)
    fund_name        = Column(String(200), default="General")
    s3_key           = Column(String(500), nullable=True)     # S3 object key
    local_path       = Column(String(500), nullable=True)     # fallback for local dev
    uploaded_by_id   = Column(String, ForeignKey("investors.id"), nullable=True)
    visible_to_all   = Column(Boolean, default=True)
    published_at     = Column(DateTime(timezone=True), nullable=True)  # display date (e.g. report date)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
    updated_at       = Column(DateTime(timezone=True), onupdate=func.now())

    uploaded_by = relationship("Investor", back_populates="documents", foreign_keys=[uploaded_by_id])


# ── Audit Log ─────────────────────────────────────────────────────────────────

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id          = Column(String, primary_key=True, default=new_uuid)
    investor_id = Column(String, ForeignKey("investors.id", ondelete="SET NULL"), nullable=True)
    action      = Column(String(100), nullable=False)  # login_success, mfa_failed, doc_download …
    detail      = Column(Text, nullable=True)
    ip_address  = Column(String(50), nullable=True)
    user_agent  = Column(String(300), nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    investor = relationship("Investor", back_populates="audit_logs")
