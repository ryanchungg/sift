"""FastAPI application entrypoint for the Document Extraction API."""

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.middleware.auth import APIKeyAuthMiddleware


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown resources."""
    yield
    from app.core.database import close_async_supabase_client
    from app.core.redis import close_redis

    await close_async_supabase_client()
    await close_redis()


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )

    # Auth + Redis sliding-window RPM for all /api/v1/* routes.
    application.add_middleware(APIKeyAuthMiddleware)

    application.include_router(api_router, prefix=settings.api_v1_prefix)

    @application.get("/health", tags=["health"])
    async def health() -> dict[str, Any]:
        """Lightweight liveness probe (DB/Redis checks added later)."""
        return {"status": "ok", "service": settings.app_name}

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(_request, exc: Exception) -> JSONResponse:
        """Return structured errors without leaking stack traces."""
        if settings.debug:
            detail = str(exc)
        else:
            detail = "Internal server error"
        return JSONResponse(status_code=500, content={"detail": detail})

    return application


app = create_app()
