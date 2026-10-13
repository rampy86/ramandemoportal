"""
DataIntelligence — Market & M&A Intelligence Portal Backend
FastAPI + email OTP MFA + JWT Auth.
Also serves the single-page frontend (frontend/index.html) at "/" so the whole
prototype runs as ONE web service on a free host.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db
from app.routers import auth, documents

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting DataIntelligence Portal API...")
    await init_db()
    if settings.SEED_DEMO_DATA:
        from app.seed_data import seed_demo_data
        await seed_demo_data()
    logger.info("Email provider: %s | demo OTP on screen: %s",
                settings.email_provider, settings.DEMO_SHOW_OTP)
    if settings.SECRET_KEY.startswith("dev-only"):
        logger.warning("SECRET_KEY is the insecure default — set a real one in your host's environment!")
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title="DataIntelligence Portal API",
    version="1.1.0",
    description="Backend for the DataIntelligence market & M&A intelligence portal with MFA",
    lifespan=lifespan,
)

_origins = settings.allowed_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials="*" not in _origins,   # browsers reject credentials with a wildcard origin
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(documents.router, prefix="/api/documents", tags=["Documents"])


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "service": "meridian-portal-api",
        "email_provider": settings.email_provider,
        "demo_otp": settings.DEMO_SHOW_OTP,
    }


# Must be mounted LAST so it doesn't shadow /api/* and /docs
if settings.SERVE_FRONTEND and (FRONTEND_DIR / "index.html").exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
