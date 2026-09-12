# Document Extraction API

Async FastAPI service that accepts PDFs and a target JSON schema, extracts structured data with Google Gemini, and notifies clients when jobs finish. This repo ships scaffold, auth/rate-limits, the Gemini/Celery extraction worker, and HTTP routes for extract/jobs/usage.

## Stack

- FastAPI (Python 3.12)
- Supabase (PostgreSQL + Storage)
- Redis + Celery
- Google GenAI (`google-genai`)
- Resend (email)

## Project layout

```text
app/
  main.py                 # FastAPI entrypoint + /health
  core/
    config.py             # pydantic-settings (env vars)
    database.py           # Supabase sync/async clients
    redis.py              # async Redis client
  middleware/
    auth.py               # X-API-Key auth + RPM rate limit
  services/
    extractor.py          # Gemini PDF → validated JSON
    email.py              # Resend completion emails
    storage.py            # Supabase Storage PDF download
  api/v1/
    extract.py            # POST /extract
    jobs.py               # GET /jobs/{job_id}
    usage.py              # GET /usage
    schemas.py            # response models
    router.py             # aggregates v1 routes
  workers/
    celery_app.py         # Celery app
    tasks.py              # process_extraction worker
scripts/init_db.sql       # Supabase schema migration
docker-compose.yml        # redis + api + worker
Dockerfile
requirements.txt
```

## Local setup

1. Copy environment defaults:

   ```bash
   cp .env.example .env
   ```

   Fill in `SUPABASE_URL`, `SUPABASE_KEY` (or `SUPABASE_SERVICE_ROLE_KEY`), `GEMINI_API_KEY`, and `RESEND_API_KEY` when you wire real services.

2. Install dependencies (optional for non-Docker runs):

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. Boot Redis, the API, and the Celery worker:

   ```bash
   docker compose up --build
   ```

4. Apply the database schema in the Supabase SQL editor (or `psql`):

   ```bash
   # scripts/init_db.sql — clients, api_keys, extraction_jobs, usage_logs
   ```

5. Open [http://localhost:8000/health](http://localhost:8000/health) — you should see `{"status":"ok",...}`.
   Interactive docs: [http://localhost:8000/docs](http://localhost:8000/docs).

Protected `/api/v1/*` routes require an `X-API-Key` header. Keys are looked up in Redis (SHA-256 hash cache) with a Supabase `api_keys` fallback, then checked against a per-key Redis sliding-window RPM limit.

### Run without Docker (API only)

```bash
# Redis must already be reachable at REDIS_URL
uvicorn app.main:app --reload --port 8000
celery -A app.workers.celery_app.celery_app worker --loglevel=info
```

## Environment variables

| Variable | Purpose |
| --- | --- |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Anon or primary API key |
| `SUPABASE_SERVICE_ROLE_KEY` | Preferred server-side key when set |
| `REDIS_URL` | Redis connection string |
| `CELERY_BROKER_URL` | Celery broker (defaults to `REDIS_URL`) |
| `CELERY_RESULT_BACKEND` | Celery backend (defaults to `REDIS_URL`) |
| `GEMINI_API_KEY` | Google Gemini API key |
| `RESEND_API_KEY` | Resend email API key |

## Planned API surface

- `POST /api/v1/extract` — enqueue extraction job
- `GET /api/v1/jobs/{job_id}` — job status / result
- `GET /api/v1/usage` — usage metrics
- `POST /api/v1/keys` — API key provisioning
- `GET /health` — health check (implemented)
