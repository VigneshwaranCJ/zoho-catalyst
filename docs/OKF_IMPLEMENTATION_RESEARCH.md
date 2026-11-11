# OKF Implementation Research

> Last updated: 2026-11-11. Verified against the raw `SPEC.md` of the canonical repository on this date.

## 1. What OKF actually is

**Open Knowledge Format (OKF)** is an open specification published by **Google Cloud** for storing knowledge as a **directory of Markdown files with YAML frontmatter** ("a bundle") that both humans and AI agents can read.

| Fact | Value | Source |
|---|---|---|
| Canonical repo | `github.com/GoogleCloudPlatform/open-knowledge-format` (spec in `SPEC.md`) | repo README |
| Old location | `GoogleCloudPlatform/knowledge-catalog/okf`. **Frozen snapshot, no longer maintained**. Google's blog posts still link here, so don't build against it | knowledge-catalog `okf/README.md` |
| Current version | **v0.2** (announced 2026-07-25). v0.1 was announced 2026-06-13 | cloud.google.com blog, "OKF v0.2 adds trust signals" |
| License | Apache-2.0 | repo `LICENSE.md` |
| Maturity | **Early / pre-1.0.** No tagged releases. Google calls v0.1 "a starting point" and its tools proofs of concept. Last spec commit 2026-08-21 (timestamps changed to ISO 8601 with explicit offset) | repo commit history |
| Official validator / JSON Schema | **None.** The spec deliberately has "no required tooling" | `SPEC.md` |
| Reference implementation | Python 3.13 `reference_agent` in the repo (builds bundles from BigQuery metadata + web crawl). Not on PyPI | repo |
| Third-party Python lib | `okflib` (Gwenlake, Apache-2.0, v0.5.0, 2026-08-14). Reads/writes and validates v0.1/v0.2. **Unevaluated**: we'll test it in Phase 4 and fall back to our own validator | PyPI |

> ⚠️ Name collision: "OKF" also stands for the **Open Knowledge Foundation**, an unrelated non-profit. When searching, use "Open Knowledge Format".

**Classification: experimental.** The format is small and simple, which keeps it low-risk. But fields may change in v0.3+, so we isolate all OKF parsing and writing in one module (`backend/app/knowledge/okf/`).

## 2. The v0.2 rules, in plain language

### 2.1 Bundle structure (§3)
- A bundle is a folder tree of `.md` files. **We choose the folders**: the spec does not dictate them.
- Recommended distribution: **a Git repository**. That's our plan anyway.
- **Reserved filenames** at any level: `index.md` (directory listing) and `log.md` (change history). They can't be concept documents.
- Every other `.md` file is a **concept document**.

### 2.2 Concept document (§4)
```markdown
---
type: Policy            # REQUIRED, the only always-required key
title: Warranty Policy  # recommended
description: One-sentence summary.   # recommended
resource: <canonical URI of the thing described>   # recommended, optional
tags: [warranty, smartair-x1]        # recommended
# optional families: sources, usage_window, generated, verified, status, stale_after
# plus any producer-defined extension keys
---
# Body: standard Markdown, prefer headings/lists/tables
```
- `type` values are **not centrally registered**. We define our own vocabulary (§4 below).
- Extra keys are allowed. Consumers must preserve them and must not reject unknown keys.

### 2.3 Provenance, trust and lifecycle (§5)
| Field | Meaning |
|---|---|
| `sources[]` | What the concept was derived from. Each entry: `resource` (**required**: URL, bundle path, or scope descriptor), optional `id`, `title`, `author`, `usage_count`, `last_modified` |
| `usage_window` | `{from, to}` frame for `usage_count` |
| Per-claim citations | **Markdown footnotes whose label is a `sources[].id`**, e.g. `Two years of coverage.[^manual]` |
| `generated` | `{by: <actor>, at: <ISO-8601>}`, who/what wrote the content and when (`by` required) |
| `verified` | list of `{by, at}`. A bare single mapping is also valid |
| Trust tier (derived, not stored) | no `verified` → *unverified*. Only non-human verifiers → *machine-confirmed*. Any `human:<id>` → *human-reviewed* |
| `status` | `draft` / `stable` / `deprecated` (absent = `stable`) |
| `stale_after` | absolute ISO-8601 instant after which content is stale |

**Actor convention (§7):** `<producer>/<version>` for tools (e.g. `csp-ingestor/claude-sonnet-5-5`), `human:<id>` for people, `process:<id>` for automated jobs. The `human:` prefix is mandatory for human-reviewed content.

### 2.4 Links (§6)
- Standard Markdown links. **Bundle-relative paths starting with `/` are recommended** (`[Refund policy](/policies/refund-policy.md)`).
- Links are **untyped** relationships. Broken links must be tolerated (they may mean "not written yet").

### 2.5 `index.md` and `log.md` (§8, §9)
- `index.md` lists the folder's content under headings, `* [Title](path) - description`. It has **no frontmatter**, except that the **bundle-root** `index.md` may carry `okf_version: "0.2"`.
- `log.md`: newest-first `## YYYY-MM-DD` headings with prose bullets (`**Update**`, `**Creation**` …).

### 2.6 Conformance (§11)
A bundle conforms if: (1) every non-reserved `.md` has parseable YAML frontmatter, (2) each has a non-empty `type`, (3) `index.md`/`log.md` follow §8/§9. Consumers must not reject a bundle for missing optional fields, unknown types or keys, broken links, or missing `index.md`.

## 3. What OKF does **not** give us (gaps we fill)

The brief warned: "do not assume ordinary Markdown with YAML satisfies OKF". The reverse is also true: **OKF conformance alone is too weak for customer-facing support answers.** OKF only requires `type`. We add a **stricter, OKF-compatible profile** using extension keys, which the spec explicitly permits.

| Need | OKF v0.2 | Our addition (profile `csp-okf-profile/1`) |
|---|---|---|
| Page numbers in citations | Not specified | per-source extension key `locators: [{page: 12, section: "Warranty"}]` |
| Content hash of source file | Not specified | `sha256` on each `sources[]` entry |
| Tenant | Not specified (bundle = tenant repo, so not needed in files) | — |
| Section-level IDs | Not specified | stable heading anchors, generated from heading text and checked unique |
| Answerability / audience | Not specified | `audience: customer \| internal`. `internal` docs are never shown to customers |
| Escalation hints | Not specified | `escalation: {required_for: [...]}` e.g. legal or refund disputes |
| Product scoping | Not specified | `products: [smartair-x1]` |
| Schema validation | No official schema | our **JSON Schema for the frontmatter** + structural checks |

**Two validation levels:**
1. **OKF v0.2 conformance** (the spec's §11 rules), so the bundle remains portable to any OKF consumer.
2. **Profile validation** (our stricter rules), required before publishing: `title`, `description`, `sources` (≥1, each with `id`), every footnote label resolves to a `sources[].id`, every source `resource` resolves to a file in `/sources/` or a recorded URL, `generated` present, `audience` present, no prompt-injection warnings left unresolved.

## 4. Our bundle layout (one Git repo per organization)

The brief's example used `products/index.md` etc. That fits OKF, **provided those `index.md` files carry no frontmatter**.

```
knowledge-repos/<org-id>/            ← Git repository = OKF bundle
  index.md                           ← root, frontmatter: okf_version: "0.2"
  log.md
  company/
    index.md
    about-technova.md                (type: Company Profile)
  products/
    index.md
    smartair-x1-overview.md          (type: Product)
    smartair-x1-specifications.md    (type: Specification)
    smartair-x1-installation.md      (type: Procedure)
    smartair-x1-troubleshooting.md   (type: Troubleshooting Guide)
  policies/
    index.md
    warranty-policy.md               (type: Policy)
    refund-policy.md                 (type: Policy)
  support/
    index.md
    faq.md                           (type: FAQ)
    escalation-policy.md             (type: Policy, audience: internal)
  sources/                           ← "references/" convention, renamed for clarity
    index.md
    smartair-x1-manual.md            (type: Source Document, an extracted text mirror of the PDF with page markers)
```

Original binaries (PDF/DOCX) are **not** committed to Git (they're large binaries). They live in object storage, referenced by `sha256`. The `sources/*.md` mirror holds the extracted text, so citations stay verifiable from the bundle alone.

**Type vocabulary** (ours): `Company Profile`, `Product`, `Specification`, `Procedure`, `Troubleshooting Guide`, `Policy`, `FAQ`, `Source Document`, `Contact Info`. Unknown types from imported bundles are accepted and treated as generic.

## 5. Example concept document (SmartAir X1 warranty)

```markdown
---
type: Policy
title: SmartAir X1 Warranty Policy
description: Coverage period, what is and isn't covered, and how to make a warranty claim for the SmartAir X1.
tags: [warranty, smartair-x1, policy]
status: stable
sources:
  - id: x1-manual
    resource: /sources/smartair-x1-manual.md
    title: SmartAir X1 User Manual (SmartAir_X1_Manual.pdf)
    author: team:technova-product
    last_modified: 2026-10-01T00:00:00+00:00
    sha256: 9f2c…e1                      # profile extension
    locators:                            # profile extension
      - { page: 14, section: "7. Warranty" }
generated: { by: csp-ingestor/claude-sonnet-5-5, at: 2026-11-11T10:20:00+00:00 }
verified:
  - { by: process:csp-citation-check, at: 2026-11-11T10:20:05+00:00 }
  - { by: human:priya.editor, at: 2026-11-11T11:02:00+00:00 }
audience: customer                       # profile extension
products: [smartair-x1]                  # profile extension
---
# Warranty period

The SmartAir X1 is covered by a **24-month limited warranty** from the date of purchase.[^x1-manual]

# What is covered
…

# How to claim
See [Contacting support](/support/faq.md#how-do-i-contact-support).

[^x1-manual]: SmartAir X1 User Manual, p. 14, §7 "Warranty".
```

In the example, a `human:` verifier makes this *human-reviewed* (§5.3), and the footnote label `x1-manual` joins to `sources[].id`. That gives us document name, page, section and knowledge file for the citation.

## 6. Knowledge engine: how the agent navigates OKF (no vector DB)

OKF is designed for **progressive disclosure**: an agent reads `index.md` → picks a folder → reads concept descriptions → opens the right file → reads the right section. We combine that with a classic keyword index:

```
             ┌──────────────── Knowledge Discovery node ────────────────┐
Question ──► │ 1. Catalog: compact list of {path, type, title, desc,    │
             │    tags} for all live docs (≈ 30–80 tokens per doc)      │
             │ 2. PostgreSQL full-text search (tsvector, websearch_to_  │
             │    tsquery, ts_rank_cd) + pg_trgm for typos, over        │
             │    knowledge_sections → top 10 candidate sections        │
             │ 3. Claude Haiku picks the 1–5 most relevant sections     │
             │    from (catalog + candidates), or "none"                │
             └──────────────────────────────────────────────────────────┘
                                     │
             Knowledge Retrieval: load the full sections (+ parent heading
             context, + linked concepts 1 hop away if needed)
```

Why this works without embeddings for support knowledge:
- Company support bases are **small** (tens to a few thousand sections), **well-structured** and **terminology-consistent** (product names, policy names).
- The catalog of titles and descriptions lets Claude reason about *which document should* contain the answer. For example, "can I send it back after 15 days?" maps to the refund policy even with no shared keywords. A pure keyword search would miss that, and this is the main thing embeddings are usually added for.
- Exact, auditable retrieval: we know *why* a section was chosen.

### 7. When we **would** add vector / hybrid search (decision criteria)

Add `pgvector` (inside the same PostgreSQL, no separate vector DB) **only if** the evaluation shows a need:

| Trigger | Threshold |
|---|---|
| Retrieval recall@5 on eval set | < 90 % after tuning synonyms, descriptions and tags |
| Catalog no longer fits a cheap prompt | > ~1,500 live documents per org (catalog > ~100k tokens) |
| Many paraphrase/synonym misses in unanswered-question report | sustained > 5 % of questions |
| Multilingual knowledge (question language ≠ document language) | any |

Even then, embeddings stay a **retrieval aid**: OKF files remain the source of truth, and citations still point to OKF sections.

## 8. Generation pipeline (document → OKF)

1. **Extract** (Docling): text, heading hierarchy, tables, page numbers (`prov.page_no`). Saved as Docling JSON.
2. **Source mirror**: write `sources/<slug>.md` (type `Source Document`) with page markers `<!-- page: 12 -->` so quotes can be located by page.
3. **Plan** (Claude Sonnet, structured output): propose concept documents (path, type, title, description, which source pages/sections feed each).
4. **Draft** (Claude Sonnet, structured output): for each concept, write the body. **Every factual sentence must end with a footnote**, and footnotes must carry an exact supporting quote and page. The model returns JSON. **Our code** renders the Markdown and frontmatter, so YAML is always well-formed.
5. **Verify** (deterministic): each quote must appear in the source mirror on the claimed page (normalized whitespace/case). Failures go back to the model once, then get flagged for human review.
6. **Injection scan** of source text and output.
7. **Validate**: OKF conformance + profile JSON Schema. Generate `index.md` and `log.md` entries.
8. **Review UI**: diff vs current version, warnings, approve/reject. On approval, set `status: stable` and add `verified: human:<user>`, then **Git commit** (author = reviewer), then re-index `knowledge_sections`.

**As built (Phase 4):** drafts live in the database (`knowledge_versions`, `review_status = pending`) until a person approves them. Approval writes **one Git commit on `main`** containing the approved files plus regenerated `index.md` / `log.md`. So Git history is exactly the publication history, and there are no draft branches to merge or conflict. (The original plan used one branch per job. Drafts-in-the-database was simpler and removes merge conflicts entirely.) Concurrent edits are detected with `base_version_id`: a draft based on an outdated version is refused.

Implementation: `backend/app/knowledge/` (`okf/` parse, validate, bundle files; `generation.py`; `quotes.py`; `injection.py`; `indexer.py`; `repo.py`) and `backend/app/services/knowledge_publish.py`. Profile schema: [okf-profile.schema.json](okf-profile.schema.json).

## 9. Libraries

| Purpose | Choice | Notes |
|---|---|---|
| Frontmatter parse/write | `python-frontmatter` + `ruamel.yaml` (round-trip, preserves unknown keys and order) | the spec says consumers SHOULD preserve unknown keys |
| Markdown parsing (headings, footnotes, links) | `markdown-it-py` + `mdit-py-plugins` (footnote plugin) | |
| JSON Schema | `jsonschema` (Draft 2020-12) | for our profile |
| OKF conformance | own validator (~200 lines). `okflib` evaluated in Phase 4 as cross-check | no official tool exists |
| Git | `pygit2` (libgit2 bindings, no git CLI needed in container) or `GitPython` | decide in Phase 4. `GitPython` is simpler, `pygit2` is safer for concurrency |

## 10. Risks

| Risk | Mitigation |
|---|---|
| OKF v0.3 changes fields | All OKF I/O in one module + `okf_version` pinned in root index + migration script |
| Model writes plausible but unsupported text | Mandatory footnotes + deterministic quote verification + human approval |
| Large manuals produce many files | Planner caps concepts per source. Sections reused via links instead of duplication |
| Git concurrency (two editors approve at once) | Serialize writes per org repo with a Redis lock |
