"""OKF v0.2 conformance (spec §11) and csp-okf-profile/1 rules."""

import pytest

from app.knowledge.okf import bundle as okfbundle
from app.knowledge.okf import document as okfdoc
from app.knowledge.okf.profile import ActorEvent, profile_json_schema, trust_tier
from app.knowledge.okf.validate import Report, check_conformance, check_profile, validate_bundle
from tests.fixtures.technova_bundle import BUNDLE

WARRANTY = BUNDLE["policies/smartair-x1-warranty.md"]


def _conformance(path: str, text: str, *, is_root: bool = False) -> list[str]:
    report = Report()
    check_conformance(path, text, report, is_root=is_root)
    return [i.message for i in report.errors]


def _profile(path: str, text: str, known: set[str] | None = None) -> Report:
    report = Report()
    check_profile(path, text, report, known_paths=known)
    return report


# ---------------------------------------------------------------- document parse/render
def test_round_trip_preserves_unknown_keys_and_order() -> None:
    text = "---\ntype: Policy\nzeta: 1\nalpha: keep\nnested: {b: 2, a: 1}\n---\n# H\nBody\n"
    doc = okfdoc.parse(text)
    assert list(doc.frontmatter) == ["type", "zeta", "alpha", "nested"]
    again = okfdoc.parse(okfdoc.render(doc.frontmatter, doc.body))
    assert again.frontmatter == doc.frontmatter
    assert again.body.strip() == "# H\nBody"


def test_timestamps_stay_strings_with_offset() -> None:
    doc = okfdoc.parse("---\ntype: X\ngenerated: {by: a/b, at: 2026-11-11T10:00:00+00:00}\n---\n")
    assert doc.frontmatter["generated"]["at"] == "2026-11-11T10:00:00+00:00"


def test_yaml_is_parsed_safely() -> None:
    with pytest.raises(okfdoc.OkfParseError):
        okfdoc.parse("---\ntype: !!python/object/apply:os.system ['echo hacked']\n---\n")
    with pytest.raises(okfdoc.OkfParseError, match="mapping"):
        okfdoc.parse("---\n- just\n- a list\n---\n")


def test_footnotes_and_links_are_found() -> None:
    doc = okfdoc.parse(WARRANTY)
    assert set(doc.footnote_refs) == {"smartair-x1-user-manual-p11"}
    assert "smartair-x1-user-manual-p11" in doc.footnote_defs


def test_slugify() -> None:
    assert okfdoc.slugify("9. Warranty Policy!") == "9-warranty-policy"
    assert okfdoc.slugify("Café Ünïcode") == "cafe-unicode"
    assert okfdoc.slugify("***") == "untitled"


# ---------------------------------------------------------------- OKF §11 conformance
def test_minimal_concept_with_only_type_is_conformant() -> None:
    assert _conformance("x.md", "---\ntype: Reference\n---\nhello\n") == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("no frontmatter at all\n", "Missing YAML frontmatter"),
        ("---\ntitle: x\n---\nbody\n", "non-empty `type`"),
        ("---\ntype: ''\n---\nbody\n", "non-empty `type`"),
        ("---\ntype: [broken\n---\nbody\n", "Invalid YAML"),
    ],
)
def test_non_conformant_concepts(text: str, expected: str) -> None:
    assert any(expected in e for e in _conformance("x.md", text))


def test_index_md_rules() -> None:
    assert _conformance("index.md", '---\nokf_version: "0.2"\n---\n# A\n', is_root=True) == []
    assert _conformance("products/index.md", '---\nokf_version: "0.2"\n---\n# A\n')  # not root
    assert _conformance("index.md", "---\ntitle: x\n---\n# A\n", is_root=True)
    assert _conformance("products/index.md", "# Products\n\n* [A](/products/a.md) - desc\n") == []


def test_log_md_rules() -> None:
    assert _conformance("log.md", "# Log\n\n## 2026-11-11\n* **Update**: x\n") == []
    assert _conformance("log.md", "# Log\n\n## November 11\n* x\n")


# ---------------------------------------------------------------- profile
def test_fixture_bundle_concepts_pass_the_profile() -> None:
    for path, text in BUNDLE.items():
        report = _profile(path, text)
        assert report.ok, (path, report.as_dict())


def test_footnote_must_match_a_source_id() -> None:
    broken = WARRANTY.replace(
        "warranty from the date of purchase.[^smartair-x1-user-manual-p11]",
        "warranty from the date of purchase.[^made-up]",
    )
    messages = [i.message for i in _profile("p.md", broken).errors]
    assert any("[^made-up] does not match any sources[].id" in m for m in messages)


def test_concept_without_citations_is_rejected() -> None:
    text = okfdoc.render(
        {**okfdoc.parse(WARRANTY).frontmatter},
        "# Warranty\n\nThe warranty is great.\n",
    )
    assert any("No footnote citations" in i.message for i in _profile("p.md", text).errors)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("title", None, "title"),
        ("audience", "everyone", "audience"),
        ("generated", {"by": "not an actor!"}, "generated.by"),
        ("generated", {"by": "a/b", "at": "2026-11-11T10:00:00"}, "offset"),
        ("status", "published", "status"),
    ],
)
def test_profile_field_rules(field: str, value: object, message: str) -> None:
    doc = okfdoc.parse(WARRANTY)
    fm = dict(doc.frontmatter)
    if value is None:
        fm.pop(field)
    else:
        fm[field] = value
    errors = _profile("p.md", okfdoc.render(fm, doc.body)).errors
    assert any(message in i.message for i in errors), [i.message for i in errors]


def test_bare_verified_mapping_is_accepted() -> None:
    doc = okfdoc.parse(WARRANTY)
    fm = {**doc.frontmatter, "verified": {"by": "human:priya", "at": "2026-11-11T10:00:00+00:00"}}
    assert _profile("p.md", okfdoc.render(fm, doc.body)).ok


def test_links_must_stay_inside_the_bundle() -> None:
    doc = okfdoc.parse(WARRANTY)
    body = doc.body + "\nSee [secret](../../etc/passwd) and [x](javascript:alert(1)).\n"
    errors = [
        i.message for i in _profile("policies/p.md", okfdoc.render(doc.frontmatter, body)).errors
    ]
    assert any("escapes the bundle" in e for e in errors)
    assert any("unsafe scheme" in e for e in errors)


def test_broken_internal_link_is_only_a_warning() -> None:
    doc = okfdoc.parse(WARRANTY)
    body = doc.body + "\nSee [refunds](/policies/not-written-yet.md).\n"
    report = _profile(
        "policies/p.md", okfdoc.render(doc.frontmatter, body), known={"policies/p.md"}
    )
    assert report.ok and any("not in the bundle" in w.message for w in report.warnings)


def test_trust_tiers() -> None:
    assert trust_tier([]) == "unverified"
    assert trust_tier([ActorEvent(by="process:check")]) == "machine-confirmed"
    assert (
        trust_tier([ActorEvent(by="process:check"), ActorEvent(by="human:priya")])
        == "human-reviewed"
    )


def test_profile_json_schema_export() -> None:
    schema = profile_json_schema()
    assert "csp-okf-profile/1" in schema["$id"]
    assert set(schema["required"]) >= {
        "type",
        "title",
        "description",
        "sources",
        "generated",
        "audience",
    }


# ---------------------------------------------------------------- generated bundle files
def test_generated_indexes_and_log_are_conformant() -> None:
    files = dict(BUNDLE)
    files.update(okfbundle.build_indexes(BUNDLE, bundle_title="TechNova Knowledge"))
    from datetime import date

    files["log.md"] = okfbundle.add_log_entry(
        None, day=date(2026, 11, 11), entries=["**Creation**: x"]
    )
    files["log.md"] = okfbundle.add_log_entry(
        files["log.md"], day=date(2026, 11, 12), entries=["**Update**: y"]
    )
    report = validate_bundle(files, profile=False)
    assert report.ok, report.as_dict()
    assert okfdoc.parse(files["index.md"]).frontmatter == {"okf_version": "0.2"}
    assert "* [Returns and Refunds](/policies/returns-and-refunds.md)" in files["policies/index.md"]
    assert files["log.md"].index("2026-11-12") < files["log.md"].index("2026-11-11")  # newest first
