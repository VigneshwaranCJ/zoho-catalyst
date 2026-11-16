"""Turn one extracted source into OKF concept documents (drafts for human review).

    extracted text ──► 1. PLAN (Claude)    which concepts, paths, types, pages
                   ──► 2. DRAFT (Claude)   statements + exact quotes + pages, per concept
                   ──► 3. VERIFY (code)    quotes exist on the page, numbers match,
                                           no injection text; failures -> 1 repair try
                   ──► 4. RENDER (code)    OKF Markdown + YAML frontmatter, footnotes
                   ──► 5. VALIDATE (code)  OKF v0.2 conformance + csp-okf-profile/1

The AI never writes YAML or Markdown syntax directly: it returns structured
JSON (validated against Pydantic schemas) and our code renders the files.
"""

import asyncio
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from app.knowledge import prompts
from app.knowledge.injection import Finding, scan_html, scan_text
from app.knowledge.okf import document as okfdoc
from app.knowledge.okf import validate as okfvalidate
from app.knowledge.okf.profile import TYPE_FOLDERS, ConceptType
from app.knowledge.quotes import SourcePages, check_statement
from app.llm.client import StructuredLLM, Usage

MAX_SOURCE_CHARS = 400_000  # ~100k tokens; larger documents must be split first
CONCURRENT_DRAFTS = 3

ConceptTypeName = Literal[
    "Company Profile", "Product", "Specification", "Procedure", "Troubleshooting Guide",
    "Policy", "FAQ", "Contact Info",
]  # fmt: skip


# ------------------------------------------------------------------ structured output schemas
class PlannedConcept(BaseModel):
    slug: str
    type: ConceptTypeName
    title: str
    description: str
    tags: list[str]
    audience: Literal["customer", "internal"]
    pages: list[int]


class GenerationPlan(BaseModel):
    products: list[str]
    concepts: list[PlannedConcept]


class Statement(BaseModel):
    text: str
    style: Literal["paragraph", "bullet", "step"]
    quote: str
    page: int | None


class DraftSection(BaseModel):
    heading: str
    statements: list[Statement]


class ConceptDraft(BaseModel):
    sections: list[DraftSection]
    related: list[str]


class RepairedStatement(Statement):
    index: int


class RepairResult(BaseModel):
    statements: list[RepairedStatement]


# ------------------------------------------------------------------ pipeline data
class GenerationError(Exception):
    """User-safe reason the generation step failed."""


@dataclass(frozen=True)
class SourceInfo:
    id: str
    name: str
    slug: str
    uri: str | None
    sha256: str
    created_at: datetime


@dataclass
class GeneratedFile:
    path: str
    content: str
    title: str
    doc_type: str
    audience: str
    validation: dict[str, Any]
    stats: dict[str, Any]


@dataclass
class GenerationResult:
    files: list[GeneratedFile]
    usage: Usage
    findings: list[Finding]
    stats: dict[str, Any] = field(default_factory=dict)


@dataclass
class _VerifiedStatement:
    heading: str
    text: str
    style: str
    page: int | None


# ------------------------------------------------------------------ helpers
def _outline(pages: SourcePages) -> str:
    lines = []
    for page, text in pages.pages.items():
        for level, heading in okfdoc.headings(text):
            prefix = f"p.{page} " if page is not None else ""
            lines.append(f"{prefix}{'  ' * (level - 1)}{heading}")
    return "\n".join(lines[:300]) or "(no headings)"


def _unique_path(folder: str, slug: str, taken: set[str]) -> str:
    path = f"{folder}/{slug}.md"
    n = 2
    while path in taken:
        path = f"{folder}/{slug}-{n}.md"
        n += 1
    taken.add(path)
    return path


def footnote_id(source_slug: str, page: int | None) -> str:
    return f"{source_slug}-p{page}" if page is not None else source_slug


def _with_footnote(text: str, label: str) -> str:
    text = text.strip()
    return f"{text}[^{label}]"


def render_concept(
    *,
    planned: PlannedConcept,
    statements: list[_VerifiedStatement],
    related: list[tuple[str, str]],
    products: list[str],
    source: SourceInfo,
    model: str,
    now: datetime,
) -> str:
    """Our code (not the AI) writes the OKF file: frontmatter + body + footnotes."""
    by_heading: dict[str, list[_VerifiedStatement]] = defaultdict(list)
    for s in statements:
        by_heading[s.heading].append(s)

    body: list[str] = []
    first_section_for: dict[str, str] = {}
    page_of: dict[str, int | None] = {}
    for heading, items in by_heading.items():
        body.append(f"# {heading.strip()}\n")
        previous_style = None
        for s in items:
            label = footnote_id(source.slug, s.page)
            first_section_for.setdefault(label, heading)
            page_of[label] = s.page
            line = _with_footnote(s.text, label)
            if s.style == "step":
                body.append(f"1. {line}")
            elif s.style == "bullet":
                body.append(f"- {line}")
            else:
                if previous_style in ("step", "bullet"):
                    body.append("")
                body.append(f"{line}\n")
            previous_style = s.style
        body.append("")
    if related:
        body.append("# Related\n")
        body.extend(f"* [{title}](/{path})" for path, title in related)
        body.append("")

    labels = sorted(first_section_for, key=lambda lbl: (len(lbl), lbl))
    body.extend(
        f"[^{label}]: {source.name}"
        + (f", page {page_of[label]}" if page_of[label] is not None else "")
        for label in labels
    )

    stamp = now.isoformat(timespec="seconds")
    frontmatter = {
        "type": planned.type,
        "title": planned.title.strip(),
        "description": planned.description.strip(),
        "tags": sorted({okfdoc.slugify(t, 40) for t in planned.tags if t.strip()}),
        "products": products,
        "audience": planned.audience,
        "status": "draft",
        "sources": [
            {
                "id": label,
                "resource": f"/sources/{source.slug}.md"
                + (f"#page-{page_of[label]}" if page_of[label] is not None else ""),
                "title": source.name,
                "sha256": source.sha256,
                "locators": [
                    {"page": page_of[label], "section": first_section_for[label]}
                    if page_of[label] is not None
                    else {"section": first_section_for[label]}
                ],
            }
            for label in labels
        ],
        "generated": {"by": f"csp-ingestor/{model}", "at": stamp},
        "verified": [{"by": "process:csp-quote-check", "at": stamp}],
    }
    return okfdoc.render(frontmatter, re.sub(r"\n{3,}", "\n\n", "\n".join(body)))


def render_source_mirror(
    source: SourceInfo, markdown: str, pages: SourcePages, now: datetime
) -> str:
    """sources/<slug>.md: the extracted text, so every citation is verifiable in the bundle."""
    page_info = f"{len(pages.pages)} pages" if pages.paged else "no fixed pages"
    stamp = now.isoformat(timespec="seconds")
    frontmatter = {
        "type": ConceptType.SOURCE_DOCUMENT.value,
        "title": source.name,
        "description": f"Text extracted from {source.name} ({page_info}), kept for citations.",
        "tags": ["source"],
        "audience": "internal",
        "status": "draft",
        "sources": [
            {
                "id": source.slug,
                "resource": source.uri or f"urn:sha256:{source.sha256}",
                "title": source.name,
                "sha256": source.sha256,
                "last_modified": source.created_at.isoformat(timespec="seconds"),
            }
        ],
        "generated": {"by": "process:csp-extractor", "at": stamp},
    }
    return okfdoc.render(frontmatter, f"# {source.name}\n\n{markdown.strip()}")


# ------------------------------------------------------------------ the pipeline
class KnowledgeGenerator:
    def __init__(self, llm: StructuredLLM, *, model: str, max_concepts: int) -> None:
        self.llm = llm
        self.model = model
        self.max_concepts = max_concepts

    async def generate(
        self,
        *,
        source: SourceInfo,
        markdown: str,
        raw_html: str | None,
        existing: dict[str, str | None],  # live path -> source_id that produced it
        now: datetime,
    ) -> GenerationResult:
        body = re.sub(r"^<!-- source:[^\n]*-->\n*", "", markdown)
        if len(body) > MAX_SOURCE_CHARS:
            raise GenerationError(
                "This document is too large for automatic knowledge generation. "
                "Split it into smaller files (e.g. one per chapter) and upload them again."
            )
        pages = SourcePages.from_markdown(body)
        normalized = pages.normalized()
        findings = scan_html(raw_html) if raw_html else scan_text(body)
        usage = Usage()

        plan = await self.llm.structured(
            model=self.model,
            system=prompts.PLAN_SYSTEM,
            user=prompts.plan_user(
                source_name=source.name,
                outline=_outline(pages),
                document=body,
                max_concepts=self.max_concepts,
                existing="\n".join(f"- {p}" for p in sorted(existing)) or "",
            ),
            output_model=GenerationPlan,
            usage=usage,
            max_tokens=8000,
        )
        concepts = plan.concepts[: self.max_concepts]
        if not concepts:
            raise GenerationError("The AI found no support topics in this document.")
        products = sorted({okfdoc.slugify(p, 40) for p in plan.products if p.strip()})

        # Paths: new topics get new paths; a path already owned by ANOTHER source is
        # never overwritten (a numeric suffix is added instead).
        taken = {p for p, owner in existing.items() if owner != source.id}
        paths: dict[str, str] = {}
        for c in concepts:
            folder = TYPE_FOLDERS[ConceptType(c.type)]
            paths[c.slug] = _unique_path(folder, okfdoc.slugify(c.slug), taken)

        semaphore = asyncio.Semaphore(CONCURRENT_DRAFTS)

        async def one(c: PlannedConcept) -> GeneratedFile | None:
            async with semaphore:
                return await self._draft_concept(
                    c, concepts, paths, products, source, pages, normalized, usage, now
                )

        drafted = await asyncio.gather(*(one(c) for c in concepts))
        files = [f for f in drafted if f is not None]
        if not files:
            raise GenerationError("No knowledge could be generated with verifiable citations.")

        files.append(
            GeneratedFile(
                path=f"sources/{source.slug}.md",
                content=render_source_mirror(source, body, pages, now),
                title=source.name,
                doc_type=ConceptType.SOURCE_DOCUMENT.value,
                audience="internal",
                validation={},
                stats={},
            )
        )
        known = set(existing) | {f.path for f in files}
        for f in files:
            report = okfvalidate.Report()
            okfvalidate.check_conformance(f.path, f.content, report)
            okfvalidate.check_profile(f.path, f.content, report, known_paths=known)
            for finding in findings:  # source-level injection findings: reviewer must see them
                report.warning(
                    f.path,
                    f"Possible prompt injection in the SOURCE ({finding.kind}): {finding.excerpt}",
                )
            for dropped in f.stats.get("dropped", []):
                report.warning(f.path, f"Dropped unverifiable statement: {dropped}")
            f.validation = report.as_dict()

        return GenerationResult(
            files=files,
            usage=usage,
            findings=findings,
            stats={
                "planned": len(concepts),
                "generated": len(files) - 1,
                "statements": sum(f.stats.get("statements", 0) for f in files),
                "dropped_statements": sum(len(f.stats.get("dropped", [])) for f in files),
                "repaired_statements": sum(f.stats.get("repaired", 0) for f in files),
                "injection_findings": [x.as_dict() for x in findings],
            },
        )

    async def _draft_concept(
        self,
        c: PlannedConcept,
        concepts: list[PlannedConcept],
        paths: dict[str, str],
        products: list[str],
        source: SourceInfo,
        pages: SourcePages,
        normalized: dict[int | None, str],
        usage: Usage,
        now: datetime,
    ) -> GeneratedFile | None:
        excerpt = pages.text_for(c.pages)
        others = "\n".join(f"- {o.slug}: {o.title}" for o in concepts if o.slug != c.slug)
        draft = await self.llm.structured(
            model=self.model,
            system=prompts.DRAFT_SYSTEM,
            user=prompts.draft_user(
                source_name=source.name, title=c.title, type_=c.type,
                description=c.description, others=others, excerpt=excerpt,
            ),
            output_model=ConceptDraft,
            usage=usage,
        )  # fmt: skip

        flat = [(sec.heading, st) for sec in draft.sections for st in sec.statements]
        verified: dict[int, _VerifiedStatement] = {}
        failures: dict[int, str] = {}
        for i, (heading, st) in enumerate(flat):
            reason = self._verify(st, normalized, verified, i, heading)
            if reason:
                failures[i] = reason

        repaired = 0
        if failures:
            listing = "\n".join(
                f"{i}. [{failures[i]}] statement: {flat[i][1].text!r} | quote: {flat[i][1].quote!r}"
                for i in failures
            )
            fixed = await self.llm.structured(
                model=self.model,
                system=prompts.REPAIR_SYSTEM,
                user=prompts.repair_user(failures=listing, excerpt=excerpt),
                output_model=RepairResult,
                usage=usage,
                max_tokens=8000,
            )
            for st in fixed.statements:
                if st.index in failures:
                    heading = flat[st.index][0]
                    if not self._verify(st, normalized, verified, st.index, heading):
                        failures.pop(st.index)
                        repaired += 1

        ordered = [verified[i] for i in sorted(verified)]
        dropped = [f"{flat[i][1].text[:120]} ({reason})" for i, reason in sorted(failures.items())]
        if not ordered:
            return None
        related = [
            (paths[slug], next(o.title for o in concepts if o.slug == slug))
            for slug in dict.fromkeys(draft.related)
            if slug in paths and slug != c.slug
        ]
        content = render_concept(
            planned=c, statements=ordered, related=related, products=products,
            source=source, model=self.model, now=now,
        )  # fmt: skip
        return GeneratedFile(
            path=paths[c.slug],
            content=content,
            title=c.title.strip(),
            doc_type=c.type,
            audience=c.audience,
            validation={},
            stats={"statements": len(ordered), "dropped": dropped, "repaired": repaired},
        )

    @staticmethod
    def _verify(
        st: Statement,
        normalized: dict[int | None, str],
        verified: dict[int, _VerifiedStatement],
        index: int,
        heading: str,
    ) -> str:
        """Returns '' if the statement is verified (and stores it), else the reason."""
        if not st.text.strip():
            return "empty statement"
        if scan_text(f"{st.text}\n{st.quote}"):
            return "looks like a prompt-injection attempt"
        check = check_statement(st.text, st.quote, st.page, normalized)
        if not check.ok:
            return check.reason
        verified[index] = _VerifiedStatement(heading.strip(), st.text, st.style, check.page)
        return ""
