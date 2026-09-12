"""API v1 router aggregation."""

from fastapi import APIRouter

from app.api.v1 import extract, jobs, usage

api_router = APIRouter()
api_router.include_router(extract.router)
api_router.include_router(jobs.router)
api_router.include_router(usage.router)
