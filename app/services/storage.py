"""Helpers for loading job PDF bytes from Supabase Storage (or inline refs)."""

from __future__ import annotations

import logging
from typing import Any

from supabase import Client

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def upload_job_pdf(
    supabase: Client,
    object_path: str,
    pdf_bytes: bytes,
    *,
    bucket: str | None = None,
    content_type: str = "application/pdf",
) -> str:
    """Upload PDF bytes to Supabase Storage and return the object path."""
    if not object_path:
        raise ValueError("object_path must not be empty")
    if not pdf_bytes:
        raise ValueError("pdf_bytes must not be empty")

    resolved_bucket = bucket or get_settings().supabase_storage_bucket
    # Upsert so retries of the same job_id do not fail on conflicts.
    supabase.storage.from_(resolved_bucket).upload(
        object_path,
        pdf_bytes,
        file_options={
            "content-type": content_type,
            "upsert": "true",
        },
    )
    return object_path


def download_job_pdf(
    supabase: Client,
    file_path: str | None,
    *,
    bucket: str | None = None,
) -> bytes:
    """Download PDF bytes for a job.

    ``file_path`` is treated as a Supabase Storage object path within ``bucket``.
    Paths may optionally be prefixed with ``{bucket}/``.
    """
    if not file_path:
        raise ValueError("Job has no file_path; cannot load PDF")

    resolved_bucket = bucket or get_settings().supabase_storage_bucket
    object_path = file_path
    prefix = f"{resolved_bucket}/"
    if object_path.startswith(prefix):
        object_path = object_path[len(prefix) :]

    response: Any = supabase.storage.from_(resolved_bucket).download(object_path)
    if response is None:
        raise RuntimeError(f"Empty download for storage object '{object_path}'")
    if isinstance(response, bytes):
        return response
    # Some client versions return memoryview / bytearray
    return bytes(response)


def estimate_pdf_page_count(pdf_bytes: bytes) -> int:
    """Estimate page count without hard-depending on a PDF library.

    Counts ``/Type /Page`` markers as a rough lower bound; always returns >= 1.
    """
    if not pdf_bytes:
        return 1
    # Avoid counting /Pages dictionaries; look for leaf page objects.
    marker = b"/Type /Page"
    count = 0
    start = 0
    while True:
        idx = pdf_bytes.find(marker, start)
        if idx < 0:
            break
        # Skip /Type /Pages
        after = pdf_bytes[idx : idx + len(marker) + 1]
        if after.endswith(b"s"):
            start = idx + len(marker)
            continue
        count += 1
        start = idx + len(marker)
    return max(count, 1)
