"""
Demo seed data — investors + sample documents.

Runs on startup when SEED_DEMO_DATA=true (default), and from `python seed.py`.
Idempotent: existing investors / documents (matched by email / title) are skipped,
so it is safe on hosts with an ephemeral disk that restart often.
"""
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal, init_db
from app.models import Document, DocumentCategory, Investor, InvestorStatus
from app.security import hash_password

logger = logging.getLogger(__name__)

UPLOAD_DIR = Path("./uploads")

DEMO_INVESTORS = [
    {
        "investor_code": "MCP-LP-2847",
        "full_name": "James Whitfield",
        "email": "j.whitfield@meridian.com",
        "entity_name": "Whitfield Family Office LLC",
        "investor_type": "Institutional LP",
    },
    {
        "investor_code": "MCP-LP-2848",
        "full_name": "Raman Dandona",
        "email": "raman.dandona@aithonsolutions.com",
        "entity_name": "Aithon Solutions",
        "investor_type": "Institutional LP",
    },
]

# (title, display file_type, category, fund, published YYYY-MM-DD)
# Every sample is generated as a small PDF; file_type only drives the icon in the UI.
DEMO_DOCUMENTS = [
    ("Q3 2026 Quarterly Report — PE Fund VI", "pdf", "report", "PE Fund VI", "2026-10-01"),
    ("Q3 2026 Quarterly Report — Real Assets IV", "pdf", "report", "Real Assets IV", "2026-10-01"),
    ("Q3 2026 Quarterly Report — Infra II", "pdf", "report", "Infra II", "2026-10-01"),
    ("Capital Call Notice — Real Assets IV ($2.4M)", "pdf", "notice", "Real Assets IV", "2026-09-28"),
    ("LPA Amendment No. 3 — Infra II", "docx", "legal", "Infra II", "2026-09-15"),
    ("Distribution Notice — Infra II ($420K)", "pdf", "notice", "Infra II", "2026-09-18"),
    ("Q2 2026 Investor Presentation", "pptx", "presentation", "All Funds", "2026-07-12"),
    ("K-1 Tax Package 2025 — All Funds", "xlsx", "tax", "All Funds", "2026-04-15"),
    ("Q1 2026 Quarterly Report — Absolute Return HF", "pdf", "report", "Absolute Return HF", "2026-04-05"),
    ("Annual Report 2025 — Meridian PE Fund VI", "pdf", "report", "PE Fund VI", "2026-03-30"),
    ("Subscription Agreement — PE Fund VI", "docx", "legal", "PE Fund VI", "2021-01-03"),
    ("Side Letter Agreement — Whitfield Family Office", "docx", "legal", "General", "2017-03-12"),
]


def _pdf_escape(text: str) -> str:
    text = text.replace("—", "-").replace("’", "'")
    text = text.encode("latin-1", "replace").decode("latin-1")
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_placeholder_pdf(title: str, fund: str, category: str, date: str) -> bytes:
    """Build a small, valid one-page PDF (correct xref offsets) with no dependencies."""
    lines = [
        ("F2", 20, "Meridian Capital - Investor Portal"),
        ("F2", 14, title),
        ("F1", 11, f"Fund: {fund}"),
        ("F1", 11, f"Category: {category}"),
        ("F1", 11, f"Date: {date}"),
        ("F1", 11, ""),
        ("F1", 10, "Sample document generated for the prototype. Contains no real financial data."),
    ]
    stream_lines = ["BT", "50 780 Td"]
    first = True
    for font, size, text in lines:
        if not first:
            stream_lines.append(f"0 -{int(size * 2)} Td")
        first = False
        stream_lines.append(f"/{font} {size} Tf ({_pdf_escape(text)}) Tj")
    stream_lines.append("ET")
    stream = "\n".join(stream_lines).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


async def seed_demo_data(verbose: bool = False) -> None:
    await init_db()
    UPLOAD_DIR.mkdir(exist_ok=True)

    investors = list(DEMO_INVESTORS)
    if settings.DEMO_EXTRA_EMAIL:
        investors.append({
            "investor_code": "MCP-LP-2900",
            "full_name": settings.DEMO_EXTRA_NAME,
            "email": settings.DEMO_EXTRA_EMAIL.strip().lower(),
            "entity_name": "Demo Entity LLC",
            "investor_type": "Institutional LP",
        })

    async with AsyncSessionLocal() as db:
        for data in investors:
            exists = (await db.execute(select(Investor).where(Investor.email == data["email"]))).scalar_one_or_none()
            if exists:
                continue
            db.add(Investor(
                **data,
                hashed_password=hash_password(settings.DEMO_PASSWORD),
                status=InvestorStatus.active,
                mfa_enabled=True,
                mfa_email=True,
            ))
            if verbose:
                print(f"  ✓ Created investor: {data['email']}")

        for title, ftype, cat, fund, date in DEMO_DOCUMENTS:
            existing = (await db.execute(select(Document).where(Document.title == title))).scalar_one_or_none()
            # Re-create the file if the row exists but the ephemeral disk was wiped
            if existing and existing.local_path and Path(existing.local_path).exists():
                continue
            pdf = make_placeholder_pdf(title, fund, cat, date)
            path = UPLOAD_DIR / f"seed-{uuid.uuid5(uuid.NAMESPACE_URL, title)}.pdf"
            path.write_bytes(pdf)
            if existing:
                existing.local_path = str(path)
                existing.s3_key = None
                continue
            db.add(Document(
                title=title,
                original_filename=re.sub(r"[^\w\-. ()$]", "-", title.replace("—", "-")) + ".pdf",
                file_type=ftype,
                file_size_bytes=len(pdf),
                category=DocumentCategory(cat),
                fund_name=fund,
                local_path=str(path),
                published_at=datetime.fromisoformat(date).replace(tzinfo=timezone.utc),
            ))
        await db.commit()
    logger.info("Demo data seeded.")
