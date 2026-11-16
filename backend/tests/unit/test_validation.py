import io
import zipfile
from pathlib import Path

import pytest

from app.ingestion.validation import FileKind, UnsupportedFileError, detect, safe_display_name

SAMPLES = Path(__file__).resolve().parents[3] / "sample-data" / "technova"
MB = 1024 * 1024


def _zip(entries: dict[str, bytes], compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buffer.getvalue()


def test_real_sample_files_are_recognised() -> None:
    pdf = (SAMPLES / "SmartAir_X1_User_Manual.pdf").read_bytes()
    docx = (SAMPLES / "TechNova_Customer_Service_Policies.docx").read_bytes()
    html = (SAMPLES / "smartair-x1-faq.html").read_bytes()
    assert detect(pdf, "manual.pdf", max_bytes=50 * MB).kind == FileKind.PDF
    assert detect(docx, "policies.docx", max_bytes=50 * MB).kind == FileKind.DOCX
    assert detect(html, "faq.html", max_bytes=50 * MB).kind == FileKind.HTML


def test_kind_comes_from_bytes_not_extension() -> None:
    pdf = (SAMPLES / "SmartAir_X1_User_Manual.pdf").read_bytes()
    assert detect(pdf, "innocent.txt", max_bytes=50 * MB).kind == FileKind.PDF
    with pytest.raises(UnsupportedFileError):
        detect(b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 100, "manual.pdf", max_bytes=MB)


def test_html_detected_without_extension_and_markdown_by_extension() -> None:
    assert detect(b"<!DOCTYPE html><html></html>", "page", max_bytes=MB).kind == FileKind.HTML
    assert detect(b"# Title\n\nBody", "notes.md", max_bytes=MB).kind == FileKind.MARKDOWN
    assert detect(b"just text", "notes.txt", max_bytes=MB).kind == FileKind.TEXT


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "empty"),
        (b"%PDF-" + b"x" * 200, "larger than"),
        (b"\x00\x01\x02binary", "Unsupported"),
        (b"\xff\xfe\xfa not utf8", "Unsupported"),
    ],
)
def test_rejects_bad_files(data: bytes, message: str) -> None:
    with pytest.raises(UnsupportedFileError, match=message):
        detect(data, "x", max_bytes=100)


def test_rejects_plain_zip_and_macro_docx() -> None:
    with pytest.raises(UnsupportedFileError, match="not a Word"):
        detect(_zip({"hello.txt": b"hi"}), "x.docx", max_bytes=MB)
    macro = _zip(
        {
            "[Content_Types].xml": b"<Types/>",
            "word/document.xml": b"<w:document/>",
            "word/vbaProject.bin": b"\x00",
        }
    )
    with pytest.raises(UnsupportedFileError, match="macros"):
        detect(macro, "x.docx", max_bytes=MB)


def test_rejects_zip_bomb() -> None:
    bomb = _zip(
        {
            "[Content_Types].xml": b"<Types/>",
            "word/document.xml": b"0" * (20 * MB),  # compresses ~1000:1
        }
    )
    assert len(bomb) < MB
    with pytest.raises(UnsupportedFileError, match="compression bomb"):
        detect(bomb, "x.docx", max_bytes=MB)


def test_safe_display_name() -> None:
    assert safe_display_name("../../etc/passwd") == "passwd"
    assert safe_display_name("C:\\Users\\me\\manual.pdf") == "manual.pdf"
    assert safe_display_name("bad\x00name\n.pdf") == "badname.pdf"
    assert safe_display_name(None) == "upload"
    assert len(safe_display_name("a" * 500)) == 200
