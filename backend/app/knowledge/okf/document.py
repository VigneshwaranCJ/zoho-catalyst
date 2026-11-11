"""Reading and writing OKF documents (Markdown + YAML frontmatter).

    ---
    type: Policy
    title: SmartAir X1 Warranty Policy
    ...
    ---
    # Warranty period
    The SmartAir X1 has a 24-month limited warranty.[^x1-manual-p11]

    [^x1-manual-p11]: SmartAir X1 User Manual, page 11

YAML is parsed with a *safe* loader (no arbitrary Python objects) and written
with stable key order. Unknown keys survive a parse -> render round trip
(spec §4.1: consumers SHOULD preserve them).
"""

import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
FOOTNOTE_REF_RE = re.compile(r"\[\^([^\]\s]+)\](?!:)")
FOOTNOTE_DEF_RE = re.compile(r"^\[\^([^\]\s]+)\]:[ \t]*(.*)$", re.MULTILINE)
HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


class OkfParseError(ValueError):
    pass


def _yaml() -> YAML:
    y = YAML(typ="safe", pure=True)
    y.default_flow_style = False
    y.sort_base_mapping_type_on_output = False  # type: ignore[assignment]  # keep key order
    y.allow_unicode = True
    y.width = 4096
    return y


def _plain(value: Any) -> Any:
    """Turn YAML-native dates into ISO strings so documents round-trip as text."""
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


@dataclass
class OkfDocument:
    frontmatter: dict[str, Any] | None  # None = file has no frontmatter block
    body: str

    @property
    def footnote_refs(self) -> list[str]:
        return FOOTNOTE_REF_RE.findall(self.body)

    @property
    def footnote_defs(self) -> dict[str, str]:
        return dict(FOOTNOTE_DEF_RE.findall(self.body))

    @property
    def links(self) -> list[str]:
        return LINK_RE.findall(self.body)


def parse(text: str) -> OkfDocument:
    text = text.lstrip("﻿")
    match = FRONTMATTER_RE.match(text)
    if not match:
        return OkfDocument(None, text)
    try:
        data = _yaml().load(match.group(1))
    except YAMLError as exc:
        raise OkfParseError(f"Invalid YAML frontmatter: {exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise OkfParseError("Frontmatter must be a YAML mapping (key: value pairs).")
    return OkfDocument(_plain(data), text[match.end() :])


def render(frontmatter: dict[str, Any] | None, body: str) -> str:
    body = body.strip("\n") + "\n"
    if frontmatter is None:
        return body
    buffer = io.StringIO()
    _yaml().dump(_plain(frontmatter), buffer)
    return f"---\n{buffer.getvalue().rstrip()}\n---\n\n{body}"


def slugify(text: str, max_length: int = 60) -> str:
    """'9. Warranty Policy!' -> '9-warranty-policy' (ASCII, lowercase, hyphens)."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:max_length].rstrip("-") or "untitled"


def headings(body: str) -> list[tuple[int, str]]:
    return [(len(m.group(1)), m.group(2).strip()) for m in HEADING_RE.finditer(body)]
