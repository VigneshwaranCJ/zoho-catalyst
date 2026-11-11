"""Golden tests: run the REAL Docling models on the TechNova sample documents.

The sample manual was generated with known content on known pages
(sample-data/technova/generate_samples.py), so we can assert exact page numbers.
This is the Phase 3 exit test: "sample manual extracts with correct headings,
tables and page numbers".

Slow (~1 minute: loading models + converting 12 pages). Skip with: -m "not slow"
"""

import re
from pathlib import Path

import pytest

from app.ingestion.extractor import PAGE_MARKER_RE, DoclingExtractor, ExtractionResult
from app.ingestion.validation import FileKind

pytestmark = pytest.mark.slow

SAMPLES = Path(__file__).resolve().parents[3] / "sample-data" / "technova"

# chapter heading -> page it was printed on
EXPECTED_PAGES = {
    "1. Safety Instructions": 3,
    "2. Product Specifications": 4,
    "3. What's in the Box": 5,
    "4. Installation": 6,
    "5. Connecting to Wi-Fi": 7,
    "6. Using the SmartAir X1": 8,
    "7. Maintenance and Filter Replacement": 9,
    "8. Troubleshooting": 10,
    "9. Warranty Policy": 11,
    "10. Returns and Refunds": 11,
    "11. Frequently Asked Questions": 12,
    "12. Contacting Support": 12,
}


@pytest.fixture(scope="module")
def extractor() -> DoclingExtractor:
    return DoclingExtractor(artifacts_path=None, document_timeout=300)


@pytest.fixture(scope="module")
def manual(extractor: DoclingExtractor) -> ExtractionResult:
    data = (SAMPLES / "SmartAir_X1_User_Manual.pdf").read_bytes()
    return extractor.extract(FileKind.PDF, data)


def _page_text(markdown: str, page: int) -> str:
    """The Markdown between `<!-- page: N -->` and the next marker."""
    parts = PAGE_MARKER_RE.split(markdown)
    # split() yields ["", "1", text1, "2", text2, ...]
    pages = {int(parts[i]): parts[i + 1] for i in range(1, len(parts) - 1, 2)}
    return pages[page]


def test_pdf_page_count_and_markers(manual: ExtractionResult) -> None:
    assert manual.page_count == 12
    markers = [int(m) for m in PAGE_MARKER_RE.findall(manual.markdown)]
    assert markers == list(range(1, 13))


def test_pdf_headings_are_on_the_right_pages(manual: ExtractionResult) -> None:
    found = {h.text: h.page for h in manual.headings}
    for heading, page in EXPECTED_PAGES.items():
        assert found.get(heading) == page, (
            f"{heading!r}: expected page {page}, got {found.get(heading)}"
        )


def test_pdf_facts_land_under_the_right_page_marker(manual: ExtractionResult) -> None:
    md = manual.markdown
    assert "24-month limited warranty" in _page_text(md, 11)
    assert "within 30 days of delivery" in _page_text(md, 11)
    assert "5 GHz networks are not supported" in _page_text(md, 7)
    assert "The device does not turn on" in _page_text(md, 10)
    assert "24-month" not in _page_text(md, 4)  # no bleeding across pages


def test_pdf_tables_are_extracted_as_tables(manual: ExtractionResult) -> None:
    assert manual.table_count == 3  # specifications, modes, troubleshooting
    specs = _page_text(manual.markdown, 4)
    row = next(line for line in specs.splitlines() if "Wi-Fi" in line)
    assert row.startswith("|") and "2.4 GHz" in row  # still a Markdown table row
    assert re.search(r"\|\s*Model number\s*\|\s*TN-SAX1\s*\|", specs)


def test_pdf_page_footer_is_not_body_text(manual: ExtractionResult) -> None:
    # "TechNova Electronics | SmartAir X1 User Manual | v1.2 ... Page N" is page
    # furniture; Docling should keep it out of the body text.
    assert manual.markdown.count("User Manual | v1.2") <= 1


def test_docx_headings_and_table(extractor: DoclingExtractor) -> None:
    data = (SAMPLES / "TechNova_Customer_Service_Policies.docx").read_bytes()
    result = extractor.extract(FileKind.DOCX, data)
    headings = [h.text for h in result.headings]
    for expected in ("Shipping", "Returns and Refunds", "Warranty", "Escalation"):
        assert expected in headings
    assert all(h.page is None for h in result.headings)  # DOCX has no fixed pages
    assert result.page_count is None
    assert "<!-- page:" not in result.markdown
    assert result.table_count == 1
    assert "Within 1 business day" in result.markdown


def test_html_keeps_content_and_drops_clutter(extractor: DoclingExtractor) -> None:
    data = (SAMPLES / "smartair-x1-faq.html").read_bytes()
    result = extractor.extract(FileKind.HTML, data)
    md = result.markdown
    assert "SmartAir X1 Frequently Asked Questions" in md
    assert "24-month limited warranty" in md
    for clutter in ("Cart (0)", "AIRFRESH", "You may also like", "All rights reserved"):
        assert clutter not in md, clutter
    assert "Ignore all previous instructions" not in md
    assert result.stats["html_raw_chars"] > result.stats["html_cleaned_chars"]
