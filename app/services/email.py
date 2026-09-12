"""Resend-backed completion notifications."""

from __future__ import annotations

import logging
from typing import Any

import resend

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


def send_extraction_complete_email(
    *,
    to_email: str,
    job_id: str,
    status: str,
    result_preview: dict[str, Any] | None = None,
    error_message: str | None = None,
    settings: Settings | None = None,
) -> str | None:
    """Send a job-completion email via Resend.

    Returns the Resend email id when sent, or ``None`` when email is skipped
    because credentials are missing (logged as a warning).
    """
    cfg = settings or get_settings()
    if not cfg.resend_api_key:
        logger.warning(
            "RESEND_API_KEY not configured; skipping notification for job %s",
            job_id,
        )
        return None

    resend.api_key = cfg.resend_api_key

    if status == "COMPLETED":
        subject = f"Extraction job {job_id} completed"
        preview = ""
        if result_preview is not None:
            # Keep the email body small — full payloads are retrieved via the API.
            import json

            truncated = json.dumps(result_preview, ensure_ascii=False)[:2000]
            preview = f"<pre>{truncated}</pre>"
        html = (
            f"<p>Your document extraction job <strong>{job_id}</strong> "
            f"finished with status <strong>{status}</strong>.</p>"
            f"{preview}"
            f"<p>Fetch the full result with "
            f"<code>GET /api/v1/jobs/{job_id}</code>.</p>"
        )
    else:
        subject = f"Extraction job {job_id} failed"
        detail = error_message or "Unknown error"
        html = (
            f"<p>Your document extraction job <strong>{job_id}</strong> "
            f"failed.</p><p>Error: {detail}</p>"
        )

    response = resend.Emails.send(
        {
            "from": cfg.resend_from_email,
            "to": [to_email],
            "subject": subject,
            "html": html,
        }
    )
    # resend SDK may return a dict or object with id
    if isinstance(response, dict):
        return response.get("id")
    return getattr(response, "id", None)
