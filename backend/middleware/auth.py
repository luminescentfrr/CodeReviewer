"""API Key authentication middleware."""
from __future__ import annotations

import os

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

PUBLIC_PATHS = {"/api/health", "/api/docs", "/", "/favicon.ico", "/openapi.json"}
PUBLIC_PREFIXES = ("/api/docs",)

ENFORCE_PATHS: set[str] = set()


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)

        # Localhost requests always pass (desktop app)
        if request.client and request.client.host in ("127.0.0.1", "::1", "localhost"):
            return await call_next(request)

        api_key = os.getenv("APP_API_KEY", "")

        if not api_key:
            if path in ENFORCE_PATHS:
                raise HTTPException(403, "APP_API_KEY not configured on server")
            return await call_next(request)

        request_key = request.headers.get("X-API-Key", "")
        if request_key != api_key:
            raise HTTPException(401, "Invalid or missing API key")

        return await call_next(request)
