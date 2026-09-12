# Project Specification: Async Document Extraction API

## 1. Overview

A production-grade Python API that accepts PDF documents and a target JSON schema, processes the extraction asynchronously via Google Gemini API (Multimodal / Structured Outputs), tracks usage/rate-limits per API key, and notifies clients via email upon task completion.

## 2. Tech Stack

- **Web Framework:** FastAPI (Async, Python 3.11+)
- **Database & Storage:** Supabase (PostgreSQL for API keys, jobs, & usage logs; Supabase Storage for temporary PDF uploads)
- **Task Queue & Cache:** Redis + Celery for background document processing & rate limiting
- **AI Engine:** Google GenAI SDK (`google-genai` / Gemini 1.5 Flash or 2.0 Flash) with native PDF parsing and Structured Outputs (`response_schema` or dynamic JSON schema validation)
- **Email Service:** Resend API (or SendGrid / aiosmtplib)
- **Containerization:** Docker & Docker Compose

## 3. Core Architecture & Data Flow

1. **Client Request:** `POST /api/v1/extract`
   - Headers: `X-API-Key: <key>`
   - Body: `multipart/form-data` with `file` (PDF), `schema` (JSON schema / prompt definition), and `notification_email` (optional).
2. **Auth & Rate Limiting:**
   - Middleware validates the API key in Redis cache (fallback to Supabase `api_keys` table).
   - Redis sliding window rate-limiter verifies current RPM/TPM limit.
3. **Queue Ingestion:**
   - Upload PDF temporarily to Supabase Storage (or store raw bytes in Redis if < 5MB).
   - Create a record in `extraction_jobs` with status `PENDING`.
   - Dispatch background job to Redis queue and immediately return `job_id` and `status: "queued"`.
4. **Worker Processing (Celery):**
   - Worker picks up job, sets status `PROCESSING`.
   - Sends PDF bytes + user JSON schema to Gemini API with structured JSON output enforcement.
   - Saves extracted JSON output, token count, and page count to `extraction_jobs` and `usage_logs`.
   - Updates status to `COMPLETED` (or `FAILED` with error message).
5. **Notification:**
   - If `notification_email` was provided, send an email with the download link or inline JSON preview.
6. **Polling / Retrieval:** `GET /api/v1/jobs/{job_id}` returns job status and result.

## 4. Database Schema (Supabase PostgreSQL)

-- API Keys & Clients
CREATE TABLE clients (
id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
name TEXT NOT NULL,
email TEXT UNIQUE NOT NULL,
created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE api_keys (
id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
client_id UUID REFERENCES clients(id) ON DELETE CASCADE,
key_hash TEXT NOT NULL UNIQUE,
key_prefix TEXT NOT NULL,
rate_limit_rpm INT DEFAULT 60,
is_active BOOLEAN DEFAULT true,
created_at TIMESTAMPTZ DEFAULT now()
);

-- Extraction Jobs
CREATE TABLE extraction_jobs (
id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
client_id UUID REFERENCES clients(id),
status TEXT NOT NULL DEFAULT 'PENDING',
file_path TEXT,
target_schema JSONB NOT NULL,
result JSONB,
error_message TEXT,
notification_email TEXT,
created_at TIMESTAMPTZ DEFAULT now(),
completed_at TIMESTAMPTZ
);

-- Usage Metering
CREATE TABLE usage_logs (
id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
client_id UUID REFERENCES clients(id),
job_id UUID REFERENCES extraction_jobs(id),
pages_processed INT DEFAULT 1,
prompt_tokens INT DEFAULT 0,
completion_tokens INT DEFAULT 0,
created_at TIMESTAMPTZ DEFAULT now()
);

## 5. API Endpoints

- `POST /api/v1/extract` -> Submit extraction job (multipart)
- `GET /api/v1/jobs/{job_id}` -> Check status & fetch JSON result
- `GET /api/v1/usage` -> Get client usage metrics (current month)
- `POST /api/v1/keys` -> Admin/Self-serve endpoint to generate new API keys
- `GET /health` -> System health check (checks DB & Redis connection)
