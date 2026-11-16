# Project Overview — Agentic Customer Support Knowledge Platform

> Status: **R&D / design phase**. No application code exists yet. This document set must be approved before implementation starts.
> Last updated: 2026-11-11

## 1. The problem

Support teams answer the same questions again and again: "How do I install it?", "What's the warranty?", "Can I return it?". The answers already exist in manuals, policies and FAQs, but customers can't find them and agents waste time copy-pasting.

## 2. What we are building

A multi-tenant SaaS platform where a business:

1. **Uploads its knowledge** — PDF, DOCX, HTML, website URLs, FAQs, manuals, policies.
2. **Gets it converted into structured knowledge files** — Markdown with YAML frontmatter that follows the Open Knowledge Format (OKF), kept in a Git repository, with every fact linked back to the page or section it came from.
3. **Reviews and approves** the generated knowledge before customers see it (a human stays in control).
4. **Embeds a chat widget** on its website with one `<script>` tag.

Customers then chat with an AI agent that:

- understands the question (including follow-ups),
- **navigates** the structured knowledge (index → topic → section), rather than doing a "similarity search" over random text chunks,
- answers with Claude, **citing** the document, page, section and knowledge file,
- says "I'm not sure" when the knowledge does not support an answer,
- detects frustration and explicit requests for a human,
- **escalates** to a Zoho Desk ticket (no duplicates), and
- feeds a weekly "unanswered questions / knowledge gaps" report.

## 3. Core architecture in one line

```
OKF = knowledge layer · LangGraph = orchestration · Claude = intelligence
UTCP = tool layer · FastAPI = backend · PostgreSQL = app database · Next.js = frontend
```

## 4. End-to-end demo flow (definition of "done" for the MVP)

```
Upload SmartAir X1 manual (PDF)
  → Docling extracts text, headings, tables, page numbers
  → Claude drafts OKF knowledge files with provenance
  → Validator checks the files against the OKF rules + our schema
  → Admin approves → Git commit → search index updated
Customer asks "What is the warranty period?"
  → LangGraph agent: validate → classify → discover → retrieve → answer
  → Citation verifier confirms every cited quote really exists in the source
  → Answer streamed to the widget with citations
Customer: "This is useless, I want a human"
  → Sentiment = frustrated, explicit human request → escalate
  → UTCP tool call → Zoho Desk ticket (mock in dev) → ticket ref shown
Dashboard shows the conversation, the ticket, and the gap in analytics
```

## 5. Users

| Role | What they do |
|---|---|
| **Platform owner** (us) | Operates the SaaS, manages organizations |
| **Org admin** | Configures integrations, widget keys, users |
| **Knowledge editor** | Uploads documents, reviews/approves OKF knowledge |
| **Support agent** | Reads conversations and tickets, handles escalations |
| **Viewer** | Read-only dashboards |
| **End customer** | Anonymous or identified visitor using the chat widget |

## 6. Scope

### In scope (MVP)
- PDF, DOCX, HTML, single URL and small-site crawl ingestion
- OKF generation, validation, approval workflow, Git versioning
- PostgreSQL full-text search index over OKF sections (no vector DB)
- Single LangGraph graph with the 11 nodes from the brief
- UTCP manual + client for 6 tools
- Zoho Desk (real + mock), interface ready for Freshdesk
- Admin dashboard (Next.js) and embeddable widget
- Langfuse tracing, ≥50-question evaluation set, test report

### Explicitly out of scope for MVP (possible later)
- Vector database / embeddings (see `OKF_IMPLEMENTATION_RESEARCH.md` §7 for when we'd add it)
- Voice, WhatsApp, email-in channels
- Multi-language answers (design keeps a `language` field so it can be added)
- Billing/subscriptions
- Freshdesk implementation (interface only)

## 7. Success criteria

The numbers are targets for the evaluation set (see `DEVELOPMENT_ROADMAP.md`, Phase 9). They are not guarantees:

| Metric | MVP target |
|---|---|
| Answer correctness (supported questions) | ≥ 90 % |
| Citation correctness (cited quote exists in cited source) | 100 %, enforced by code, not by the model |
| Hallucination rate (claims not supported by knowledge) | ≤ 2 % |
| Correct "I don't know" on unsupported questions | ≥ 90 % |
| Escalation accuracy | ≥ 90 % |
| Duplicate tickets | 0 |
| p50 time-to-first-token in widget | < 2.5 s |
| Cross-tenant data leakage in security tests | 0 |

**A working demo does not make the system production-ready.** Production readiness also needs load testing, a security review, a penetration test, legal/privacy review (customer PII goes to Anthropic and Zoho) and operational runbooks. Those are listed in the roadmap, Phase 10.

## 8. Document map

| Document | Purpose |
|---|---|
| `PROJECT_OVERVIEW.md` | This file — the what and why |
| `SYSTEM_ARCHITECTURE.md` | Components, data flows, the LangGraph graph, folder structure |
| `TECHNOLOGY_SELECTION.md` | Every technology: what, why, alternatives, license, cost, maturity + compatibility matrix |
| `OKF_IMPLEMENTATION_RESEARCH.md` | What OKF actually is, how we comply, how we search it |
| `UTCP_IMPLEMENTATION_RESEARCH.md` | What UTCP actually is, SDK, the Claude↔UTCP adapter |
| `DATABASE_DESIGN.md` | PostgreSQL schema and multi-tenant isolation |
| `SECURITY_DESIGN.md` | Threat model, auth, RBAC, prompt-injection defences |
| `DEVELOPMENT_ROADMAP.md` | Phases, milestones, exit tests |
| `COST_ESTIMATION.md` | LLM, infrastructure and SaaS cost estimates |
