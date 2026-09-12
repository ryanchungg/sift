"""Celery tasks for asynchronous document extraction."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.core.config import get_settings
from app.core.database import get_supabase_client
from app.services.email import send_extraction_complete_email
from app.services.extractor import extract_structured_json
from app.services.storage import download_job_pdf, estimate_pdf_page_count
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_job(supabase: Any, job_id: str) -> dict[str, Any]:
    result = (
        supabase.table("extraction_jobs")
        .select("*")
        .eq("id", job_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    if not rows:
        raise ValueError(f"extraction_jobs row not found: {job_id}")
    return rows[0]


def _update_job(supabase: Any, job_id: str, values: dict[str, Any]) -> None:
    (
        supabase.table("extraction_jobs")
        .update(values)
        .eq("id", job_id)
        .execute()
    )


def _insert_usage_log(
    supabase: Any,
    *,
    client_id: str | None,
    job_id: str,
    pages_processed: int,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    payload: dict[str, Any] = {
        "job_id": job_id,
        "pages_processed": pages_processed,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }
    if client_id:
        payload["client_id"] = client_id
    supabase.table("usage_logs").insert(payload).execute()


@celery_app.task(name="app.workers.tasks.ping")
def ping() -> str:
    """Health-check task used to verify the worker is reachable."""
    return "pong"


@celery_app.task(
    name="app.workers.tasks.process_extraction",
    bind=True,
    max_retries=2,
    default_retry_delay=15,
)
def process_extraction(self, job_id: str) -> dict[str, Any]:
    """Load a job, extract structured JSON via Gemini, persist results, email.

    Flow:
      1. Mark job PROCESSING
      2. Download PDF from Supabase Storage
      3. Call Gemini with the job's target_schema
      4. Write result + usage_logs, mark COMPLETED
      5. If notification_email is set, send a Resend completion email

    On failure the job is marked FAILED (with error_message) and a failure
    email is sent when notification_email is present.
    """
    settings = get_settings()
    supabase = get_supabase_client(settings)

    try:
        job = _load_job(supabase, job_id)
    except Exception as exc:
        logger.exception("Failed to load job %s", job_id)
        return {"job_id": job_id, "status": "FAILED", "error": str(exc)}

    notification_email = job.get("notification_email")
    client_id = job.get("client_id")
    target_schema = job.get("target_schema") or {}
    if not isinstance(target_schema, dict):
        target_schema = {}

    _update_job(
        supabase,
        job_id,
        {"status": "PROCESSING", "error_message": None},
    )

    try:
        pdf_bytes = download_job_pdf(supabase, job.get("file_path"))
        pages_processed = estimate_pdf_page_count(pdf_bytes)

        extraction = extract_structured_json(
            pdf_bytes,
            target_schema,
            settings=settings,
        )

        _update_job(
            supabase,
            job_id,
            {
                "status": "COMPLETED",
                "result": extraction.data,
                "error_message": None,
                "completed_at": _utcnow_iso(),
            },
        )
        _insert_usage_log(
            supabase,
            client_id=str(client_id) if client_id else None,
            job_id=job_id,
            pages_processed=pages_processed,
            prompt_tokens=extraction.prompt_tokens,
            completion_tokens=extraction.completion_tokens,
        )

        if notification_email:
            try:
                send_extraction_complete_email(
                    to_email=notification_email,
                    job_id=job_id,
                    status="COMPLETED",
                    result_preview=extraction.data,
                    settings=settings,
                )
            except Exception:
                logger.exception(
                    "Failed to send completion email for job %s", job_id
                )

        return {
            "job_id": job_id,
            "status": "COMPLETED",
            "prompt_tokens": extraction.prompt_tokens,
            "completion_tokens": extraction.completion_tokens,
            "pages_processed": pages_processed,
        }
    except Exception as exc:
        logger.exception("Extraction failed for job %s", job_id)
        error_message = str(exc)
        try:
            _update_job(
                supabase,
                job_id,
                {
                    "status": "FAILED",
                    "error_message": error_message[:2000],
                    "completed_at": _utcnow_iso(),
                },
            )
        except Exception:
            logger.exception("Failed to persist FAILED status for job %s", job_id)

        if notification_email:
            try:
                send_extraction_complete_email(
                    to_email=notification_email,
                    job_id=job_id,
                    status="FAILED",
                    error_message=error_message[:500],
                    settings=settings,
                )
            except Exception:
                logger.exception(
                    "Failed to send failure email for job %s", job_id
                )

        # Do not retry schema/validation errors; retry transient backend issues.
        retryable = not isinstance(exc, ValueError)
        if retryable:
            try:
                raise self.retry(exc=exc)
            except self.MaxRetriesExceededError:
                pass

        return {
            "job_id": job_id,
            "status": "FAILED",
            "error": error_message[:500],
        }
