"""POST /extract — enqueue a PDF extraction job."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

import jsonschema
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status

from app.api.v1.schemas import ExtractJobCreated
from app.core.config import get_settings
from app.core.database import get_async_supabase_client, get_supabase_client
from app.middleware.auth import get_current_client
from app.services.extractor import validate_user_schema
from app.services.storage import upload_job_pdf
from app.workers.tasks import process_extraction

logger = logging.getLogger(__name__)

router = APIRouter(tags=["extract"])

_MAX_PDF_BYTES = 25 * 1024 * 1024  # 25 MiB soft limit for uploads


def _parse_target_schema(raw_schema: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_schema)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"schema must be valid JSON: {exc.msg}",
        ) from exc
    if not isinstance(parsed, dict) or not parsed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="schema must be a non-empty JSON object",
        )
    try:
        validate_user_schema(parsed)
    except jsonschema.SchemaError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid JSON Schema: {exc.message}",
        ) from exc
    return parsed


async def _read_pdf(file: UploadFile) -> bytes:
    filename = (file.filename or "").lower()
    content_type = (file.content_type or "").lower()
    is_pdf = (
        content_type in {"application/pdf", "application/x-pdf"}
        or filename.endswith(".pdf")
    )
    if not is_pdf:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="file must be a PDF",
        )

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="file must not be empty",
        )
    if len(pdf_bytes) > _MAX_PDF_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"PDF exceeds maximum size of {_MAX_PDF_BYTES} bytes",
        )
    if not pdf_bytes.startswith(b"%PDF"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="file does not look like a valid PDF",
        )
    return pdf_bytes


def _create_pending_job(
    *,
    job_id: str,
    client_id: str,
    object_path: str,
    target_schema: dict[str, Any],
    notification_email: str | None,
    pdf_bytes: bytes,
) -> None:
    """Upload PDF and insert PENDING job using the sync Supabase client."""
    settings = get_settings()
    supabase = get_supabase_client(settings)
    upload_job_pdf(
        supabase,
        object_path,
        pdf_bytes,
        content_type="application/pdf",
    )
    supabase.table("extraction_jobs").insert(
        {
            "id": job_id,
            "client_id": client_id,
            "status": "PENDING",
            "file_path": object_path,
            "target_schema": target_schema,
            "notification_email": notification_email,
        }
    ).execute()


@router.post(
    "/extract",
    response_model=ExtractJobCreated,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_extraction_job(
    request: Request,
    file: UploadFile = File(..., description="PDF document to extract"),
    target_schema_json: str = Form(
        ...,
        alias="schema",
        description="Target JSON Schema as a JSON string",
    ),
    notification_email: str | None = Form(
        None,
        description="Optional email notified when the job completes",
    ),
    email: str | None = Form(
        None,
        description="Alias for notification_email",
    ),
) -> ExtractJobCreated:
    """Validate inputs, store the PDF, enqueue Celery extraction, return job id."""
    client = get_current_client(request)
    target_schema = _parse_target_schema(target_schema_json)
    pdf_bytes = await _read_pdf(file)

    notify = (notification_email or email or "").strip() or None
    if notify and "@" not in notify:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="notification_email must be a valid email address",
        )

    job_id = str(uuid.uuid4())
    object_path = f"{client.client_id}/{job_id}.pdf"

    try:
        await asyncio.to_thread(
            _create_pending_job,
            job_id=job_id,
            client_id=client.client_id,
            object_path=object_path,
            target_schema=target_schema,
            notification_email=notify,
            pdf_bytes=pdf_bytes,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to create extraction job %s", job_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to create extraction job",
        ) from exc

    try:
        process_extraction.delay(job_id)
    except Exception as exc:
        logger.exception("Failed to dispatch Celery task for job %s", job_id)
        try:
            supabase = await get_async_supabase_client()
            await (
                supabase.table("extraction_jobs")
                .update(
                    {
                        "status": "FAILED",
                        "error_message": "Failed to enqueue extraction worker",
                    }
                )
                .eq("id", job_id)
                .execute()
            )
        except Exception:
            logger.exception(
                "Failed to mark job %s as FAILED after enqueue error", job_id
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to enqueue extraction job",
        ) from exc

    return ExtractJobCreated(job_id=job_id, status="queued")
