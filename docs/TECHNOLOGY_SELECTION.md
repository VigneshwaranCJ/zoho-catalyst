# Technology Selection & Compatibility Matrix

> Last updated: 2026-11-11. Versions verified from PyPI/npm/official docs on this date. Exact pins are set in Phase 2 with `uv add` / `npm install` and recorded in lock files.
> Legend for maturity: **GA** = stable/production · **Beta** = usable, expect changes · **Experimental** = early, isolate behind our own interfaces.

## 1. Summary table

| Layer | Choice | Version (2026-11) | License | Maturity |
|---|---|---|---|---|
| Language | Python | **3.12** | PSF | GA |
| API framework | FastAPI | 0.162.x | MIT | GA in practice (PyPI says Beta, still 0.x) |
| Validation | Pydantic | 2.14.x | MIT | GA |
| ORM / migrations | SQLAlchemy 2.1.x / Alembic 1.20.x | | MIT | GA |
| DB driver | psycopg 3.3.x (one driver for ORM + LangGraph) | | LGPL-3.0 (fine for use as a library) | GA |
| Database | PostgreSQL **18** | 18.6 | PostgreSQL (permissive) | GA |
| Cache / limits / locks | **Valkey 9.1** (Redis-compatible) via `redis-py` client | | BSD-3 | GA |
| Agent orchestration | LangGraph | 1.2.x | MIT | GA |
| Checkpointer | langgraph-checkpoint-postgres | 3.2.x | MIT | GA |
| LLM SDK | `anthropic` (official Python SDK) | latest | MIT | GA |
| Main model | **Claude Sonnet 5.5** `claude-sonnet-5-5` | | commercial API | GA |
| Light model | **Claude Haiku 5.5** `claude-haiku-5-5` | | commercial API | GA |
| Knowledge format | **OKF v0.2** (Google Cloud) | 0.2 | Apache-2.0 | **Experimental** |
| Tool protocol | **UTCP** `utcp` + `utcp-http` | 1.2.0 / 1.1.15 | MPL-2.0 | **Beta** |
| Document extraction | Docling | 2.150.x | MIT | GA (heavy) |
| HTML main-content | trafilatura | 2.3.x | Apache-2.0 | GA |
| Secondary converter | MarkItDown, **not used by default** | 0.1.9 | MIT | Beta |
| Observability | Langfuse Python SDK v5 (OpenTelemetry) | 5.2.x | MIT (server core MIT, `ee/` commercial) | GA |
| Logging | structlog | | MIT/Apache | GA |
| Frontend | Next.js 16 + React 19 + TypeScript | 16.4 / 19.3 | MIT | GA |
| Styling / UI | Tailwind CSS 4.3 + shadcn/ui | | MIT | GA |
| Widget build | Vite + TypeScript (Preact or vanilla) | | MIT | GA |
| Helpdesk | Zoho Desk REST API v1 (+ Mock, Freshdesk later) | v1 | commercial SaaS | GA |
| Tests | pytest, pytest-asyncio, httpx, respx, testcontainers | | MIT/Apache | GA |
| Packaging | **uv** (Python), npm (JS) | uv 0.13 | MIT/Apache | GA |
| Containers / CI | Docker, Docker Compose, GitHub Actions | | Apache / commercial SaaS | GA |

## 2. Compatibility matrix and resolved conflicts

| # | Concern | Finding | Decision |
|---|---|---|---|
| 1 | **Python version** | Your PC has Python 3.14/3.15, not 3.12. LangGraph declares 3.10–3.13. Langfuse SDK and SQLAlchemy 2.1 need ≥ 3.11. Docling supports 3.10–3.14 | Use **3.12** inside the project. `uv` downloads it automatically (`uv python install 3.12`). Your system Python stays untouched |
| 2 | LangChain dependency | LangGraph depends on `langchain-core` (not full LangChain). Langfuse v5 also needs `langchain-core ≥ 1` | Accept `langchain-core`. **Don't** add `langchain-anthropic`. Nodes call the official `anthropic` SDK directly (full access to citations, structured outputs, caching, effort) |
| 3 | Tracing direct SDK calls | Langfuse LangChain `CallbackHandler` traces graph nodes but not raw SDK calls | Wrap Anthropic calls with Langfuse `@observe(as_type="generation")` + usage details |
| 4 | Two Postgres drivers | LangGraph checkpointer requires psycopg 3. SQLAlchemy can use asyncpg or psycopg | **psycopg 3 only** (`postgresql+psycopg`) |
| 5 | **Redis license** | Redis ≥ 8 is RSALv2/SSPLv1/AGPLv3 (triple-licensed). Valkey is the BSD fork, protocol-compatible | **Valkey 9** container. Same `redis-py` client, same commands. The brief said Redis: this is the smallest change, and switching back is a one-line image change |
| 6 | LangGraph node timeouts | Only for **async** nodes (sync nodes with `timeout=` fail at compile) | All nodes `async def` |
| 7 | **Claude Sonnet 5.5 API rules** | Forced `tool_choice` (`any`/`tool`) → 400. `thinking: {type: "disabled"}` → 400 (use `{type: "between_tools"}` or lower `effort`). Non-default `temperature`/`top_p` → 400. Assistant prefill not supported. Native **Citations are incompatible with structured outputs** (`output_config.format`) | Code-driven tool calls in deterministic nodes. Classification uses structured outputs. **Answer generation uses native Citations** (no structured output). No temperature params |
| 8 | Refusals | Sonnet 5.5 can return `stop_reason: "refusal"` (HTTP 200) | Always check `stop_reason`. Enable server-side fallbacks (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`). Refusal → polite fallback + human offer |
| 9 | Docling weight | `docling` pulls torch, torchvision and HF models (layout/table models downloaded on first run). Works on Windows x86-64 | Run Docling in the **worker container** with **CPU-only torch** wheels. Pre-download models at image build (`artifacts_path`). Larger image (several GB), slow first build |
| 10 | MarkItDown | Beta. No page numbers for PDFs. README warns against untrusted input | Not used by default (page-level citations are required). Possible later fallback for PPTX/XLSX |
| 11 | URL fetching | Docling/trafilatura can fetch URLs themselves, which is an SSRF risk | Our hardened `httpx` fetcher downloads the bytes. Converters only receive bytes |
| 12 | UTCP ↔ LangChain adapter | `langchain-utcp-adapters` 0.1.0 is stale vs `utcp` 1.2 | Own adapter (`UTCP_IMPLEMENTATION_RESEARCH.md` §3) |
| 13 | UTCP OAuth vs Zoho | UTCP `oauth2` = client-credentials only. Zoho uses auth-code + refresh token | Zoho behind our tool server. UTCP uses `api_key` to our server |
| 14 | Langfuse SDK v5 ↔ server | SDK v5 requires Langfuse server ≥ 4.59 if self-hosted | Dev: **Langfuse Cloud Hobby** (free). Self-host later with matching versions |
| 15 | Next.js / shadcn / Tailwind 4 | shadcn supports Tailwind v4 + React 19 (`tw-animate-css` replaces `tailwindcss-animate`) | Use the current `shadcn` CLI init for Tailwind v4 |
| 16 | Node.js | Next 16 needs Node ≥ 20.9. Your PC has Node 24 | OK. Docker images use Node 24 LTS |
| 17 | PostgreSQL | PG 14 is EOL 2026-11-12. PG 18 is current | `postgres:18` image |

## 3. Technology details

Each entry: **What · Why · Alternatives · Advantages · Limitations · License · Compatibility · Cost.**

### 3.1 FastAPI (backend web framework)
- **What:** Python web framework built on Starlette + Pydantic. Automatic OpenAPI docs at `/docs`.
- **Why:** async (needed for streaming LLM output and many concurrent chats), type-hint driven, auto-generated API documentation (meets "Document API endpoints").
- **Alternatives:** Django + DRF (batteries included, heavier, async weaker), Litestar (similar, smaller community), Flask (sync-first).
- **Advantages:** fast, great docs, SSE via `StreamingResponse`, dependency injection for auth/tenant scope.
- **Limitations:** still 0.x (minor versions can change behaviour; pin it). No built-in admin, auth or background jobs.
- **License:** MIT. **Cost:** free.

### 3.2 Pydantic v2
- **What:** data validation using Python type hints. **Why:** validates every API input, tool input/output, LLM structured output and graph state. **Alternatives:** attrs + cattrs, msgspec. **Limitations:** v1→v2 differences in old tutorials. **License:** MIT.

### 3.3 SQLAlchemy 2.1 + Alembic + psycopg 3
- **What:** ORM (Python classes ↔ tables), migration tool, PostgreSQL driver.
- **Why:** mature, async support, explicit SQL when needed (FTS queries, RLS).
- **Alternatives:** SQLModel (thin layer over SQLAlchemy, less control), Tortoise ORM, raw SQL with psycopg.
- **Limitations:** learning curve. Autogenerate misses RLS/generated columns (we write those by hand).
- **License:** MIT / MIT / LGPL-3.0 (psycopg: using it as an unmodified library is fine for closed-source apps).

### 3.4 PostgreSQL 18
- **What:** relational database. **Why:** one database for app data, **full-text search** (tsvector + GIN), **trigram** fuzzy matching (`pg_trgm`), **Row-Level Security** for multi-tenancy, LangGraph checkpoints, and `pgvector` later if ever needed. That's fewer moving parts than a separate search engine or vector DB.
- **Alternatives:** MySQL (weaker FTS/RLS), Elasticsearch/OpenSearch for search (powerful, extra cluster to run), SQLite (not multi-user).
- **Limitations:** FTS is lexical (no meaning). We handle that with the catalog + Claude selection step (`OKF_IMPLEMENTATION_RESEARCH.md` §6).
- **License:** PostgreSQL License (permissive). **Cost:** free self-hosted. Managed ~$15–60/month small tier (see COST_ESTIMATION).

### 3.5 Valkey (instead of Redis)
- **What:** in-memory key-value store. **Why:** rate limiting, per-org token budgets, distributed locks (Git write serialization), short-lived caches.
- **Alternatives:** Redis 8 (license choice RSAL/SSPL/AGPL), KeyDB, Dragonfly (BSL), Memcached (no Lua/locks).
- **Limitations:** another service to run. Data is volatile, so never the system of record.
- **License:** BSD-3. **Cost:** free. Managed small tier ~$15–30/month.

### 3.6 LangGraph 1.2
- **What:** library to build LLM workflows as **graphs of nodes with typed state**, with checkpoints, retries, timeouts, human-in-the-loop.
- **Why:** our flow is a *workflow with branches* (validate → classify → search → answer → verify → escalate), not a free-roaming agent. LangGraph gives explicit control, persistence (`AsyncPostgresSaver`), `interrupt()` for approvals, `RetryPolicy`, node `timeout=`.
- **Alternatives:** hand-written async pipeline (simplest, but we'd rebuild checkpointing/HITL), Anthropic Tool Runner (good for open-ended tool loops, less control over fixed steps), Claude Managed Agents (Anthropic hosts the loop. Overkill for a deterministic support flow and moves state off our infra), Temporal (durable workflows, heavy), CrewAI/AutoGen (multi-agent focus, which the brief explicitly doesn't want).
- **Advantages:** GA (1.x), MIT, strong docs, Langfuse integration.
- **Limitations:** depends on `langchain-core`. Interrupt semantics need care (node restarts on resume). Abstractions can feel heavy for beginners. We keep one graph.
- **License:** MIT. **Cost:** free (LangSmith / LangGraph Platform are optional paid products we don't use).

### 3.7 Claude via the official `anthropic` SDK
- **What:** Anthropic's LLM API.
- **Why Sonnet 5.5** for answer generation and OKF drafting: strong instruction following, long context (1M), **native Citations** (returns exact spans from documents we supply, the strongest anti-fabrication feature available), structured outputs, prompt caching. $2 / $10 per million input/output tokens.
- **Why Haiku 5.5** for intent, sentiment, section selection, follow-up rewriting, weekly clustering: very cheap ($0.10 / $0.50 per MTok for prompts ≤ 100K tokens) and fast.
- **Higher-quality option:** Claude **Opus 5.5** (`claude-opus-5-5`, $4 / $20) is Anthropic's current default flagship. Worth A/B testing for **OKF generation** (one-off per document, quality-sensitive) in Phase 4. The model is configurable per task in settings.
- **Alternatives:** OpenAI / Gemini / open models via other SDKs. The brief specifies Claude.
- **Limitations:** see compatibility rows 7–8 (no forced tool choice, no temperature, citations ≠ structured output, refusal stop reason). Rate limits per Anthropic tier. Data leaves your infra (review Anthropic's commercial terms/retention, disclose AI use to customers).
- **License:** SDK MIT. API commercial pay-as-you-go.

### 3.8 OKF v0.2 (knowledge format)
Details in `OKF_IMPLEMENTATION_RESEARCH.md`. **Experimental** (pre-1.0, no official validator). We use it with our own stricter profile and own validator, isolated in one module. **License:** Apache-2.0. **Cost:** free.

### 3.9 UTCP (tool protocol)
Details in `UTCP_IMPLEMENTATION_RESEARCH.md`. **Beta**, small ecosystem, MPL-2.0. We use only core + HTTP plugin, behind our own `ToolGateway`.

### 3.10 Docling (document extraction)
- **What:** IBM-originated open-source converter for PDF/DOCX/PPTX/XLSX/HTML/images → structured `DoclingDocument` → Markdown/JSON.
- **Why:** keeps **page numbers and bounding boxes** (`prov.page_no`, `bbox`), heading hierarchy and **tables** (TableFormer). That's essential for page-level citations.
- **Alternatives:** MarkItDown (lighter, no page numbers), PyMuPDF (fast PDF text with pages, AGPL!), pdfplumber (MIT, PDF only), Unstructured (Apache, heavier), cloud OCR APIs (Azure Document Intelligence, AWS Textract, paid).
- **Limitations:** heavy install (torch, models), slower first run, scanned PDFs need OCR (included via RapidOCR, but slower).
- **License:** MIT. **Cost:** CPU time only. Ingestion is a background job.

### 3.11 trafilatura (web page cleaning)
- **What:** extracts the main text from HTML (drops nav/ads/footers). **Why:** cleaner input for website URLs before Docling/LLM. **Alternatives:** readability-lxml (Apache), BeautifulSoup custom rules. **License:** Apache-2.0 (since v1.8).

### 3.12 Langfuse (LLM observability)
- **What:** open-source tracing/evaluation platform for LLM apps. **Why:** per-node traces, token and cost tracking, prompt/version tracking, datasets and scores for our ≥ 50-question evaluation.
- **Alternatives:** LangSmith (commercial, LangChain-native), Arize Phoenix (open source), OpenTelemetry + Grafana (generic, no LLM UI), Helicone.
- **Limitations:** self-hosting needs PostgreSQL + **ClickHouse** + Redis/Valkey + S3-compatible storage. That's heavy for a laptop, so **use Langfuse Cloud for dev** (Hobby: free, 50k units/month, 30-day retention, 2 users). Sending traces to a third party requires PII redaction (we do it) and your approval.
- **License:** MIT core, `ee/` commercial. **Cost:** free (Hobby / self-host). Paid cloud tiers when volume grows.

### 3.13 Next.js 16 + React 19 + TypeScript + Tailwind 4 + shadcn/ui
- **What:** React framework (routing, server rendering), UI library, typed JS, utility CSS, copy-in accessible components (Radix-based).
- **Why:** professional SaaS dashboard quickly. shadcn components are copied into our repo (no lock-in). Charts via shadcn/Recharts.
- **Alternatives:** Vite + React SPA (simpler, no SSR), Remix/React Router 7, Vue/Nuxt, Refine/React-Admin (admin-panel frameworks).
- **Limitations:** Next.js App Router concepts (server vs client components) take time to learn. Major versions move fast.
- **License:** MIT. **Cost:** free. Hosting any Node host / Vercel.

### 3.14 Widget: Vite + TypeScript, iframe architecture
- **Why iframe:** isolates our CSS/JS and tokens from the customer's page (security + no style clashes). **Alternatives:** Shadow-DOM web component (lighter, but shares the page's JS context, so a weaker security boundary). **License:** MIT.

### 3.15 Zoho Desk API (helpdesk)
- **API:** REST v1, base `https://desk.zoho.<dc>/api/v1`. **Use the `api_domain` returned by the token response.** Data centres include `.com`, `.eu`, `.in`, `.com.au`, `.jp`, `.sa`, `.com.cn`, `.sg`, `.ae`, and Canada `desk.zohocloud.ca`.
- **Auth:** OAuth 2.0. Header `Authorization: Zoho-oauthtoken <token>`, `orgId` header (we always send it). Access token lifetime **1 hour**. Token request limits (≈10 access-token requests per 10 minutes, 10 active access tokens per refresh token, 20 refresh tokens per client per user), so **cache the access token** and refresh only near expiry, with a Valkey lock.
- **Client type:** *Self Client* for single-company dev/testing (no redirect URL). *Server-based client* (`access_type=offline`) for the multi-tenant "Connect Zoho Desk" button.
- **Scopes:** `Desk.tickets.READ, Desk.tickets.CREATE, Desk.tickets.UPDATE, Desk.contacts.READ, Desk.contacts.CREATE, Desk.basic.READ, Desk.search.READ`.
- **Endpoints used:** `POST /tickets` (required `subject`, `departmentId`, plus a contact: `contactId` or `contact` object with `email`/`lastName`). `GET /tickets/{id}`. `GET /tickets/search` (duplicate check via custom field `cf_ai_conversation_id`). `POST /tickets/{id}/comments` (attach AI transcript, `isPublic: false`). `GET /departments`. `GET /organizations`. **Not** `sendReply` (it emails the customer).
- **Limits:** daily API credits by edition (Free 5,000. Standard 50,000 + 250/agent. Enterprise 100,000 + 1,000/agent). Concurrency 5–25 per org. 429 with `Retry-After`.
- **Webhooks (later):** `Ticket_Update` events for status sync (scope naming `Desk.webhooks.*` vs `Desk.events.*` conflicts across Zoho docs, so verify then).
- **Mock provider:** same `TicketProvider` interface, stores tickets in DB, returns fake `ZD-MOCK-000123` numbers and a local URL. Default when no credentials are configured.
- **Freshdesk (later):** `https://<domain>.freshdesk.com/api/v2/tickets`, Basic auth with API key. Requester via `email`/`requester_id`/…, `status`/`priority`/`source`.
- **License/cost:** Zoho Desk subscription (Free edition exists with low API credits). API use counts against credits.

### 3.16 Background jobs: PostgreSQL job table (no extra queue technology)
- **What:** the worker process claims jobs from `ingestion_jobs` (and a generic `jobs` table) with `SELECT … FOR UPDATE SKIP LOCKED`. A tiny scheduler loop runs periodic jobs (ticket sync every 10 min, weekly report).
- **Why:** durable and transactional with our data, with **zero new dependencies** (coding standard 5: "avoid unnecessary dependencies"). Our job volume is low.
- **Alternatives:** Celery (BSD, mature, heavier, awkward with asyncio), ARQ, Dramatiq (LGPL), Temporal. **Revisit if** we need >~20 jobs/second or complex workflows.

### 3.17 Auth libraries
`pyjwt` (MIT) for JWTs, `pwdlib[argon2]` / `argon2-cffi` (MIT) for password hashing, `cryptography` (Apache/BSD) for AES-GCM secret encryption. **Alternative:** a hosted identity provider (Clerk, Auth0, Keycloak self-hosted) once SSO is needed.

### 3.18 Testing & quality tools
`pytest`, `pytest-asyncio`, `httpx` (ASGI test client), `respx` (mock HTTP: Zoho, UTCP), `testcontainers` (real PostgreSQL in tests), `ruff` (lint + format), `mypy` (types), `vitest` + Playwright (frontend/widget). **License:** all permissive.

### 3.19 Docker, Docker Compose, GitHub Actions, uv
- Docker Compose runs the whole stack locally with one command. GitHub Actions runs lint/tests/builds on each push.
- **uv** replaces pip/venv/pyenv: installs Python 3.12, creates `.venv`, locks dependencies (`uv.lock`), and is very fast.
- **Cost:** Docker Desktop is free for personal/small business (paid licence required for companies with >250 employees **or** >$10M revenue; verify current Docker terms). GitHub Actions free minutes for public repos and a monthly allowance for private.

## 4. Experimental / beta / not-production-ready list

| Item | Status | How we contain the risk |
|---|---|---|
| OKF v0.2 | Experimental (pre-1.0, ~5 months old, no validator) | Single OKF module, pinned `okf_version`, own validator, migration path |
| UTCP 1.2 | Beta (PyPI), small ecosystem | Core + HTTP plugin only, own adapter, contract tests, HTTP fallback |
| `langchain-utcp-adapters` | Experimental, stale | **Not used** |
| MarkItDown | Beta | **Not used by default** |
| FastAPI | 0.x, but production-proven | Pin minor version |
| `okflib` (third-party OKF lib) | Unknown quality | Evaluate as cross-check only |
| Server-side refusal fallbacks (Anthropic) | Beta header | Optional. Our code handles `refusal` regardless |

## 5. Final architecture recommendation

Build the **modular monolith** described in `SYSTEM_ARCHITECTURE.md` with:

- **OKF v0.2 + our `csp-okf-profile/1`** in **Git (one repo per org)** as the knowledge source of truth.
- **PostgreSQL 18** for everything else: app data, RLS multi-tenancy, FTS + trigram search index, LangGraph checkpoints, job queue. **No vector DB** until the evaluation triggers in OKF §7 are hit, and then `pgvector` in the same database.
- **LangGraph 1.2**: one 11-node graph, async nodes, Postgres checkpointer, rules-based escalation, `interrupt()` for sensitive tickets.
- **Claude Sonnet 5.5** for answers (native Citations + deterministic verification) and OKF drafting. **Haiku 5.5** for classification/sentiment/selection. Opus 5.5 A/B-tested for OKF generation.
- **UTCP** as the tool layer through our own FastAPI tool server + `UtcpClient` + a custom Claude adapter with policy, validation, timeouts, retries and logs.
- **Zoho Desk** behind a `TicketProvider` interface, with **Mock** as default in dev.
- **Valkey** instead of Redis (license), **psycopg 3** as the only driver, **Langfuse Cloud** for dev tracing.
- **Next.js 16 / shadcn** dashboard + **iframe-isolated** Vite widget with SSE streaming.

This keeps the infrastructure small (five runtime services: api, worker, web, postgres, valkey), uses mature components for everything critical, and isolates the two young standards (OKF, UTCP) behind interfaces we control.
