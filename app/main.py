"""FastAPI application: submit Markdown file sets, query link-check results."""
from __future__ import annotations

import os

from fastapi import Depends, FastAPI, HTTPException

from .analyzer import analyze, normalize_submitted_path
from .models import CheckRequest, CheckResult, CheckSummary
from .storage import Store

app = FastAPI(
    title="Markdown Link Checker",
    version="1.0.0",
    description=(
        "Checks links across a submitted set of Markdown files: heading anchors, "
        "relative paths and explicit fragments. Reports missing targets, duplicate "
        "anchors, path traversal out of the root and self-references. "
        "No external services; results are stored in SQLite."
    ),
)


def get_store() -> Store:
    """Store factory (DB path configurable via the DB_PATH env var)."""
    return Store(os.environ.get("DB_PATH", "data/checks.db"))


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/checks", status_code=201, response_model=CheckResult)
def create_check(request: CheckRequest, store: Store = Depends(get_store)) -> CheckResult:
    """Submit a set of Markdown files and run the link check."""
    files: dict[str, str] = {}
    errors: list[str] = []
    for f in request.files:
        try:
            norm = normalize_submitted_path(f.path)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if norm in files:
            errors.append(f"duplicate file path after normalization: {norm!r}")
            continue
        files[norm] = f.content
    if errors:
        raise HTTPException(status_code=422, detail=errors)

    diagnostics = analyze(files)
    return store.save(files, diagnostics)


@app.get("/checks", response_model=list[CheckSummary])
def list_checks(store: Store = Depends(get_store)) -> list[CheckSummary]:
    """List recent checks (newest first)."""
    return store.list()


@app.get("/checks/{check_id}", response_model=CheckResult)
def get_check(check_id: str, store: Store = Depends(get_store)) -> CheckResult:
    """Fetch a stored check result by its ID."""
    result = store.get(check_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"check not found: {check_id}")
    return result
