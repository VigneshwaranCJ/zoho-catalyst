# Database Design

> PostgreSQL 18, SQLAlchemy 2.1 (async, `postgresql+psycopg` dialect), Alembic migrations.
> One driver, **psycopg 3**, is shared by SQLAlchemy and the LangGraph Postgres checkpointer (which requires psycopg 3), so we don't run two drivers.
> Last updated: 2026-11-11

## 1. Principles (plain language)

1. **Git holds the knowledge text; PostgreSQL holds everything about it.**
   The OKF Markdown files are the source of truth for *content*, versioned in Git. PostgreSQL stores metadata, workflow state (draft/approved), the search index, conversations, tickets and analytics. If the database is lost, the knowledge index can be rebuilt from Git.
2. **Every tenant-owned row has `organization_id`.** This is the "multi-tenant isolation" column. Every query filters by it.
3. **Defence in depth with Row-Level Security (RLS).** PostgreSQL can enforce "you only see rows where `organization_id = current_setting('app.current_org')`" at the database level. A bug in a Python query then can't leak another company's data. The app sets `SET LOCAL app.current_org = '<uuid>'` at the start of each transaction.
4. **UUID primary keys** (`uuid` v7 generated in Python: time-ordered, so it indexes well). They can't be guessed, unlike sequential IDs.
5. **Timestamps everywhere:** `created_at`, `updated_at` (`timestamptz`, UTC). Use soft delete (`deleted_at`) where an audit trail matters.
6. **Enums as `text` + `CHECK` constraints**, not PostgreSQL `ENUM` types. They're easier to change in migrations.
7. **Secrets are never stored in plain text.** `integration_credentials` holds encrypted blobs (envelope encryption, key from environment / KMS).

## 2. Entity-relationship overview

```
organizations ─┬─< users
               ├─< api_keys (widget keys)
               ├─< integration_credentials
               ├─< knowledge_sources ─< knowledge_documents ─< knowledge_versions
               │                                  └─< knowledge_sections (search index)
               ├─< customers ─< conversations ─< messages ─< message_citations
               │                     ├─< agent_executions
               │                     ├─< support_tickets
               │                     └─< feedback
               ├─< unanswered_questions
               ├─< ingestion_jobs
               └─< audit_logs
```

## 3. Tables

Types are abbreviated: `uuid`, `text`, `int`, `bool`, `jsonb`, `ts` = `timestamptz`. **All tables get `created_at ts not null default now()` and `updated_at ts not null default now()`.** They are omitted below for brevity.

### 3.1 Tenancy & identity

**organizations**
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| slug | text UNIQUE | e.g. `technova` |
| name | text | |
| status | text | `active` / `suspended` |
| settings | jsonb | escalation thresholds, branding, language |
| knowledge_repo_path | text | path/URL of this org's Git repo |

**users**
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| organization_id | uuid FK → organizations | |
| email | citext | UNIQUE (organization_id, email) |
| display_name | text | |
| role | text | `org_admin` / `editor` / `agent` / `viewer` |
| password_hash | text NULL | argon2id; NULL if SSO-only |
| last_login_at | ts NULL | |
| is_active | bool | |

**api_keys** (widget public keys + server-to-server keys)
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| organization_id | uuid FK | |
| kind | text | `widget_public` / `server_secret` |
| key_prefix | text | first 8 chars shown in UI |
| key_hash | text | SHA-256 of the key. The full key is shown only once |
| allowed_origins | text[] | for widget keys: `https://technova.example` |
| rate_limit_per_min | int | |
| revoked_at | ts NULL | |

**integration_credentials**
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| organization_id | uuid FK | |
| provider | text | `zoho_desk` / `freshdesk` / `smtp` / `mock` |
| config | jsonb | non-secret: data-center, orgId, departmentId |
| secret_ciphertext | bytea | encrypted refresh token / API key |
| key_version | int | which encryption key was used (for rotation) |
| status | text | `connected` / `expired` / `error` |
| UNIQUE (organization_id, provider) | | |

### 3.2 Knowledge

**knowledge_sources** — one row per uploaded file or URL (the *raw origin*)
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| organization_id | uuid FK | |
| source_type | text | `pdf` / `docx` / `html` / `url` / `markdown` |
| original_name | text | `SmartAir_X1_Manual.pdf` |
| uri | text NULL | URL, for web sources |
| storage_path | text | where the original bytes are kept |
| sha256 | text | detects re-uploads of the same file |
| mime_type | text | detected from bytes, not trusted from the browser |
| size_bytes | bigint | |
| page_count | int NULL | |
| uploaded_by | uuid FK → users | |
| UNIQUE (organization_id, sha256) | | |

**ingestion_jobs** — progress of turning a source into OKF
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| organization_id | uuid FK | |
| source_id | uuid FK → knowledge_sources | |
| status | text | `queued` / `extracting` / `generating` / `validating` / `needs_review` / `failed` / `done` |
| progress | int | 0–100 |
| error | text NULL | |
| extraction_artifact_path | text | Docling JSON (keeps page numbers and bounding boxes) |

**knowledge_documents** — one row per OKF file (e.g. `policies/warranty-policy.md`)
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| organization_id | uuid FK | |
| path | text | repository-relative path. UNIQUE (organization_id, path) |
| title | text | |
| doc_type | text | from frontmatter (`policy`, `faq`, `troubleshooting` …) |
| status | text | `draft` / `in_review` / `approved` / `rejected` / `archived` |
| current_version_id | uuid FK → knowledge_versions NULL | the approved version customers see |
| tags | text[] | |
| deleted_at | ts NULL | soft delete |

**knowledge_versions** — immutable history, one per Git commit that touched the file
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| organization_id | uuid FK | |
| document_id | uuid FK → knowledge_documents | |
| version_no | int | UNIQUE (document_id, version_no) |
| git_commit_sha | text | |
| content_sha256 | text | |
| frontmatter | jsonb | parsed YAML |
| validation_report | jsonb | errors and warnings from the OKF validator |
| created_by | uuid FK → users NULL | NULL = generated by AI |
| review_status | text | `pending` / `approved` / `rejected` |
| reviewed_by | uuid NULL, reviewed_at ts NULL, review_note text NULL | |

**knowledge_document_sources** — many-to-many provenance: which sources and pages a document came from
| column | type | notes |
|---|---|---|
| document_id | uuid FK | |
| source_id | uuid FK | |
| pages | int[] | |
| PK (document_id, source_id) | | |

**knowledge_sections** — the **search index**. One row per heading section of an approved version.
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| organization_id | uuid FK | |
| document_id | uuid FK | |
| version_id | uuid FK | |
| anchor | text | `#warranty-period` |
| heading_path | text[] | `{Warranty Policy, Coverage, Warranty period}` |
| body | text | section Markdown |
| source_id | uuid FK NULL | provenance |
| source_pages | int[] | e.g. `{12,13}` |
| search_vector | tsvector | GENERATED from heading (weight A) + body (weight B) |
| is_live | bool | true only for the current approved version |

Indexes: `GIN (search_vector)`, `GIN (body gin_trgm_ops)` for fuzzy matches and typos, `(organization_id, is_live)`.

**knowledge_links** — relationships between OKF documents (from Markdown links / frontmatter `related`)
| from_document_id | to_document_id | link_type (`related`/`parent`/`supersedes`) |

### 3.3 Conversations

**customers**
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| organization_id | uuid FK | |
| external_id | text NULL | the business's own customer ID if the widget passes a signed identity |
| email | citext NULL | |
| name | text NULL | |
| anonymous_token_hash | text NULL | for anonymous visitors (cookie) |
| metadata | jsonb | |
| UNIQUE (organization_id, email) WHERE email IS NOT NULL | | |

**conversations**
| column | type | notes |
|---|---|---|
| id | uuid PK | also used as the LangGraph `thread_id` |
| organization_id | uuid FK | |
| customer_id | uuid FK NULL | |
| channel | text | `widget` / `api` / `dashboard_test` |
| status | text | `open` / `resolved` / `escalated` / `abandoned` |
| last_sentiment | text NULL | `positive`/`neutral`/`negative`/`frustrated`/`angry` |
| escalation_reason | text NULL | |
| started_at, last_message_at, closed_at | ts | |
| message_count | int | |
| origin | text | website origin the widget ran on |

Index: `(organization_id, last_message_at DESC)`, `(organization_id, status)`.

**messages**
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| organization_id | uuid FK | |
| conversation_id | uuid FK | |
| role | text | `customer` / `assistant` / `human_agent` / `system` |
| content | text | |
| intent | text NULL | from the classifier |
| sentiment | text NULL | |
| confidence | numeric(4,3) NULL | answer confidence 0–1 |
| answer_status | text NULL | `answered` / `partial` / `unsupported` / `escalated` |
| latency_ms | int NULL | |
| input_tokens, output_tokens, cache_read_tokens | int NULL | |
| langfuse_trace_id | text NULL | |

**message_citations**
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| message_id | uuid FK | |
| section_id | uuid FK → knowledge_sections | |
| version_id | uuid FK | pins the exact version that was cited |
| quote | text | exact supporting text, checked by the citation verifier |
| source_name | text | `SmartAir_X1_Manual.pdf` |
| page | int NULL | |
| verified | bool | |

**agent_executions** — one row per graph run (per customer message)
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| organization_id | uuid FK | |
| conversation_id | uuid FK | |
| message_id | uuid FK NULL | |
| status | text | `running`/`succeeded`/`failed`/`interrupted`/`timed_out` |
| node_path | text[] | nodes visited, in order |
| tool_calls | jsonb | UTCP calls: name, args (redacted), duration, ok/error |
| error | text NULL | |
| models_used | text[] | |
| total_tokens | int | |
| cost_usd | numeric(10,6) | |
| duration_ms | int | |
| langfuse_trace_id | text | |

**support_tickets**
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| organization_id | uuid FK | |
| conversation_id | uuid FK | |
| customer_id | uuid FK NULL | |
| provider | text | `zoho_desk` / `mock` / `freshdesk` |
| external_ticket_id | text NULL | Zoho ticket id |
| external_ticket_number | text NULL | human-readable number |
| external_url | text NULL | |
| subject | text, description | text | |
| priority | text | `low`/`medium`/`high`/`urgent` |
| status | text | mirrored from provider |
| idempotency_key | text | **UNIQUE (organization_id, idempotency_key)**: prevents duplicate tickets |
| approval_status | text | `not_required` / `pending` / `approved` / `rejected` (human-in-the-loop) |
| last_synced_at | ts NULL | |

Duplicate prevention: `idempotency_key = sha256(organization_id + conversation_id + "escalation")`. There is at most one open escalation ticket per conversation. A second escalation in the same conversation adds a comment to the existing ticket instead of creating a new one.

**feedback**
| id | organization_id | conversation_id | message_id | rating (`up`/`down`) | comment | customer_id |

**unanswered_questions**
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| organization_id | uuid FK | |
| message_id | uuid FK | |
| question | text | |
| normalized_question | text | lower-cased, PII-redacted, used for grouping |
| reason | text | `no_evidence` / `low_confidence` / `negative_feedback` / `escalated` |
| cluster_label | text NULL | assigned weekly by Claude Haiku |
| week_start | date | for the weekly report |
| resolved_by_document_id | uuid NULL | closes the gap once new knowledge is added |

### 3.4 Operations

**audit_logs** (append-only. The app's DB role has no UPDATE/DELETE on it)
| id | organization_id NULL | actor_type (`user`/`system`/`agent`/`api_key`) | actor_id | action (`knowledge.approve`, `ticket.create`…) | target_type | target_id | ip | user_agent | details jsonb | created_at |

**LangGraph checkpoint tables** are created and owned by `langgraph-checkpoint-postgres` (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`). We keep them in a separate schema, `langgraph`, so our Alembic migrations never touch them.

## 4. Multi-tenant isolation (how it actually works)

1. Each request is authenticated: an admin JWT, or a widget key plus origin check. Either way, it resolves to exactly one `organization_id`.
2. A FastAPI dependency opens a DB session and runs `SET LOCAL app.current_org = :org_id`.
3. Every tenant table has:
   ```sql
   ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
   CREATE POLICY tenant_isolation ON messages
     USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid)
     WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid);
   ```
   If no org is set, the expression is NULL and **no rows match** (safe default).
4. The application connects as a **non-owner role** (`csp_app`), so RLS always applies to it. Migrations, seeding and a few narrowly-scoped `SECURITY DEFINER` functions run as the owner role (`csp_owner`) and are deliberately exempt. We do **not** use `FORCE ROW LEVEL SECURITY`, because that would also block those owner-only functions. Example: `auth_find_login_candidates(email)` exists because at login time the tenant isn't known yet.
5. Repository classes in Python *also* filter by `organization_id`. RLS is the safety net, not the only lock.
6. Tests (Phase 9) create two orgs and assert that org A cannot read, search, or cite org B's data through any API or agent tool.

Knowledge files are isolated too: **one Git repository per organization** (`knowledge-repos/<org_id>/`), and every file-system path is resolved and checked to stay inside that repo (no `../` escapes).

## 5. Retention & privacy

| Data | Default retention | Note |
|---|---|---|
| Messages / conversations | 365 days (configurable per org) | nightly purge job |
| Customer PII | until deletion request | "right to erasure" endpoint anonymizes customer + messages |
| Audit logs | 2 years | |
| Agent executions | 90 days | Langfuse has its own retention |
| Uploaded originals | until source deleted | |

## 6. Migrations

- Alembic with autogenerate. Every migration is reviewed by hand, because RLS policies and generated columns aren't auto-detected.
- RLS policies live in migrations as raw SQL.
- Seed script creates the `TechNova Electronics` demo org, an admin user and a widget key. The demo credentials go in `.env.example` comments and the seed file, never in docs.
