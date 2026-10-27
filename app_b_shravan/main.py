"""Application B - Subscription Renewal & Cost Tracker.

FastAPI backend entry point.
Owner: Shravan N A (23MID0445), CSI3007 Advanced Python Programming Project.

Run locally:  uvicorn main:app --reload --port 8002
Docs:         http://localhost:8002/docs
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api import integration, subscriptions
from config import get_settings
from database import init_db

settings = get_settings()
logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("app_b")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # For production PostgreSQL deployments migrations are applied separately
    # (see DEPLOYMENT.md); create_all keeps local SQLite development simple.
    init_db()
    logger.info("%s v%s started.", settings.APP_NAME, settings.APP_VERSION)
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
    description=(
        "Subscription management API: services, billing frequencies, renewal "
        "horizons, monthly-equivalent/annual costs, tags and real REST "
        "integration with the Expense Manager (App A). "
        f"Owner: {settings.OWNER} ({settings.REGISTRATION_NO})."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(subscriptions.router)
app.include_router(integration.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):  # pragma: no cover
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
