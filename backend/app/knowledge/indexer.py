"""Split an OKF document into searchable sections.

One section per heading. For each section we record:
  * heading + heading path (["Warranty Policy", "What is covered"])
  * body text WITHOUT footnote markers (cleaner search + display)
  * the source pages cited by the section's footnotes (via sources[].locators),
    which is what Phase 5 needs to answer with "SmartAir X1 Manual, page 11".

Source Document mirrors are split per page instead ("Page 11"), so the agent can
fall back to the original text when no concept covers a question.
"""

import re
from dataclasses import dataclass
from typing import Any

from app.ingestion.extractor import PAGE_MARKER_RE
from app.knowledge.okf import document as okfdoc

_FOOTNOTE_DEF_LINE_RE = re.compile(r"^\[\^[^\]\s]+\]:.*$", re.MULTILINE)


@dataclass
class SectionRow:
    position: int
    anchor: str
    heading: str
    heading_path: list[str]
    body: str
    source_pages: list[int]


def _label_pages(frontmatter: dict[str, Any]) -> dict[str, list[int]]:
    pages: dict[str, list[int]] = {}
    for source in frontmatter.get("sources") or []:
        if not isinstance(source, dict) or "id" not in source:
            continue
        found = [
            int(loc["page"])
            for loc in source.get("locators") or []
            if isinstance(loc, dict) and isinstance(loc.get("page"), int)
        ]
        pages[str(source["id"])] = found
    return pages


def _clean(body: str) -> str:
    body = _FOOTNOTE_DEF_LINE_RE.sub("", body)
    body = okfdoc.FOOTNOTE_REF_RE.sub("", body)
    return re.sub(r"\n{3,}", "\n\n", body).strip()


def _unique_anchor(heading: str, used: set[str]) -> str:
    base = okfdoc.slugify(heading, 100)
    anchor, n = base, 2
    while anchor in used:
        anchor = f"{base}-{n}"
        n += 1
    used.add(anchor)
    return anchor


def split_sections(content: str) -> list[SectionRow]:
    doc = okfdoc.parse(content)
    fm = doc.frontmatter or {}
    title = str(fm.get("title") or "Untitled")
    if fm.get("type") == "Source Document":
        return _split_pages(doc.body, title)

    label_pages = _label_pages(fm)
    used: set[str] = set()
    rows: list[SectionRow] = []
    stack: list[tuple[int, str]] = []
    current_heading = title
    current_lines: list[str] = []

    def flush() -> None:
        raw = "\n".join(current_lines)
        text = _clean(raw)
        if text and current_heading.lower() != "related":
            pages = sorted(
                {
                    p
                    for label in okfdoc.FOOTNOTE_REF_RE.findall(raw)
                    for p in label_pages.get(label, [])
                }
            )
            rows.append(
                SectionRow(
                    position=len(rows),
                    anchor=_unique_anchor(current_heading, used),
                    heading=current_heading,
                    heading_path=[title, *[h for _, h in stack]] if stack else [title],
                    body=text,
                    source_pages=pages,
                )
            )

    for line in _FOOTNOTE_DEF_LINE_RE.sub("", doc.body).splitlines():
        match = okfdoc.HEADING_RE.match(line)
        if match:
            flush()
            level, heading = len(match.group(1)), match.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, heading))
            current_heading, current_lines = heading, []
        else:
            current_lines.append(line)
    flush()
    return rows


def _split_pages(body: str, title: str) -> list[SectionRow]:
    parts = PAGE_MARKER_RE.split(body)
    rows: list[SectionRow] = []
    used: set[str] = set()
    if len(parts) == 1:
        text = body.strip()
        return [SectionRow(0, "full-text", title, [title], text, [])] if text else []
    for i in range(1, len(parts) - 1, 2):
        page, text = int(parts[i]), parts[i + 1].strip()
        if text:
            heading = f"Page {page}"
            rows.append(
                SectionRow(
                    len(rows),
                    _unique_anchor(heading, used),
                    heading,
                    [title, heading],
                    text,
                    [page],
                )
            )
    return rows
