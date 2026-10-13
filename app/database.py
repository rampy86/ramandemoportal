"""
Async SQLAlchemy database setup.
SQLite by default; any Postgres URL works (Neon, Supabase, Render, AWS RDS).
Plain 'postgres://' / 'postgresql://' URLs (as copied from a provider dashboard)
are converted to the asyncpg driver automatically.
"""
import logging
import ssl as _ssl
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)


def _normalise_db_url(url: str) -> tuple[str, dict]:
    """Return (sqlalchemy_url, connect_args)."""
    connect_args: dict = {}
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    if url.startswith("postgresql+asyncpg://"):
        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query))
        # asyncpg does not understand libpq params like sslmode / channel_binding
        sslmode = query.pop("sslmode", None)
        query.pop("channel_binding", None)
        if sslmode in ("require", "verify-ca", "verify-full") or "neon.tech" in parts.netloc:
            connect_args["ssl"] = _ssl.create_default_context()
        url = urlunsplit(parts._replace(query=urlencode(query)))
    return url, connect_args


_db_url, _connect_args = _normalise_db_url(settings.DATABASE_URL)

engine = create_async_engine(
    _db_url,
    echo=(settings.ENVIRONMENT == "development"),
    pool_pre_ping=True,
    connect_args=_connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def init_db():
    """Create all tables on startup."""
    from app import models  # noqa: F401 — import models so they register with Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialised (%s).", _db_url.split("://")[0])


async def get_db():
    """FastAPI dependency — yields an async DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
