"""Bearer-token authentication dependencies.

- Write endpoints require the app's own API_TOKEN (least privilege: read
  endpoints stay open so teammates' category lookups need no secret).
- If API_TOKEN is not configured, writes are rejected in production-style
  use but allowed in tests via ALLOW_UNAUTHENTICATED_WRITES=1.
"""
from __future__ import annotations

import os

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from config import get_settings

security = HTTPBearer(auto_error=False)


def require_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> None:
    settings = get_settings()
    if not settings.API_TOKEN:
        if os.environ.get("ALLOW_UNAUTHENTICATED_WRITES") == "1":
            return  # local development / automated tests only
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API_TOKEN is not configured; write endpoints are disabled.",
        )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if credentials.credentials != settings.API_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid token"
        )
