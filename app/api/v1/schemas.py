"""Pydantic response models for API v1."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ExtractJobCreated(BaseModel):
    """Response returned after enqueueing an extraction job."""

    job_id: str
    status: str = "queued"


class JobStatusResponse(BaseModel):
    """Job status payload for polling clients."""

    job_id: str
    status: str
    result: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None
    notification_email: str | None = None


class UsageSummaryResponse(BaseModel):
    """Aggregated usage metrics for the authenticated client (current month)."""

    client_id: str
    period_start: datetime
    period_end: datetime
    job_count: int = 0
    pages_processed: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = Field(
        0, description="Sum of prompt_tokens + completion_tokens"
    )
