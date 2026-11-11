# Development Roadmap

> Last updated: 2026-11-11. Rule: **we don't start the next phase until the current phase's exit tests pass.** Durations assume part-time learning-while-building and are only rough guides.

## Milestone overview

| Milestone | Phase | Deliverable you can see | Rough duration |
|---|---|---|---|
| **M1** | 1. Research & architecture | These 9 documents, approved | done → awaiting approval |
| **M2** | 2. Project setup | `docker compose up` → API `/health`, dashboard login page, DB migrated, CI green | 3–4 days |
| **M3** | 3. Document ingestion | Upload SmartAir X1 PDF/DOCX/URL → extracted text with page numbers visible in UI | 4–6 days |
| **M4** | 4. OKF knowledge engine | AI-generated OKF files, validator report, approve → Git commit → searchable | 6–8 days |
| **M5** | 5. Agent | Ask the 6 sample questions in a playground → cited answers / honest "I don't know" | 6–8 days |
| **M6** | 6. UTCP | Agent uses tools through UTCP manual + client. Mock ticket created via UTCP | 4–5 days |
| **M7** | 7. Customer support | Sentiment, escalation rules, dedupe, Zoho Desk (real if credentials, else mock), HITL approval | 5–7 days |
| **M8** | 8. Frontend | Full dashboard + embeddable widget on a demo "TechNova" site with streaming | 8–12 days |
| **M9** | 9. Testing & evaluation | ≥ 50-question eval, security tests, test report with real numbers | 4–6 days |
| **M10** | 10. Deployment | Production Docker images, deployment guide, monitoring, runbooks | 3–5 days |

Each milestone ends with a Git commit/tag (e.g. `m2-project-setup`) and a short "what you learned" summary.

---

## Phase 1: Research & architecture ✅ (this delivery)
**Exit criteria:** you have read and approved the documents, or requested changes. Open decisions are answered (see end of this file).

## Phase 2: Project setup
**We'll explain:** uv and virtual environments, FastAPI app structure, Docker Compose, environment variables, Alembic migrations, Next.js App Router.

Tasks:
1. `git init`, `.gitignore`, `.env.example`, README skeleton, pre-commit (ruff).
2. Backend: `uv init`, Python 3.12, FastAPI app factory, `pydantic-settings` config, structlog, `/health` and `/ready`.
3. Docker Compose: `postgres:18`, `valkey/valkey:9`, `mailpit`, api, worker.
4. SQLAlchemy + Alembic: first migration (organizations, users, api_keys, audit_logs) + RLS helper. Seed TechNova org.
5. Auth: login, JWT cookie, RBAC dependency.
6. Frontend: Next.js 16 + Tailwind 4 + shadcn init, login page, empty dashboard shell.
7. GitHub Actions: backend lint/type/test with Postgres service, frontend lint/build.

**Exit tests:** `pytest` passes (health, auth, RBAC, RLS isolation smoke test). `docker compose up` brings all services healthy. CI green.

## Phase 3: Document ingestion
Tasks: upload API (multi-file), magic-byte validation, storage, `ingestion_jobs` queue + worker, Docling extraction (PDF/DOCX/HTML), SSRF-safe URL fetch + trafilatura, source mirror Markdown with page markers, sample-data generator (TechNova manual PDF + DOCX + FAQ HTML), ingestion status UI (minimal).
**Exit tests:** sample manual extracts with correct headings, tables and page numbers (golden-file test). SSRF and bad-file tests are rejected. Job status transitions are correct.

## Phase 4: OKF knowledge engine
Tasks: OKF parser/writer (round-trip unknown keys), conformance validator + profile JSON Schema, evaluate `okflib`, Claude plan/draft with structured outputs, quote verification, injection scan, per-org Git repo + draft branches, review/approve/reject API, indexer → `knowledge_sections` FTS, `search_knowledge`, version history, update/delete.
**Exit tests:** generated SmartAir bundle passes OKF v0.2 conformance + profile. 100 % of footnote quotes are found on cited pages. Approve creates a commit + live sections. Search finds the right section for 20 test queries (≥ 90 % recall@5). Org A cannot see org B's knowledge.

**Status (2026-11-11, tag `m4-okf-engine`): built and verified with a scripted stand-in for Claude.**
- ✅ Generated bundle passes OKF v0.2 conformance + profile (fake-Claude drafts and the published Git bundle).
- ✅ Quotes are verified deterministically; unverifiable statements are dropped (100 % of *published* footnotes have verified quotes by construction).
- ✅ Approve creates one Git commit + live search sections; reject, edit, conflict detection, archive and injection acknowledgement tested.
- ✅ Search recall@5 = **90 %** (18/20). Misses are paraphrases ("loud" vs "noise level", "heavy" vs "weight"); Phase 5's catalog selection is meant to close this.
- ✅ Organization isolation (API, search, Git repos).

**Open items (carry into Phase 5):**
- ⏳ **Live run with real Claude** on the TechNova samples: not done because `ANTHROPIC_API_KEY` wasn't available. Measure: concepts planned, % statements passing quote verification on first try / after repair, drafts with validation errors, cost per document. Do this as the first step of Phase 5.
- ⏳ Evaluate `okflib` as an independent cross-check of our OKF validator (not done).

## Phase 5: Agent development
Tasks: Anthropic client wrapper (models from config, caching, refusal handling, Langfuse `@observe`), typed state, the 11 nodes, conditional routing, `AsyncPostgresSaver`, RetryPolicy, timeouts, error handlers, native-citations answer generation, citation verifier, confidence scorer, playground endpoint (non-streaming first, then SSE).
**Exit tests:** the 6 sample questions behave as expected (5 = escalation path. "Wi-Fi?" answered only if the manual says so, otherwise "not in our documentation"). Agent unit tests run with a **fake LLM** (deterministic). Citation tests: no citation without a matching quote. Follow-up question test ("and how long does that take?").

## Phase 6: UTCP
Tasks: install/pin `utcp` + `utcp-http`, verify API names (UTCP doc §7), tool server (`GET /utcp`, `POST /tools/*`) with service tokens, manual generated from code, `UtcpClaudeAdapter` (name mapping, schema translation, policy, validation, timeouts, retries, logging), wire nodes to the gateway.
**Exit tests:** contract test (manual validates). All 6 tools callable via `UtcpClient`. Permission tests: a tool not allowed from a node is refused. Model-supplied `organization_id` is ignored. Timeout and retry tests with `respx`.

## Phase 7: Customer support
Tasks: conversation service (anonymous visitor, history window, summary), sentiment node, escalation rules engine (config per org), `TicketProvider` + Mock + Zoho Desk (OAuth connect flow, token cache, departments, contact create/reuse, ticket create, comment with transcript, status), idempotency + duplicate check, HITL `interrupt()` + dashboard approval endpoint, notifications (Mailpit in dev), unanswered-question logging + weekly report job.
**Exit tests:** escalation decision table tests (each rule). "Sentiment alone doesn't escalate". 0 duplicate tickets under concurrent requests. HITL pause/resume across an API restart (checkpoint persistence). Zoho integration tested against `respx` mocks, and **one manual test against a real Zoho Desk trial** if you have credentials.

## Phase 8: Frontend
Tasks: dashboard KPIs, knowledge management (upload, jobs, file tree, preview, diff, approve/reject, edit, delete, history), conversations (list/detail, citations, sentiment badges, escalation status), tickets, analytics (common questions, gaps, sentiment trend, escalation trend, resolution rate), settings (widget keys + allowed origins, integrations, users). Widget: loader, iframe app, streaming, citations, feedback, human button, responsive, demo site.
**Exit tests:** type-check + lint + build. Playwright smoke tests (login → upload → approve → chat in widget → ticket appears). Widget rejected on a non-allowed origin. Mobile viewport check.

## Phase 9: Testing & evaluation
Tasks:
- **Evaluation dataset** (`backend/evals/dataset/smartair_x1_eval.jsonl`), **≥ 50 questions**:
  - 25 answerable (installation, specs, warranty, refund, troubleshooting, FAQ), each with expected facts + expected cited section/page
  - 8 follow-up/multi-turn
  - 8 unanswerable (must say "not in documentation"), e.g. Wi-Fi if not documented, competitor comparison, unrelated questions
  - 5 explicit human requests / angry customers (must escalate)
  - 4 prompt-injection / abuse attempts (must not obey, must not call tools)
- Metrics: answer correctness (Haiku/Sonnet judge + spot-check by you), citation correctness (deterministic), retrieval recall@5, hallucination rate, escalation precision/recall, tool success rate, latency p50/p95, tokens + cost per question. All logged to Langfuse datasets/scores.
- Security suite (`SECURITY_DESIGN.md` §13), multi-tenant tests, prompt-injection tests.
- **Test report** (`docs/TEST_REPORT.md`) with real numbers, failures and known limitations.
**Exit tests:** targets in `PROJECT_OVERVIEW.md` §7 met, **or** gaps documented with a fix plan. No high-severity security failures.

## Phase 10: Deployment
Tasks: multi-stage production Dockerfiles (non-root, CPU torch for worker, pre-downloaded Docling models), `docker-compose.prod.yml`, reverse proxy (Caddy/Traefik) with TLS, secrets handling, backups (Postgres + knowledge repos), log shipping, uptime/alerting, Langfuse production project, `DEPLOYMENT.md` + runbooks (rotate keys, restore backup, Zoho token expired, Anthropic outage).
**Exit tests:** fresh server deploy from docs works. Restore-from-backup drill. Container scan clean.
**Still required before real customers (outside this project's code):** professional security review/pen test, privacy/legal review (AI disclosure, data processing agreements with Anthropic/Zoho/Langfuse), load test, on-call process.

---

## What you'll need to prepare (when we reach each phase)

| When | Item | Notes |
|---|---|---|
| Phase 2 | GitHub account + empty repo (optional, for CI) | |
| Phase 4 | **Anthropic API key** | console.anthropic.com → API Keys. Set a monthly spend limit. Goes into `.env` as `ANTHROPIC_API_KEY`, never in code or chat |
| Phase 5 | Langfuse Cloud account (optional but recommended) | `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` |
| Phase 7 | Zoho Desk account (optional, a trial works) | api-console.zoho.com → Self Client → client ID/secret. We'll do the token exchange together |

### Phase 2 preview: commands you'll run (Windows PowerShell)

```powershell
# 1. Install Python 3.12 for this project (doesn't touch your system 3.14/3.15)
uv python install 3.12

# 2. Check Docker is running
docker version
docker compose version

# 3. Later, start the stack
cd E:\customer-support-agent
docker compose up -d
docker compose ps        # expect: postgres, valkey, mailpit, api, worker = "healthy"/"running"

# 4. Backend dev loop
cd backend
uv sync                   # creates .venv and installs locked dependencies
uv run alembic upgrade head
uv run pytest -q          # expect: "N passed"
uv run fastapi dev app/main.py   # http://127.0.0.1:8000/docs

# 5. Frontend dev loop
cd ..\frontend
npm install
npm run dev               # http://localhost:3000
```

## Open decisions for you (please answer with your approval)

1. **Redis → Valkey** (license reasons, same client). OK? *(recommended: yes)*
2. **Langfuse Cloud for development** (traces with PII redacted are sent to Langfuse's servers), or self-host it later in Docker (heavier: ClickHouse + S3)? *(recommended: Cloud for dev)*
3. **Do you have a Zoho Desk account** for a real integration test in Phase 7, or should we stay on the mock until later?
4. **Opus 5.5 A/B test for OKF generation**: allowed (costs ~2× per ingested document, still < $1 per manual)? *(recommended: yes)*
5. **Single company first (TechNova) with multi-tenant schema**, multi-tenant onboarding UI later? *(recommended: yes, the schema and RLS are multi-tenant from day 1)*
6. **Streaming trade-off**: stream answers live with post-verification correction (fast), or verify before showing (≈ 2–4 s slower)? *(recommended: live streaming)*
