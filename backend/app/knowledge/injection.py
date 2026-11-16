"""Prompt-injection scanner for untrusted documents and AI drafts.

Uploaded documents and web pages may contain text written to manipulate an AI
("ignore all previous instructions...", hidden text on a web page). This
scanner flags such passages so that:

* the human reviewer sees a warning (and must explicitly acknowledge it), and
* AI-drafted statements containing such text are dropped.

This is ONE layer of defence, not a guarantee: the generation prompt also
treats documents as data, and nothing in a document can ever trigger an action
(the answer-generation step in Phase 5 has no tools). See SECURITY_DESIGN §6.
"""

import re
from dataclasses import dataclass

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("override_instructions", re.compile(
        r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|system)\b"
        r"[^.\n]{0,20}\b(instructions?|prompts?|rules|messages?)\b", re.I)),
    ("role_hijack", re.compile(
        r"\byou are now\b|\b(act|behave) as (an? )?(admin|administrator|developer|system)\b"
        r"|\b(admin|developer|god|jailbreak|dan) mode\b", re.I)),
    ("fake_system_message", re.compile(
        r"(^|\n|\s)(system|assistant|developer)\s*(notice|message|prompt|override)?\s*:\s", re.I)),
    ("prompt_exfiltration", re.compile(
        r"\b(reveal|print|show|repeat|output)\b[^.\n]{0,30}"
        r"\b(system prompt|instructions|hidden prompt)\b",
        re.I)),
    ("tool_abuse", re.compile(
        r"\b(create|open|file|submit)\b[^.\n]{0,30}\b(tickets?|refunds?)\b[^.\n]{0,40}"
        r"\b(every|each|all)\b", re.I)),
    ("model_tokens", re.compile(r"<\|?(im_start|im_end|system|endoftext)\|?>|\[/?INST\]", re.I)),
]  # fmt: skip

ZERO_WIDTH_RE = re.compile("[​-‏⁠-⁤﻿‪-‮]")
_HIDDEN_STYLE_RE = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden"
    r"|font-size\s*:\s*0(px|pt|em|rem)?\s*(;|$)|opacity\s*:\s*0(\.0+)?\s*(;|$)",
    re.I,
)
_CSS_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")


@dataclass(frozen=True, slots=True)
class Finding:
    kind: str
    excerpt: str

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "excerpt": self.excerpt}


def _excerpt(text: str, start: int, end: int, width: int = 60) -> str:
    snippet = text[max(0, start - width) : end + width]
    return re.sub(r"\s+", " ", snippet).strip()[:200]


def scan_text(text: str) -> list[Finding]:
    findings: list[Finding] = []
    for kind, pattern in PATTERNS:
        for match in pattern.finditer(text):
            findings.append(Finding(kind, _excerpt(text, match.start(), match.end())))
    if ZERO_WIDTH_RE.search(text):
        findings.append(Finding("invisible_characters", "zero-width or bidi control characters"))
    return findings


def scan_html(html: str) -> list[Finding]:
    """Scan raw HTML: injection phrases AND text hidden from human visitors."""
    from lxml import html as lxml_html  # type: ignore[import-untyped]  # ships with trafilatura

    findings = scan_text(re.sub(r"<[^>]+>", " ", html))
    try:
        root = lxml_html.fromstring(html)
    except (ValueError, lxml_html.etree.ParserError):
        return findings

    hidden_classes: set[str] = set()
    for style in root.iter("style"):
        for selector, body in _CSS_RULE_RE.findall(style.text_content()):
            if _HIDDEN_STYLE_RE.search(body):
                hidden_classes.update(re.findall(r"\.([\w-]+)", selector))

    for element in root.iter():
        if not isinstance(element.tag, str) or element.tag in {"style", "script", "head"}:
            continue
        inline = element.get("style", "")
        classes = set((element.get("class") or "").split())
        hidden = (
            element.get("hidden") is not None
            or element.get("aria-hidden") == "true"
            or bool(_HIDDEN_STYLE_RE.search(inline))
            or bool(classes & hidden_classes)
        )
        if hidden:
            text = re.sub(r"\s+", " ", element.text_content()).strip()
            if len(text) >= 20:  # ignore empty icons / tiny decorative spans
                findings.append(Finding("hidden_text", text[:200]))
    return findings
