-- Document Extraction API — initial Supabase / PostgreSQL schema
-- Source: project SPEC.md §4
-- Apply via Supabase SQL editor or: psql "$DATABASE_URL" -f scripts/init_db.sql

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ---------------------------------------------------------------------------
-- API Keys & Clients
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS clients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    key_hash TEXT NOT NULL UNIQUE,
    key_prefix TEXT NOT NULL,
    rate_limit_rpm INT NOT NULL DEFAULT 60,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_api_keys_client_id ON api_keys(client_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_key_prefix ON api_keys(key_prefix);
CREATE INDEX IF NOT EXISTS idx_api_keys_active ON api_keys(is_active) WHERE is_active = true;

-- ---------------------------------------------------------------------------
-- Extraction Jobs
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS extraction_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID REFERENCES clients(id),
    status TEXT NOT NULL DEFAULT 'PENDING',
    file_path TEXT,
    target_schema JSONB NOT NULL,
    result JSONB,
    error_message TEXT,
    notification_email TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT extraction_jobs_status_check CHECK (
        status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')
    )
);

CREATE INDEX IF NOT EXISTS idx_extraction_jobs_client_id ON extraction_jobs(client_id);
CREATE INDEX IF NOT EXISTS idx_extraction_jobs_status ON extraction_jobs(status);
CREATE INDEX IF NOT EXISTS idx_extraction_jobs_created_at ON extraction_jobs(created_at DESC);

-- ---------------------------------------------------------------------------
-- Usage Metering
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS usage_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID REFERENCES clients(id),
    job_id UUID REFERENCES extraction_jobs(id),
    pages_processed INT NOT NULL DEFAULT 1,
    prompt_tokens INT NOT NULL DEFAULT 0,
    completion_tokens INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_usage_logs_client_id ON usage_logs(client_id);
CREATE INDEX IF NOT EXISTS idx_usage_logs_job_id ON usage_logs(job_id);
CREATE INDEX IF NOT EXISTS idx_usage_logs_created_at ON usage_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_logs_client_created
    ON usage_logs(client_id, created_at DESC);
