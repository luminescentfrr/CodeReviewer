"""Report listing and retrieval endpoints."""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse

from ..config import REPORTS_DIR
from ..output.report import list_reports as _list_reports


def register(app):
    @app.get("/api/reports")
    async def list_reports():
        return _list_reports()

    @app.get("/api/reports/{filename}")
    async def get_report(filename: str):
        path = (REPORTS_DIR / filename).resolve()
        if not str(path).startswith(str(REPORTS_DIR.resolve())):
            raise HTTPException(404, "report not found")
        if not path.exists() or not path.suffix == ".md":
            raise HTTPException(404, "report not found")
        return FileResponse(path, media_type="text/markdown; charset=utf-8")
