"""Pydantic schemas for the Markdown link checker API."""
from __future__ import annotations

from pydantic import BaseModel, Field


class FileInput(BaseModel):
    """A single submitted Markdown file."""

    path: str = Field(..., description="POSIX-style path relative to the submission root, e.g. 'docs/guide.md'")
    content: str = Field(..., description="Raw Markdown content of the file")


class CheckRequest(BaseModel):
    """Submission payload: a set of Markdown files forming one virtual tree."""

    files: list[FileInput] = Field(..., min_length=1)


class Diagnostic(BaseModel):
    """One finding produced by the link analysis."""

    type: str = Field(
        ...,
        description="One of: missing_file, missing_anchor, duplicate_anchor, path_out_of_root, self_reference",
    )
    source_file: str = Field(..., description="Normalized path of the file containing the problem")
    line: int = Field(..., description="1-based line number in the source file")
    link: str = Field(..., description="The link target exactly as written in the source (reproducible)")
    target_file: str | None = Field(None, description="Normalized path the link resolves to, if resolvable")
    message: str = Field(..., description="Human-readable explanation")


class CheckResult(BaseModel):
    check_id: str
    created_at: str
    file_count: int
    diagnostic_count: int
    summary: dict[str, int] = Field(..., description="Diagnostic counts keyed by type")
    diagnostics: list[Diagnostic]


class CheckSummary(BaseModel):
    check_id: str
    created_at: str
    file_count: int
    diagnostic_count: int
