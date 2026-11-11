"""Deterministic checks that every AI-written statement is supported by the source.

The AI must give, for each statement, an exact quote from the source and the
page it is on. Here, in plain code (no AI), we check:

1. The quote really appears in the source (after normalizing whitespace,
   Markdown table pipes, curly quotes and dashes). If it's on a different page
   than claimed, the page is corrected.
2. Every number in the statement ("24-month", "30 days", "2.4 GHz") also
   appears on that page, because invented numbers are the most damaging kind
   of AI mistake in customer support.

Statements failing either check are dropped and reported to the human reviewer.
"""

import re
import unicodedata
from dataclasses import dataclass

from app.ingestion.extractor import PAGE_MARKER_RE

MIN_QUOTE_CHARS = 12
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
# Curly quotes, dashes, minus sign and no-break space -> plain ASCII; Markdown
# punctuation -> spaces. Written as code points so the source stays unambiguous.
_TRANSLATE: dict[int, str] = str.maketrans(
    {
        0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"',
        0x2013: "-", 0x2014: "-", 0x2212: "-", 0x00A0: " ",
        ord("|"): " ", ord("*"): " ", ord("_"): " ", ord("#"): " ", ord("`"): " ", ord(">"): " ",
    }
)  # fmt: skip


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_TRANSLATE).lower()
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True, slots=True)
class SourcePages:
    """The extracted source split into pages ({None: text} for unpaged formats)."""

    pages: dict[int | None, str]

    @classmethod
    def from_markdown(cls, markdown: str) -> "SourcePages":
        parts = PAGE_MARKER_RE.split(markdown)
        if len(parts) == 1:
            return cls({None: markdown})
        return cls({int(parts[i]): parts[i + 1] for i in range(1, len(parts) - 1, 2)})

    @property
    def paged(self) -> bool:
        return None not in self.pages

    def normalized(self) -> dict[int | None, str]:
        return {p: normalize(t) for p, t in self.pages.items()}

    def text_for(self, pages: list[int]) -> str:
        """Source text for the given pages, with page markers (all text if unpaged)."""
        if not self.paged:
            return self.pages[None]
        chosen = sorted({p for p in pages if p in self.pages}) or sorted(
            p for p in self.pages if p is not None
        )
        return "\n\n".join(f"<!-- page: {p} -->\n{self.pages[p]}" for p in chosen)


@dataclass(frozen=True, slots=True)
class QuoteCheck:
    ok: bool
    page: int | None  # corrected page (None for unpaged sources)
    reason: str = ""


def check_statement(
    text: str, quote: str, claimed_page: int | None, normalized_pages: dict[int | None, str]
) -> QuoteCheck:
    q = normalize(quote)
    if len(q) < MIN_QUOTE_CHARS:
        return QuoteCheck(False, claimed_page, "quote too short to verify")

    found_page: int | None
    if claimed_page in normalized_pages and q in normalized_pages[claimed_page]:
        found_page = claimed_page
    else:
        matches = [p for p, t in normalized_pages.items() if q in t]
        if not matches:
            return QuoteCheck(False, claimed_page, "quote not found in the source")
        found_page = matches[0]

    page_text = normalized_pages[found_page]
    missing = [n for n in _NUMBER_RE.findall(text) if normalize(n) not in page_text]
    if missing:
        return QuoteCheck(
            False, found_page, f"number(s) {', '.join(missing)} not found on the source page"
        )
    return QuoteCheck(True, found_page)
