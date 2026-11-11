# Agentic Customer Support Knowledge Platform

**OKF** (knowledge) · **LangGraph** (orchestration) · **Claude** (intelligence) · **UTCP** (tools) · **FastAPI** · **PostgreSQL** · **Next.js**

> **Status: Phase 4 (OKF knowledge engine) complete.** Next: Phase 5, the AI agent. See the [roadmap](docs/DEVELOPMENT_ROADMAP.md).

## What runs today

| Service | URL | What it is |
|---|---|---|
| Dashboard (Next.js 16) | http://localhost:3000 | Login, dashboard, **Knowledge**: upload documents and web pages, review AI drafts, publish, browse, search |
| API (FastAPI) | http://localhost:8000/docs | Interactive API docs (Swagger) |
| PostgreSQL 18 | `127.0.0.1:5433` | App database (host port 5433 so it never clashes with a local Postgres on 5432) |
| Valkey 9 | `127.0.0.1:6379` | Rate limits, locks (Redis-compatible) |
| Mailpit | http://localhost:8025 | Catches every email the app sends in development |

## Prerequisites (Windows)

- **Docker Desktop**, running (whale icon in the system tray)
- **uv**, the Python manager: `winget install astral-sh.uv` (it downloads Python 3.12 for this project by itself)
- **Node.js 20.9+** (24 LTS recommended)
- **Git**

## First-time setup (PowerShell)

```powershell
cd E:\customer-support-agent

# 1. Create your local config from the template, then edit the secrets in .env
Copy-Item .env.example .env
#    Generate a JWT secret and paste it into JWT_SECRET=:
uv run --no-project python -c "import secrets; print(secrets.token_urlsafe(48))"
#    Also change POSTGRES_OWNER_PASSWORD, POSTGRES_APP_PASSWORD, SEED_ADMIN_PASSWORD.

# 2. Start everything: database, cache, mail catcher, migrations, API, worker
docker compose up -d --build
docker compose ps
```

Expected `docker compose ps` output (the `migrate` service runs once and exits, so it isn't listed):

```
SERVICE    STATUS
api        Up (healthy)
mailpit    Up (healthy)
postgres   Up (healthy)
valkey     Up (healthy)
worker     Up
```

```powershell
# 3. Create the demo organization (TechNova Electronics) and its admin user
docker compose exec api python -m scripts.seed
#   created organization technova (...)
#   created admin user admin@technova.example

# 4. Check the API can reach its dependencies
curl.exe http://127.0.0.1:8000/ready
#   {"status":"ok","checks":{"postgres":"ok","valkey":"ok"}}

# 5. Start the dashboard
cd frontend
npm install
npm run dev
#   open http://localhost:3000 and sign in with SEED_ADMIN_EMAIL / SEED_ADMIN_PASSWORD from .env
```

## AI knowledge generation (Claude)

Uploaded documents are turned into OKF knowledge files by Claude. To enable it:

1. Create a key at https://console.anthropic.com (API Keys). **Set a monthly spend limit** (Billing → Limits).
2. Put it in `.env` (never in code or chat): `ANTHROPIC_API_KEY=sk-ant-...`
3. Restart: `docker compose up -d` (or restart your local worker).

Without a key everything else works; uploads stop at **Text extracted**. Generating the 12-page sample manual costs roughly $0.10–0.50 (the exact cost is shown on the source's page). `KNOWLEDGE_GENERATION_MODEL=claude-opus-5-5` switches drafting to Opus for comparison (about 2× the cost).

Knowledge files are stored as one Git repository per organization (Docker volume `knowledge_repos`). To look at the history:

```powershell
docker compose cp api:/data/knowledge-repos ./knowledge-repos   # copy out (the folder is git-ignored)
git -C (Get-ChildItem .\knowledge-repos -Directory)[0].FullName log --stat
```

## Day-to-day development

### Backend (outside Docker, for fast iteration)

```powershell
cd backend
uv sync                                  # install/update dependencies into backend\.venv
docker compose up -d postgres valkey     # only the infrastructure
uv run alembic upgrade head              # apply migrations
$env:PORT=8001; uv run python -m app.dev # API on :8001 (the Docker api already uses :8000)
```

> **Windows note:** `app.dev` exists because psycopg's async mode can't run on Windows' default event loop. It starts uvicorn on a compatible loop. Inside Docker (Linux) we run plain `uvicorn`.

### Tests and code quality

```powershell
cd backend
docker compose up -d postgres valkey   # tests use the real Postgres (database csp_test) and Valkey (db 15)
uv run pytest -q -m "not slow"         # fast tests (expect: 195 passed; Claude is faked, no API cost)
uv run pytest -q -m slow               # golden tests with the real Docling models (~1 min)
uv run ruff check .                    # lint
uv run ruff format .                   # auto-format
uv run mypy app scripts                # strict type check

cd ..\frontend
npm run lint
npx tsc --noEmit
npm test                               # unit tests (Node built-in runner)
npm run build
```

### Database migrations

```powershell
cd backend
uv run alembic revision --autogenerate -m "add knowledge tables"   # then REVIEW the generated file
uv run alembic upgrade head
uv run alembic downgrade -1
```

### Useful Docker commands

```powershell
docker compose logs -f api worker     # follow logs
docker compose restart api
docker compose down                   # stop (data is kept in the pgdata volume)
docker compose down -v                # stop AND delete the database volume (fresh start)
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `failed to connect to the docker API ... dockerDesktopLinuxEngine` | Docker Desktop isn't running. Start it and wait for the whale icon to settle |
| `ports are not available: ... 5432` | Another PostgreSQL is installed locally. That's why we use host port **5433** (`POSTGRES_HOST_PORT` in `.env`) |
| Tests or API very slow on Windows | Use `127.0.0.1`, not `localhost`, in `.env` (`localhost` tries IPv6 first and waits) |
| `Psycopg cannot use the 'ProactorEventLoop'` | Start the API with `uv run python -m app.dev`, not `fastapi dev` |
| First `docker compose build` takes a long time | The worker image includes PyTorch (CPU) and Docling's models (downloaded at build time). Later builds are cached |
| Upload stays "Queued" | The worker isn't running: `docker compose ps worker`, `docker compose logs worker`. It logs `worker_ready` once models are loaded (~30 s) |
| `To support symlinks on Windows...` warning when running Docling locally | Harmless: Hugging Face copies model files instead of linking them |
| Login returns 429 | 5 failed attempts in 15 minutes for that email from that IP. Wait, or run `docker compose restart valkey` in development. In production, set `FORWARDED_ALLOW_IPS` to your reverse proxy so the API sees real visitor IPs (otherwise all visitors share one IP and an attacker could lock out an account) |
| `/ready` shows `postgres: error` | Run `docker compose ps`. Check that the `migrate` service exited with code 0 (`docker compose logs migrate`) |

## Project layout

```
backend/    FastAPI app (app/), Alembic migrations, tests, Dockerfile (targets: api, worker)
sample-data/technova/  Fictional TechNova SmartAir X1 manual (PDF), policies (DOCX), FAQ page (HTML)
frontend/   Next.js 16 dashboard (App Router, Tailwind 4, shadcn/ui)
docker/     Postgres init script (creates the RLS-restricted app role + test DB)
docs/       Architecture and design documents
.github/    CI: backend tests, frontend build, dependency audits
```

## API endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | none | Liveness |
| GET | `/ready` | none | PostgreSQL + Valkey reachability |
| POST | `/api/v1/auth/login` | none (rate-limited) | Sign in. Sets httpOnly session cookies + CSRF cookie |
| POST | `/api/v1/auth/refresh` | refresh cookie | Rotate tokens atomically. 409 = another tab refreshed in the last 30 s (retry). Reuse of an old token later revokes all sessions |
| POST | `/api/v1/auth/logout` | refresh cookie | Revoke session |
| GET | `/api/v1/auth/me` | session | Current user + permissions |
| GET | `/api/v1/organization` | session | Current organization |
| PATCH | `/api/v1/organization` | `org:manage` + CSRF | Rename organization (audited) |
| GET | `/api/v1/users` | `org:manage` | List users in your organization |
| POST | `/api/v1/knowledge/sources` | `knowledge:edit` + CSRF | Upload up to 20 files (multipart `files`). Per-file result: created / duplicate / rejected |
| POST | `/api/v1/knowledge/sources/url` | `knowledge:edit` + CSRF | Queue a public web page (private/internal addresses refused) |
| GET | `/api/v1/knowledge/sources` | `knowledge:view` | List sources with processing status |
| GET | `/api/v1/knowledge/sources/{id}` | `knowledge:view` | Details, outline (headings + pages), extraction stats |
| GET | `/api/v1/knowledge/sources/{id}/extracted` | `knowledge:view` | Extracted text as Markdown with `<!-- page: N -->` markers |
| POST | `/api/v1/knowledge/sources/{id}/retry` | `knowledge:edit` + CSRF | Re-run a failed extraction |
| DELETE | `/api/v1/knowledge/sources/{id}` | `knowledge:publish` + CSRF | Soft-delete a source |
| POST | `/api/v1/knowledge/sources/{id}/generate` | `knowledge:edit` + CSRF | Run AI knowledge generation again (reuses the extracted text) |
| GET | `/api/v1/knowledge/reviews` | `knowledge:view` | Drafts waiting for review |
| GET | `/api/v1/knowledge/versions/{id}` | `knowledge:view` | A draft or version: content, validation report, diff |
| POST | `/api/v1/knowledge/versions/approve` | `knowledge:publish` + CSRF | Publish drafts in ONE Git commit (`acknowledge_warnings` needed if the source had prompt-injection text) |
| POST | `/api/v1/knowledge/versions/{id}/reject` | `knowledge:publish` + CSRF | Reject a draft |
| GET | `/api/v1/knowledge/documents` | `knowledge:view` | Published and draft documents |
| GET | `/api/v1/knowledge/documents/{id}` | `knowledge:view` | Current content, trust tier, version history |
| PUT | `/api/v1/knowledge/documents/{id}` | `knowledge:edit` + CSRF | Save an edit as a new draft (goes through review) |
| DELETE | `/api/v1/knowledge/documents/{id}` | `knowledge:publish` + CSRF | Remove from published knowledge (Git keeps history) |
| GET | `/api/v1/knowledge/search?q=` | `knowledge:view` | Full-text search over published sections (with cited pages) |
| GET | `/api/v1/knowledge/profile-schema` | `knowledge:view` | JSON Schema of our OKF profile |

Full, live documentation: http://localhost:8000/docs

## Design documents

[Overview](docs/PROJECT_OVERVIEW.md) · [Architecture](docs/SYSTEM_ARCHITECTURE.md) · [Technology selection](docs/TECHNOLOGY_SELECTION.md) · [OKF research](docs/OKF_IMPLEMENTATION_RESEARCH.md) · [UTCP research](docs/UTCP_IMPLEMENTATION_RESEARCH.md) · [Database](docs/DATABASE_DESIGN.md) · [Roadmap](docs/DEVELOPMENT_ROADMAP.md) · [Security](docs/SECURITY_DESIGN.md) · [Cost](docs/COST_ESTIMATION.md)
