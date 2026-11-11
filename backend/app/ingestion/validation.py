"""Upload validation: decide what a file REALLY is, from its bytes.

Never trust the file extension or the browser's Content-Type: a renamed
`.exe` must not become a "PDF". We check magic bytes and structure ourselves
(no native libmagic dependency, which is painful on Windows).

Accepted kinds: PDF, DOCX, HTML, Markdown, plain text.
"""

import io
import zipfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePath


class FileKind(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    HTML = "html"
    MARKDOWN = "markdown"
    TEXT = "text"


MIME_TYPES = {
    FileKind.PDF: "application/pdf",
    FileKind.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    FileKind.HTML: "text/html",
    FileKind.MARKDOWN: "text/markdown",
    FileKind.TEXT: "text/plain",
}

EXTENSIONS = {
    FileKind.PDF: "pdf",
    FileKind.DOCX: "docx",
    FileKind.HTML: "html",
    FileKind.MARKDOWN: "md",
    FileKind.TEXT: "txt",
}

# DOCX is a ZIP archive: limits against "zip bombs" (tiny file that expands to GBs).
MAX_DOCX_UNCOMPRESSED = 200 * 1024 * 1024
MAX_DOCX_ENTRIES = 5_000
MAX_COMPRESSION_RATIO = 100


class UnsupportedFileError(ValueError):
    """The file is not acceptable. The message is safe to show to the user."""


@dataclass(frozen=True, slots=True)
class DetectedFile:
    kind: FileKind
    mime_type: str
    extension: str


def safe_display_name(filename: str | None) -> str:
    """Keep only the base name, strip control characters, cap the length."""
    name = PurePath((filename or "upload").replace("\\", "/")).name
    name = "".join(ch for ch in name if ch.isprintable()).strip() or "upload"
    return name[:200]


def _check_docx(data: bytes) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise UnsupportedFileError("The Word file is damaged or not a real .docx file.") from exc
    with archive:
        infos = archive.infolist()
        names = {i.filename for i in infos}
        if "[Content_Types].xml" not in names or "word/document.xml" not in names:
            raise UnsupportedFileError("This ZIP file is not a Word (.docx) document.")
        if any(n.lower().endswith("vbaproject.bin") for n in names):
            raise UnsupportedFileError("Word files with macros are not accepted.")
        if len(infos) > MAX_DOCX_ENTRIES:
            raise UnsupportedFileError("The Word file has too many internal parts.")
        total = sum(i.file_size for i in infos)
        if total > MAX_DOCX_UNCOMPRESSED:
            raise UnsupportedFileError("The Word file is too large when unpacked.")
        for info in infos:
            if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
                raise UnsupportedFileError("The Word file looks like a compression bomb.")
        content_types = archive.read("[Content_Types].xml").decode("utf-8", "replace").lower()
        if "macroenabled" in content_types:
            raise UnsupportedFileError("Word files with macros are not accepted.")


def _as_text(data: bytes) -> str | None:
    if b"\x00" in data:  # NUL bytes = binary, never a text document
        return None
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def detect(data: bytes, filename: str | None, *, max_bytes: int) -> DetectedFile:
    if not data:
        raise UnsupportedFileError("The file is empty.")
    if len(data) > max_bytes:
        raise UnsupportedFileError(f"The file is larger than {max_bytes // (1024 * 1024)} MB.")

    if data.startswith(b"%PDF-"):
        kind = FileKind.PDF
    elif data.startswith(b"PK\x03\x04"):
        _check_docx(data)
        kind = FileKind.DOCX
    else:
        text = _as_text(data)
        if text is None:
            raise UnsupportedFileError(
                "Unsupported file type. Upload PDF, Word (.docx), HTML, Markdown or text files."
            )
        head = text[:4096].lstrip().lower()
        suffix = PurePath(safe_display_name(filename)).suffix.lower()
        if head.startswith(("<!doctype html", "<html")) or suffix in {".html", ".htm"}:
            kind = FileKind.HTML
        elif suffix in {".md", ".markdown"}:
            kind = FileKind.MARKDOWN
        else:
            kind = FileKind.TEXT
    return DetectedFile(kind, MIME_TYPES[kind], EXTENSIONS[kind])
