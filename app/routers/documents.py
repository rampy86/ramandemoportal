"""
Documents router:
  GET  /api/documents          — list documents for current investor
  POST /api/documents/upload   — upload a file (local or S3)
  GET  /api/documents/{id}/download — get presigned S3 URL (or stream local file)
  DELETE /api/documents/{id}   — soft-delete (admin/uploader only)
"""
import logging
import os
import uuid
from pathlib import Path
from typing import Annotated, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import AuditLog, Document, DocumentCategory
from app.routers.auth import get_current_investor
from app.schemas import DocumentOut, DocumentUploadMeta

router = APIRouter()
logger = logging.getLogger(__name__)

UPLOAD_DIR = Path("./uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".zip"}
MAX_FILE_SIZE_MB = 50


def _s3_client():
    if not settings.AWS_ACCESS_KEY_ID:
        return None
    return boto3.client(
        "s3",
        region_name=settings.AWS_REGION,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    )


def _presigned_url(s3_key: str) -> Optional[str]:
    s3 = _s3_client()
    if not s3 or not settings.S3_BUCKET_NAME:
        return None
    try:
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.S3_BUCKET_NAME, "Key": s3_key},
            ExpiresIn=settings.S3_PRESIGNED_URL_EXPIRE,
        )
    except (BotoCoreError, ClientError) as exc:
        logger.error(f"Could not generate presigned URL for {s3_key}: {exc}")
        return None


# ── List documents ────────────────────────────────────────────────────────────

@router.get("", response_model=list[DocumentOut])
async def list_documents(
    current=Depends(get_current_investor),
    db: AsyncSession = Depends(get_db),
    category: Optional[DocumentCategory] = None,
    fund_name: Optional[str] = None,
):
    q = select(Document).where(Document.visible_to_all == True)  # noqa: E712
    if category:
        q = q.where(Document.category == category)
    if fund_name:
        q = q.where(Document.fund_name == fund_name)
    q = q.order_by(func.coalesce(Document.published_at, Document.created_at).desc())

    result = await db.execute(q)
    docs = result.scalars().all()

    out = []
    for doc in docs:
        d = DocumentOut.model_validate(doc)
        if doc.s3_key:
            d.download_url = _presigned_url(doc.s3_key)
        out.append(d)
    return out


# ── Upload ────────────────────────────────────────────────────────────────────

@router.post("/upload", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    category: DocumentCategory = Form(DocumentCategory.other),
    fund_name: str = Form("General"),
    current=Depends(get_current_investor),
    db: AsyncSession = Depends(get_db),
):
    # Validate extension
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"File type '{suffix}' not allowed.")

    # Read and size-check
    content = await file.read()
    size_mb = len(content) / 1024 / 1024
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail=f"File exceeds {MAX_FILE_SIZE_MB} MB limit.")

    safe_name = f"{uuid.uuid4()}{suffix}"
    doc_title = title or Path(file.filename).stem
    s3_key = None
    local_path = None

    s3 = _s3_client()
    if s3 and settings.S3_BUCKET_NAME:
        # Upload to S3
        s3_key = f"documents/{safe_name}"
        try:
            s3.put_object(
                Bucket=settings.S3_BUCKET_NAME,
                Key=s3_key,
                Body=content,
                ContentType=file.content_type or "application/octet-stream",
                ContentDisposition=f'attachment; filename="{file.filename}"',
            )
            logger.info(f"Uploaded {file.filename} → s3://{settings.S3_BUCKET_NAME}/{s3_key}")
        except (BotoCoreError, ClientError) as exc:
            logger.error(f"S3 upload failed: {exc}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                                detail="File storage error. Please try again.")
    else:
        # Fallback: save locally
        local_path = str(UPLOAD_DIR / safe_name)
        with open(local_path, "wb") as f:
            f.write(content)
        logger.info(f"Saved locally: {local_path}")

    doc = Document(
        title=doc_title,
        original_filename=file.filename,
        file_type=suffix.lstrip("."),
        file_size_bytes=len(content),
        category=category,
        fund_name=fund_name,
        s3_key=s3_key,
        local_path=local_path,
        uploaded_by_id=current.id,
    )
    db.add(doc)
    db.add(AuditLog(
        investor_id=current.id,
        action="doc_upload",
        detail=f"{file.filename} → {category} / {fund_name}",
        ip_address=request.headers.get("X-Forwarded-For", request.client.host),
    ))
    await db.flush()

    out = DocumentOut.model_validate(doc)
    if s3_key:
        out.download_url = _presigned_url(s3_key)
    return out


# ── Download ──────────────────────────────────────────────────────────────────

@router.get("/{doc_id}/download")
async def download_document(
    doc_id: str,
    request: Request,
    current=Depends(get_current_investor),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    db.add(AuditLog(
        investor_id=current.id,
        action="doc_download",
        detail=f"doc_id={doc_id} title={doc.title}",
        ip_address=request.headers.get("X-Forwarded-For", request.client.host),
    ))

    # S3 — redirect to presigned URL
    if doc.s3_key:
        url = _presigned_url(doc.s3_key)
        if not url:
            raise HTTPException(status_code=500, detail="Could not generate download link.")
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=url)

    # Local fallback
    if doc.local_path and os.path.exists(doc.local_path):
        return FileResponse(
            path=doc.local_path,
            filename=doc.original_filename,
            media_type="application/octet-stream",
        )

    raise HTTPException(status_code=404, detail="File not found in storage.")
