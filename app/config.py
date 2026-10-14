"""
Configuration — all secrets come from environment variables.
Never hard-code credentials. See .env.example for required variables.
"""
import json
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── App ──────────────────────────────────────────────
    APP_NAME: str = "DataIntelligence Portal"
    SECRET_KEY: str = "dev-only-insecure-key-change-me"   # ALWAYS override in any hosted environment
    ENVIRONMENT: str = "production"
    # Accepts a JSON list '["https://a.com","https://b.com"]', a comma list 'https://a.com,https://b.com', or '*'
    ALLOWED_ORIGINS: str = "http://localhost:8000,http://localhost:5173"

    # Serve the single-page frontend (frontend/index.html) from this API at "/"
    SERVE_FRONTEND: bool = True

    # ── Demo / prototype helpers ─────────────────────────
    # SEED_DEMO_DATA: create demo investors + sample documents on startup (idempotent).
    #   Needed on free hosts with no shell access (e.g. Render free) and an ephemeral disk.
    SEED_DEMO_DATA: bool = True
    DEMO_PASSWORD: str = "ChangeMe123!"
    # Optional extra demo login so you can receive real OTP emails yourself
    DEMO_EXTRA_EMAIL: str = ""
    DEMO_EXTRA_NAME: str = "Demo Investor"
    # DEMO_SHOW_OTP: also return the OTP in the /login response so the UI can display it.
    #   PROTOTYPE ONLY — this defeats MFA. Turn off once real email delivery works.
    DEMO_SHOW_OTP: bool = True
    # ALLOW_OTP_SIGNUP: "Email code" sign-in creates an account for any new email address.
    #   Great for demos; set false to allow only existing investors.
    ALLOW_OTP_SIGNUP: bool = True

    # ── JWT ──────────────────────────────────────────────
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── MFA / OTP ────────────────────────────────────────
    OTP_EXPIRE_MINUTES: int = 10            # Code valid for 10 minutes
    OTP_LENGTH: int = 6
    MAX_OTP_ATTEMPTS: int = 5              # Lock out after 5 wrong attempts

    # ── Email delivery ───────────────────────────────────
    # EMAIL_PROVIDER: "smtp"   → Gmail/any SMTP (blocked on Render free: ports 25/465/587)
    #                 "brevo"  → Brevo HTTPS API (port 443, works on free hosts)
    #                 "console"→ don't send; log the code (use with DEMO_SHOW_OTP)
    #                 "auto"   → brevo if BREVO_API_KEY set, else smtp if SMTP creds set, else console
    EMAIL_PROVIDER: str = "auto"

    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""                     # your Gmail address
    SMTP_PASSWORD: str = ""                 # Gmail App Password (not your login password)

    BREVO_API_KEY: str = ""
    BREVO_API_URL: str = "https://api.brevo.com/v3/smtp/email"

    EMAIL_FROM_NAME: str = "DataIntelligence Support"
    EMAIL_FROM_ADDRESS: str = ""           # Defaults to SMTP_USER if blank (must be a verified sender for Brevo)

    # ── Database ─────────────────────────────────────────
    # sqlite (default) or any Postgres URL, e.g. from Neon:  postgresql://user:pw@host/db?sslmode=require
    DATABASE_URL: str = "sqlite+aiosqlite:///./meridian.db"

    # ── AWS S3 (document storage) ─────────────────────────
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "us-east-1"
    S3_BUCKET_NAME: str = ""
    S3_PRESIGNED_URL_EXPIRE: int = 3600    # 1 hour

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    @property
    def allowed_origins(self) -> List[str]:
        v = (self.ALLOWED_ORIGINS or "").strip()
        if v.startswith("["):
            items = json.loads(v)
        else:
            items = v.split(",")
        return [o.strip().rstrip("/") for o in items if o and o.strip()]

    # Values pasted into a hosting dashboard often carry stray spaces or quotes
    @field_validator("BREVO_API_KEY", "EMAIL_FROM_ADDRESS", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_PROVIDER", mode="before")
    @classmethod
    def _trim(cls, v):
        return v.strip().strip('"').strip("'").strip() if isinstance(v, str) else v

    @property
    def email_from(self) -> str:
        return self.EMAIL_FROM_ADDRESS or self.SMTP_USER

    @property
    def email_provider(self) -> str:
        p = self.EMAIL_PROVIDER.lower()
        if p != "auto":
            return p
        if self.BREVO_API_KEY:
            return "brevo"
        if self.SMTP_USER and self.SMTP_PASSWORD:
            return "smtp"
        return "console"


settings = Settings()
