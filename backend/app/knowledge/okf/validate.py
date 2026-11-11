"""OKF validation at two levels.

1. **Conformance with OKF v0.2** (spec §11), the rules every OKF consumer
   relies on: each non-reserved `.md` has parseable YAML frontmatter with a
   non-empty `type`; `index.md` / `log.md` follow §8 / §9.
2. **Our profile** (`csp-okf-profile/1`): required titles/descriptions,
   provenance, footnotes that resolve to `sources[].id`, valid actors and
   timestamps, links that stay inside the bundle.

Errors block publishing; warnings are shown to the human reviewer.
There is no official OKF validator (the spec says "no required tooling"), so
this module is our implementation of §11, tested against the spec's rules.
"""

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from pydantic import ValidationError

from app.knowledge.okf import document as okfdoc
from app.knowledge.okf.profile import OKF_VERSION, ConceptFrontmatter

RESERVED = {"index.md", "log.md"}
LOG_DATE_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)


@dataclass
class Issue:
    level: str  # "error" | "warning"
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"level": self.level, "path": self.path, "message": self.message}


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)

    def error(self, path: str, message: str) -> None:
        self.issues.append(Issue("error", path, message))

    def warning(self, path: str, message: str) -> None:
        self.issues.append(Issue("warning", path, message))

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": [i.as_dict() for i in self.errors],
            "warnings": [i.as_dict() for i in self.warnings],
        }


def _is_reserved(path: str) -> bool:
    return PurePosixPath(path).name in RESERVED


# ------------------------------------------------------------------ level 1: OKF v0.2 §11
def check_conformance(path: str, text: str, report: Report, *, is_root: bool = False) -> None:
    name = PurePosixPath(path).name
    if name == "index.md":
        try:
            doc = okfdoc.parse(text)
        except okfdoc.OkfParseError as exc:
            report.error(path, f"index.md: {exc}")
            return
        if doc.frontmatter is not None:
            # §8: no frontmatter, except `okf_version` in the bundle-root index.md
            allowed = {"okf_version"} if is_root else set()
            extra = set(doc.frontmatter) - allowed
            if extra:
                report.error(
                    path, f"index.md may not carry frontmatter keys {sorted(extra)} (OKF §8)"
                )
        return
    if name == "log.md":
        if okfdoc.FRONTMATTER_RE.match(text):
            report.error(path, "log.md must not have frontmatter (OKF §9)")
        for heading in re.findall(r"^## (.+)$", text, re.MULTILINE):
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", heading.strip()):
                report.error(path, f"log.md date heading {heading!r} is not YYYY-MM-DD (OKF §9)")
        return
    try:
        doc = okfdoc.parse(text)
    except okfdoc.OkfParseError as exc:
        report.error(path, f"{exc} (OKF §11.1)")
        return
    if doc.frontmatter is None:
        report.error(path, "Missing YAML frontmatter (OKF §11.1)")
        return
    type_value = doc.frontmatter.get("type")
    if not isinstance(type_value, str) or not type_value.strip():
        report.error(path, "Frontmatter needs a non-empty `type` (OKF §11.2)")


# ------------------------------------------------------------------ level 2: our profile
def _check_links(
    path: str, doc: okfdoc.OkfDocument, known_paths: set[str] | None, report: Report
) -> None:
    for target in doc.links:
        if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
            if not target.lower().startswith(("https://", "http://", "mailto:")):
                report.error(path, f"Link with unsafe scheme: {target}")
            continue
        target_path = target.split("#", 1)[0]
        if not target_path:
            continue
        if target_path.startswith("/"):
            resolved = target_path.lstrip("/")
        else:
            resolved = str(PurePosixPath(path).parent / target_path)
        normalized = PurePosixPath(resolved)
        if ".." in normalized.parts:
            report.error(path, f"Link escapes the bundle: {target}")
            continue
        # §6.1: broken links are tolerated by consumers; we warn the reviewer.
        if (
            known_paths is not None
            and resolved.rstrip("/") not in known_paths
            and not resolved.endswith("/")
        ):
            report.warning(path, f"Link target not in the bundle (yet): {target}")


def check_profile(
    path: str, text: str, report: Report, *, known_paths: set[str] | None = None
) -> ConceptFrontmatter | None:
    """Validate a concept document against csp-okf-profile/1. Returns the parsed frontmatter."""
    if _is_reserved(path):
        return None
    try:
        doc = okfdoc.parse(text)
    except okfdoc.OkfParseError as exc:
        report.error(path, str(exc))
        return None
    if doc.frontmatter is None:
        report.error(path, "Missing YAML frontmatter")
        return None
    try:
        fm = ConceptFrontmatter.model_validate(doc.frontmatter)
    except ValidationError as exc:
        for err in exc.errors():
            location = ".".join(str(p) for p in err["loc"]) or "frontmatter"
            report.error(path, f"{location}: {err['msg']}")
        return None

    source_ids = [s.id for s in fm.sources]
    if len(source_ids) != len(set(source_ids)):
        report.error(path, "sources[].id values must be unique")
    refs = doc.footnote_refs
    defs = doc.footnote_defs
    for label in sorted(set(refs)):
        if label not in source_ids:
            report.error(path, f"Footnote [^{label}] does not match any sources[].id (OKF §5.1)")
        if label not in defs:
            report.error(path, f"Footnote [^{label}] has no definition line")
    for label in defs:
        if label not in refs:
            report.warning(path, f"Footnote definition [^{label}] is never used")
    if fm.type != "Source Document" and not refs:
        report.error(path, "No footnote citations: every fact must cite its source")
    if not okfdoc.headings(doc.body):
        report.warning(path, "No headings: sections make retrieval and citations more precise")
    for source in fm.sources:
        if source.resource.startswith("/") and known_paths is not None:
            if source.resource.lstrip("/").split("#", 1)[0] not in known_paths:
                report.warning(path, f"Source resource not in the bundle: {source.resource}")
    _check_links(path, doc, known_paths, report)
    return fm


def validate_bundle(files: dict[str, str], *, profile: bool = True) -> Report:
    """Validate a whole bundle: {bundle-relative path: file text}."""
    report = Report()
    known = {p for p in files}
    for path, text in sorted(files.items()):
        if not path.endswith(".md"):
            continue
        check_conformance(path, text, report, is_root=(path == "index.md"))
        if profile and not _is_reserved(path):
            check_profile(path, text, report, known_paths=known)
    root_index = files.get("index.md")
    if root_index is not None:
        fm = okfdoc.parse(root_index).frontmatter or {}
        if str(fm.get("okf_version", "")) != OKF_VERSION:
            report.warning("index.md", f'Root index.md should declare okf_version: "{OKF_VERSION}"')
    return report
