"""Gemini-backed PDF → structured JSON extraction."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import jsonschema
from google import genai
from google.genai import types
from jsonschema import Draft202012Validator

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_EXTRACTION_INSTRUCTION = """You are a document extraction engine.
Read the attached PDF and extract data that conforms EXACTLY to the
provided JSON Schema. Return only a JSON object that validates against
the schema. Do not include markdown fences or commentary.
"""


@dataclass(slots=True, frozen=True)
class ExtractionResult:
    """Structured extraction output plus token usage metrics."""

    data: dict[str, Any]
    prompt_tokens: int
    completion_tokens: int
    model: str


def validate_user_schema(schema: dict[str, Any]) -> None:
    """Raise ``jsonschema.SchemaError`` if ``schema`` is not a valid JSON Schema."""
    Draft202012Validator.check_schema(schema)


def _build_client(settings: Settings) -> genai.Client:
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    return genai.Client(api_key=settings.gemini_api_key)


def _usage_tokens(response: Any) -> tuple[int, int]:
    """Best-effort prompt/completion token extraction from a Gemini response."""
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return 0, 0
    prompt = int(
        getattr(usage, "prompt_token_count", None)
        or getattr(usage, "prompt_tokens", 0)
        or 0
    )
    completion = int(
        getattr(usage, "candidates_token_count", None)
        or getattr(usage, "completion_tokens", None)
        or getattr(usage, "output_token_count", 0)
        or 0
    )
    return prompt, completion


def extract_structured_json(
    pdf_bytes: bytes,
    user_schema: dict[str, Any],
    *,
    settings: Settings | None = None,
) -> ExtractionResult:
    """Extract structured JSON from a PDF using Gemini multimodal + JSON schema.

    Args:
        pdf_bytes: Raw PDF file bytes.
        user_schema: Caller-supplied JSON Schema describing the desired output.
        settings: Optional settings override (defaults to env-backed settings).

    Returns:
        ``ExtractionResult`` with validated data and token counts.

    Raises:
        ValueError: Invalid schema, empty PDF, or output that fails validation.
        RuntimeError: Missing Gemini credentials or empty model response.
    """
    if not pdf_bytes:
        raise ValueError("PDF bytes must not be empty")
    if not isinstance(user_schema, dict) or not user_schema:
        raise ValueError("user_schema must be a non-empty JSON object")

    try:
        validate_user_schema(user_schema)
    except jsonschema.SchemaError as exc:
        raise ValueError(f"Invalid JSON Schema: {exc.message}") from exc

    cfg = settings or get_settings()
    client = _build_client(cfg)

    schema_text = json.dumps(user_schema, ensure_ascii=False)
    prompt = (
        f"{_EXTRACTION_INSTRUCTION}\n\n"
        f"JSON Schema:\n{schema_text}"
    )

    # Prefer native structured outputs via response_json_schema when available;
    # still validate locally so bad model output never reaches callers.
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_json_schema=user_schema,
        temperature=0.0,
    )

    response = client.models.generate_content(
        model=cfg.gemini_model,
        contents=[
            types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
            prompt,
        ],
        config=config,
    )

    raw_text = (getattr(response, "text", None) or "").strip()
    if not raw_text:
        raise RuntimeError("Gemini returned an empty extraction response")

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Gemini returned non-JSON output: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Extracted JSON must be an object at the top level")

    try:
        jsonschema.validate(instance=payload, schema=user_schema)
    except jsonschema.ValidationError as exc:
        raise ValueError(
            f"Extracted JSON failed schema validation: {exc.message}"
        ) from exc

    prompt_tokens, completion_tokens = _usage_tokens(response)
    return ExtractionResult(
        data=payload,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        model=cfg.gemini_model,
    )
