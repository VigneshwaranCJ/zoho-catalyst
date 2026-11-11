"""Generated bundle files: `index.md` per directory (OKF §8) and `log.md` (§9).

These are always regenerated from the concept documents on publish, so humans
and AI never edit them by hand (and they never cause merge conflicts).
"""

from collections import defaultdict
from datetime import date
from pathlib import PurePosixPath

from app.knowledge.okf import document as okfdoc
from app.knowledge.okf.profile import OKF_VERSION

SECTION_TITLES = {
    "company": "Company",
    "products": "Products",
    "policies": "Policies",
    "support": "Support",
    "sources": "Sources",
}


def build_indexes(concepts: dict[str, str], *, bundle_title: str) -> dict[str, str]:
    """Return {path: content} for the root index.md and one index.md per folder."""
    by_dir: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for path, text in sorted(concepts.items()):
        if PurePosixPath(path).name in {"index.md", "log.md"}:
            continue
        fm = okfdoc.parse(text).frontmatter or {}
        title = str(fm.get("title") or PurePosixPath(path).stem.replace("-", " ").title())
        desc = str(fm.get("description") or "").replace("\n", " ").strip()
        by_dir[str(PurePosixPath(path).parent)].append((PurePosixPath(path).name, title, desc))

    result: dict[str, str] = {}
    root_lines = [f"# {bundle_title}", ""]
    for directory in sorted(d for d in by_dir if d != "."):
        heading = SECTION_TITLES.get(directory, directory.replace("-", " ").title())
        lines = [f"# {heading}", ""]
        for name, title, desc in by_dir[directory]:
            lines.append(f"* [{title}](/{directory}/{name})" + (f" - {desc}" if desc else ""))
        result[f"{directory}/index.md"] = "\n".join(lines) + "\n"
        root_lines.append(f"* [{heading}](/{directory}/) - {len(by_dir[directory])} documents")
    for name, title, desc in by_dir.get(".", []):
        root_lines.append(f"* [{title}](/{name})" + (f" - {desc}" if desc else ""))
    result["index.md"] = okfdoc.render({"okf_version": OKF_VERSION}, "\n".join(root_lines))
    return result


def add_log_entry(existing: str | None, *, day: date, entries: list[str]) -> str:
    """Prepend entries under a `## YYYY-MM-DD` heading (newest first, OKF §9)."""
    heading = f"## {day.isoformat()}"
    bullets = "\n".join(f"* {e}" for e in entries)
    if not existing:
        return f"# Knowledge Update Log\n\n{heading}\n{bullets}\n"
    if heading in existing:
        return existing.replace(heading, f"{heading}\n{bullets}", 1)
    title, _, rest = existing.partition("\n\n")
    return f"{title}\n\n{heading}\n{bullets}\n\n{rest}".rstrip("\n") + "\n"
