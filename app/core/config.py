"""Application settings loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the Document Extraction API."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "Document Extraction API"
    app_env: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    # Supabase (PostgreSQL + Storage)
    supabase_url: str = ""
    supabase_key: str = ""
    supabase_service_role_key: str = ""
    supabase_storage_bucket: str = "extractions"

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None

    # Google Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    # Resend email
    resend_api_key: str = ""
    resend_from_email: str = "noreply@example.com"

    @property
    def broker_url(self) -> str:
        """Celery broker URL, defaulting to Redis."""
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend(self) -> str:
        """Celery result backend URL, defaulting to Redis."""
        return self.celery_result_backend or self.redis_url

    @property
    def effective_supabase_key(self) -> str:
        """Prefer the service-role key when present; otherwise the anon key."""
        return self.supabase_service_role_key or self.supabase_key


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
