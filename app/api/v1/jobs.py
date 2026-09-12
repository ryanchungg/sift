"""GET /jobs/{job_id} — poll extraction job status and result."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status

from app.api.v1.schemas import JobStatusResponse
from app.core.database import get_async_supabase_client
from app.middleware.auth import get_current_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["jobs"])


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str, request: Request) -> JobStatusResponse:
    """Return status/result for a job owned by the authenticated client."""
    client = get_current_client(request)
    supabase = await get_async_supabase_client()

    try:
        result = await (
            supabase.table("extraction_jobs")
            .select(
                "id, status, result, error_message, created_at, completed_at, "
                "notification_email, client_id"
            )
            .eq("id", job_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.exception("Failed to fetch job %s", job_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to load job",
        ) from exc

    rows = result.data or []
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    job = rows[0]
    if str(job.get("client_id")) != str(client.client_id):
        # Do not leak existence of other clients' jobs.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    return JobStatusResponse(
        job_id=str(job["id"]),
        status=str(job["status"]),
        result=job.get("result"),
        error_message=job.get("error_message"),
        created_at=job.get("created_at"),
        completed_at=job.get("completed_at"),
        notification_email=job.get("notification_email"),
    )
