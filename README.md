# Agentic Customer Support Knowledge Platform

**OKF** (knowledge) · **LangGraph** (orchestration) · **Claude** (intelligence) · **UTCP** (tools) · **FastAPI** · **PostgreSQL** · **Next.js**

> **Status: Phase 2 (project setup) complete.** Next: Phase 3, document ingestion. See the [roadmap](docs/DEVELOPMENT_ROADMAP.md).

## What runs today

| Service | URL | What it is |
|---|---|---|
| Dashboard (Next.js 16) | http://localhost:3000 | Login + dashboard shell |
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
uv run pytest -q                       # expect: 36 passed
uv run ruff check .                    # lint
uv run ruff format .                   # auto-format
uv run mypy app scripts                # strict type check

cd ..\frontend
npm run lint
npx tsc --noEmit
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
| Login returns 429 | 5 failed attempts in 15 minutes. Wait, or run `docker compose restart valkey` in development |
| `/ready` shows `postgres: error` | Run `docker compose ps`. Check that the `migrate` service exited with code 0 (`docker compose logs migrate`) |

## Project layout

```
backend/    FastAPI app (app/), Alembic migrations, tests, Dockerfile
frontend/   Next.js 16 dashboard (App Router, Tailwind 4, shadcn/ui)
docker/     Postgres init script (creates the RLS-restricted app role + test DB)
docs/       Architecture and design documents
.github/    CI: backend tests, frontend build, dependency audits
```

## API endpoints (Phase 2)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | none | Liveness |
| GET | `/ready` | none | PostgreSQL + Valkey reachability |
| POST | `/api/v1/auth/login` | none (rate-limited) | Sign in. Sets httpOnly session cookies + CSRF cookie |
| POST | `/api/v1/auth/refresh` | refresh cookie | Rotate tokens (reuse of an old token revokes all sessions) |
| POST | `/api/v1/auth/logout` | refresh cookie | Revoke session |
| GET | `/api/v1/auth/me` | session | Current user + permissions |
| GET | `/api/v1/organization` | session | Current organization |
| PATCH | `/api/v1/organization` | `org:manage` + CSRF | Rename organization (audited) |
| GET | `/api/v1/users` | `org:manage` | List users in your organization |

Full, live documentation: http://localhost:8000/docs

## Design documents

[Overview](docs/PROJECT_OVERVIEW.md) · [Architecture](docs/SYSTEM_ARCHITECTURE.md) · [Technology selection](docs/TECHNOLOGY_SELECTION.md) · [OKF research](docs/OKF_IMPLEMENTATION_RESEARCH.md) · [UTCP research](docs/UTCP_IMPLEMENTATION_RESEARCH.md) · [Database](docs/DATABASE_DESIGN.md) · [Roadmap](docs/DEVELOPMENT_ROADMAP.md) · [Security](docs/SECURITY_DESIGN.md) · [Cost](docs/COST_ESTIMATION.md)
