"""Markdown link analysis.

Parses a virtual tree of Markdown files (path -> content) and checks:
  - heading anchors (GitHub-style slugs), including duplicates
  - relative links and explicit fragments (#anchor), resolved against
    normalized POSIX paths
  - links escaping the submission root (path traversal)
  - files linking to themselves via an explicit path (self-loops)

External URLs (http:, https:, mailto:, ...) are ignored: no network access.
"""
from __future__ import annotations

import posixpath
import re
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import unquote

from .models import Diagnostic

# A heading: up to 3 leading spaces, 1-6 '#', at least one space, then text.
# An optional closing sequence of '#' must be preceded by whitespace.
HEADING_RE = re.compile(r"^[ ]{0,3}#{1,6}[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")

# Fenced code block delimiter (``` or ~~~).
FENCE_RE = re.compile(r"^[ ]{0,3}(```+|~~~+)")

# Inline code span (single backticks; good enough for link/heading cleanup).
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")

# Inline link: [text](dest) or [text](<dest>) with optional "title".
# Images ![alt](src) are excluded via the negative lookbehind.
LINK_RE = re.compile(
    r"(?<!!)"                       # not an image
    r"\[[^\]\n]*\]"                 # link text
    r"\([ \t]*"
    r"(?:<([^>\n]+)>|([^\s)]+))"    # destination: <...> or bare
    r"(?:[ \t]+[\"'][^\"']*[\"'])?" # optional title
    r"[ \t]*\)"
)

# URI scheme, e.g. https:, mailto:, tel:
SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")

# Characters kept in GitHub-style slugs: word chars (incl. unicode letters,
# digits, underscore), hyphens and spaces. Everything else is dropped.
_SLUG_DROP_RE = re.compile(r"[^\w\- ]", re.UNICODE)

# Link/image markup inside heading text: replaced by its visible text.
_HEADING_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")


def slugify(heading_text: str) -> str:
    """GitHub-style anchor slug for a heading's visible text."""
    text = heading_text.strip().lower()
    text = _SLUG_DROP_RE.sub("", text)
    return text.replace(" ", "-")


def _heading_visible_text(raw: str) -> str:
    """Strip inline markdown formatting from heading text."""
    text = INLINE_CODE_RE.sub(lambda m: m.group(0)[1:-1], raw)
    text = _HEADING_LINK_RE.sub(r"\1", text)
    text = text.replace("**", "").replace("__", "").replace("*", "").replace("~~", "")
    return text.strip()


def normalize_submitted_path(path: str) -> str:
    """Normalize a submitted file path; reject absolute or escaping paths."""
    p = posixpath.normpath(path.replace("\\", "/"))
    if p.startswith("/") or p == ".." or p.startswith("../") or p == ".":
        raise ValueError(f"invalid file path (must be relative, inside the root): {path!r}")
    return p


@dataclass
class _Link:
    line: int
    raw: str  # destination exactly as written


@dataclass
class _Doc:
    path: str
    anchors: dict[str, int] = field(default_factory=dict)  # slug -> first defining line
    links: list[_Link] = field(default_factory=list)


def _parse_file(path: str, content: str) -> tuple[_Doc, list[Diagnostic]]:
    """Extract anchors and links from one Markdown file."""
    doc = _Doc(path=path)
    duplicates: list[Diagnostic] = []
    in_fence = False
    fence_marker = ""

    for lineno, line in enumerate(content.splitlines(), start=1):
        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            if not in_fence:
                in_fence, fence_marker = True, marker[0] * 3
            elif marker.startswith(fence_marker[0]):
                in_fence = False
            continue
        if in_fence:
            continue

        heading = HEADING_RE.match(line)
        if heading:
            slug = slugify(_heading_visible_text(heading.group(1)))
            if slug:
                if slug in doc.anchors:
                    duplicates.append(
                        Diagnostic(
                            type="duplicate_anchor",
                            source_file=path,
                            line=lineno,
                            link=f"#{slug}",
                            target_file=path,
                            message=(
                                f"Anchor '#{slug}' duplicates the heading "
                                f"first defined at line {doc.anchors[slug]}"
                            ),
                        )
                    )
                else:
                    doc.anchors[slug] = lineno

        # Links (also inside heading lines); inline code spans are blanked first.
        for m in LINK_RE.finditer(INLINE_CODE_RE.sub("", line)):
            doc.links.append(_Link(line=lineno, raw=m.group(1) or m.group(2)))

    return doc, duplicates


def analyze(files: dict[str, str]) -> list[Diagnostic]:
    """Analyze a set of Markdown files (normalized path -> content)."""
    docs: dict[str, _Doc] = {}
    diagnostics: list[Diagnostic] = []

    for path, content in files.items():
        doc, dups = _parse_file(path, content)
        docs[path] = doc
        diagnostics.extend(dups)

    for src_path, doc in docs.items():
        src_dir = posixpath.dirname(src_path)
        for link in doc.links:
            raw = link.raw.strip()
            if not raw or raw == "#" or SCHEME_RE.match(raw):
                continue  # empty target or external URL

            path_part, _, frag = raw.partition("#")
            path_part = unquote(path_part).strip()
            frag = unquote(frag)

            if not path_part:
                # Fragment-only link: anchor within the same file.
                if frag and frag not in doc.anchors:
                    diagnostics.append(
                        Diagnostic(
                            type="missing_anchor",
                            source_file=src_path,
                            line=link.line,
                            link=link.raw,
                            target_file=src_path,
                            message=f"Anchor '#{frag}' not found in '{src_path}'",
                        )
                    )
                continue

            if path_part.startswith("/"):
                resolved = posixpath.normpath(path_part.lstrip("/"))
            else:
                resolved = posixpath.normpath(posixpath.join(src_dir, path_part))

            if resolved == ".." or resolved.startswith("../"):
                diagnostics.append(
                    Diagnostic(
                        type="path_out_of_root",
                        source_file=src_path,
                        line=link.line,
                        link=link.raw,
                        target_file=None,
                        message=f"Link escapes the submission root: '{path_part}'",
                    )
                )
                continue

            if resolved == src_path:
                diagnostics.append(
                    Diagnostic(
                        type="self_reference",
                        source_file=src_path,
                        line=link.line,
                        link=link.raw,
                        target_file=resolved,
                        message=f"File links to itself via explicit path: '{path_part}'",
                    )
                )
                continue

            target = docs.get(resolved)
            if target is None:
                diagnostics.append(
                    Diagnostic(
                        type="missing_file",
                        source_file=src_path,
                        line=link.line,
                        link=link.raw,
                        target_file=resolved,
                        message=f"Target file '{resolved}' not found in submitted files",
                    )
                )
                continue

            if frag and frag not in target.anchors:
                diagnostics.append(
                    Diagnostic(
                        type="missing_anchor",
                        source_file=src_path,
                        line=link.line,
                        link=link.raw,
                        target_file=resolved,
                        message=f"Anchor '#{frag}' not found in '{resolved}'",
                    )
                )

    diagnostics.sort(key=lambda d: (d.source_file, d.line, d.type, d.link))
    return diagnostics


def summarize(diagnostics: list[Diagnostic]) -> dict[str, int]:
    """Diagnostic counts keyed by type."""
    return dict(Counter(d.type for d in diagnostics))
