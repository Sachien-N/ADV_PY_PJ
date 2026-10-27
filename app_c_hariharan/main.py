"""Application C - Smart Home Electricity & Bill Manager.

FastAPI backend entry point.
Owner: Hariharan S, CSI3007 Advanced Python Programming Project.

Run locally:  uvicorn main:app --reload --port 8003
Docs:         http://localhost:8003/docs
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api import appliances, bills, integration, readings
from config import get_settings
from database import init_db
from services import expense_client

settings = get_settings()
logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("app_c")


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
        "Electricity management API: appliances, meter readings (manual or "
        "clearly-labelled simulated), kWh consumption, configurable tariff "
        "slabs, estimated vs actual bills, payments, six-month deviation "
        "analysis and real REST integration with the Expense Manager (App A). "
        f"Owner: {settings.OWNER}."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(readings.router)
app.include_router(appliances.router)
app.include_router(bills.router)
app.include_router(integration.router)


@app.get("/health")
def health() -> dict:
    """Liveness + peer visibility. Never fails because a peer is down."""
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "owner": settings.OWNER,
        "expense_api_configured": bool(settings.EXPENSE_API_URL),
    }


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "path": request.url.path},
    )
