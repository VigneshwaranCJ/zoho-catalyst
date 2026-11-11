"""Text extraction with Docling, preserving page numbers and structure.

Output is Markdown with explicit page markers, so later phases can cite pages:

    <!-- page: 11 -->

    ## 9. Warranty Policy
    TechNova Electronics provides a 24-month limited warranty ...

How page numbers are kept: Docling records the page of every item
(`item.prov[].page_no`); we export the document one page at a time with the
official `export_to_markdown(page_no=N)` and insert a marker before each page.

Only PDFs have real pages. DOCX/HTML/Markdown are "flowing" formats (the page
layout depends on the screen or printer), so they get no page markers and are
cited by section heading instead.

Docling is heavy (PyTorch models), so:
  * it is imported lazily and only in the worker process (the API never loads it),
  * one converter is built once and reused (loading models takes ~25 s),
  * remote services and third-party plugins stay disabled.
"""

import io
import re
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.ingestion.validation import EXTENSIONS, FileKind

if TYPE_CHECKING:
    from docling.document_converter import DocumentConverter


class ExtractionError(Exception):
    """The document could not be turned into text. Message is user-safe."""


@dataclass(frozen=True, slots=True)
class Heading:
    text: str
    page: int | None


@dataclass
class ExtractionResult:
    markdown: str
    page_count: int | None
    headings: list[Heading]
    table_count: int
    docling_json: dict[str, Any] | None
    stats: dict[str, Any] = field(default_factory=dict)


PAGE_MARKER = "<!-- page: {page} -->"
PAGE_MARKER_RE = re.compile(r"<!-- page: (\d+) -->")
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.MULTILINE)


def clean_html(html: str) -> str:
    """Keep the main content of a web page; drop menus, footers, ads and scripts.

    Note: this also tends to drop hidden text, but that is NOT a security
    control. Prompt-injection scanning (Phase 4) checks the raw page too.
    """
    import trafilatura

    cleaned = trafilatura.extract(
        html,
        output_format="html",
        include_tables=True,
        include_formatting=True,
        include_links=False,
        include_images=False,
        favor_precision=True,
    )
    if not cleaned or not cleaned.strip():
        raise ExtractionError("No readable main content was found on this page.")
    return str(cleaned)


class DoclingExtractor:
    def __init__(self, *, artifacts_path: Path | None, document_timeout: float) -> None:
        self.artifacts_path = artifacts_path
        self.document_timeout = document_timeout
        self._converter: DocumentConverter | None = None
        self._lock = threading.Lock()  # Docling models are not used concurrently

    def _get_converter(self) -> "DocumentConverter":
        if self._converter is None:
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption

            pdf_options = PdfPipelineOptions(
                do_ocr=True,  # only used for image regions / scanned pages
                do_table_structure=True,
                document_timeout=self.document_timeout,
                artifacts_path=self.artifacts_path,
                enable_remote_services=False,
                allow_external_plugins=False,
            )
            self._converter = DocumentConverter(
                allowed_formats=[InputFormat.PDF, InputFormat.DOCX, InputFormat.HTML],
                format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options)},
            )
        return self._converter

    def warm_up(self) -> None:
        """Build the converter (and load PDF models) before the first real job."""
        from docling.datamodel.base_models import InputFormat

        with self._lock:
            self._get_converter().initialize_pipeline(InputFormat.PDF)

    def extract(self, kind: FileKind, data: bytes) -> ExtractionResult:
        started = datetime.now(UTC)
        if kind in (FileKind.MARKDOWN, FileKind.TEXT):
            result = self._extract_plain(kind, data)
        else:
            stats: dict[str, Any] = {}
            if kind == FileKind.HTML:
                raw = data.decode("utf-8", "replace")
                cleaned = clean_html(raw)
                stats["html_raw_chars"] = len(raw)
                stats["html_cleaned_chars"] = len(cleaned)
                data = cleaned.encode("utf-8")
            result = self._extract_with_docling(kind, data)
            result.stats.update(stats)
        if not result.markdown.strip() or len(PAGE_MARKER_RE.sub("", result.markdown).strip()) < 20:
            raise ExtractionError("No text could be extracted from this document.")
        result.stats.update(
            {
                "extractor": f"docling {version('docling')}"
                if kind not in (FileKind.MARKDOWN, FileKind.TEXT)
                else "plain",
                "duration_ms": int((datetime.now(UTC) - started).total_seconds() * 1000),
                "chars": len(result.markdown),
                "headings": len(result.headings),
                "tables": result.table_count,
                "pages": result.page_count,
            }
        )
        return result

    def _extract_plain(self, kind: FileKind, data: bytes) -> ExtractionResult:
        text = data.decode("utf-8-sig").replace("\r\n", "\n")
        headings = (
            [Heading(m.group(2), None) for m in _MD_HEADING_RE.finditer(text)]
            if kind == FileKind.MARKDOWN
            else []
        )
        return ExtractionResult(text, None, headings, 0, None)

    def _extract_with_docling(self, kind: FileKind, data: bytes) -> ExtractionResult:
        from docling.datamodel.base_models import ConversionStatus
        from docling_core.types.doc.items.table.table import TableItem
        from docling_core.types.doc.items.text import SectionHeaderItem, TitleItem
        from docling_core.types.io import DocumentStream

        # The name only tells Docling the format; it never comes from the user.
        stream = DocumentStream(name=f"source.{EXTENSIONS[kind]}", stream=io.BytesIO(data))
        with self._lock:
            result = self._get_converter().convert(stream, raises_on_error=False)
        if result.status != ConversionStatus.SUCCESS:
            if result.status == ConversionStatus.PARTIAL_SUCCESS:
                raise ExtractionError(
                    "Only part of the document could be processed (it may be too long or damaged)."
                )
            raise ExtractionError("The document could not be read. Is it damaged or encrypted?")

        doc = result.document
        page_count = doc.num_pages() if kind == FileKind.PDF else 0  # type: ignore[no-untyped-call]
        if page_count:
            parts = [
                f"{PAGE_MARKER.format(page=p)}\n\n{doc.export_to_markdown(page_no=p).strip()}"
                for p in range(1, page_count + 1)
            ]
            markdown = "\n\n".join(parts) + "\n"
        else:
            markdown = doc.export_to_markdown().strip() + "\n"

        headings: list[Heading] = []
        tables = 0
        for item, _level in doc.iterate_items():
            if isinstance(item, SectionHeaderItem | TitleItem):
                page = item.prov[0].page_no if (page_count and item.prov) else None
                headings.append(Heading(item.text.strip(), page))
            elif isinstance(item, TableItem):
                tables += 1
        return ExtractionResult(
            markdown=markdown,
            page_count=page_count or None,
            headings=headings,
            table_count=tables,
            docling_json=doc.export_to_dict(),
        )


def markdown_header(*, source_name: str, sha256: str, extractor: str) -> str:
    """Provenance comment at the top of every extracted file."""
    safe_name = source_name.replace("-->", "")
    return (
        f"<!-- source: {safe_name} | sha256: {sha256} | extractor: {extractor} | "
        f"extracted_at: {datetime.now(UTC).isoformat(timespec='seconds')} -->\n\n"
    )
