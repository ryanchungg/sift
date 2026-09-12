# Sift: Document Extraction API

Async document extraction API that parses PDFs into user-defined JSON schemas using Google Gemini, Redis-backed task queues, and Supabase.

## How to run

1. Make `.env` file from `.env.example`
2. Replace `.env` variables with actual keys (`GEMINI_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`, `RESEND_API_KEY`)
3. Run `scripts/init_db.sql` in your Supabase SQL editor to create tables
4. Run `docker-compose up --build`
5. Test endpoints at `http://localhost:8000/docs`

---

### Principles

1. **Try to make everything as cheap / free as possible**
   - Use Gemini Flash on the free tier (native PDF parsing so we avoid paying for heavy OCR tools like AWS Textract).
   - Use Gemini's structured outputs (`response_schema`) so we don't waste tokens on conversational fluff or formatting retries.
   - Cache API key lookups in Redis so we don't spam Supabase database queries on every single incoming HTTP request.
   - Per-key sliding window rate limiting in Redis to protect our free-tier Gemini API quota from getting drained.

2. **Learn software engineering**
   - **Async Backend:** FastAPI for non-blocking I/O and automatic Swagger UI docs.
   - **Distributed Task Queues:** Celery + Redis so long PDF extractions run in the background without freezing API requests or causing HTTP timeouts.
   - **Databases & Storage:** Supabase (PostgreSQL) for jobs, usage logs, and API keys; Supabase Storage for temporary PDF uploads.
   - **Docker:** Docker Compose to run Redis, the FastAPI web service, and the Celery worker all together with one command.

3. **Solve technical challenges**
   - **Non-blocking API Design:** Return `status: "queued"` and a `job_id` immediately (<100ms) instead of making users wait 20s for Gemini to finish.
   - **Dynamic JSON Validation:** Let users submit arbitrary JSON schemas and validate Gemini's output before marking the job as complete.
   - **Usage Metering:** Track prompt tokens, completion tokens, and page counts per API key in PostgreSQL so usage can be monitored.

4. **Security**
   - Never store raw API keys in the database: hash them with `SHA-256` and verify against key prefixes.
   - Never commit `.env` or API credentials to GitHub.
   - Return structured error responses without leaking internal stack traces.
   - TODO: Configure Supabase Row Level Security (RLS) policies.

---

### To-Dos

#### Must-have

1. Strict validation on user-provided JSON schemas using `jsonschema` before dispatching jobs.
2. Auto-delete temporary PDFs from Supabase Storage once the extraction job is marked `COMPLETED` or `FAILED`.
3. Handle edge cases for scanned/corrupted PDFs or empty files.
4. Add basic unit tests with `pytest` (mocking Gemini API calls).
5. Supabase Row Level Security (RLS) setup.

#### Nice to have

1. Webhook callbacks (`webhook_url`) as an alternative to email notifications.
2. Simple frontend dashboard to upload PDFs and inspect extracted JSON side-by-side.
3. Batch upload endpoint (`POST /api/v1/extract/batch`) for multiple files.
4. Support image formats (`.png`, `.jpg`) in addition to PDFs.
