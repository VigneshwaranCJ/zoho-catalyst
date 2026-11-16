# Cost Estimation

> Last updated: 2026-11-11. **All figures are estimates** for planning. Real numbers come from `agent_executions.cost_usd` and Langfuse once the system runs, and we re-baseline after the Phase 9 evaluation.
> Claude prices are Anthropic first-party list prices per million tokens (MTok) as published in November 2026. Always check https://www.anthropic.com/pricing before budgeting.

## 1. Model prices used

| Model | ID | Input $/MTok | Output $/MTok | Used for |
|---|---|---|---|---|
| Claude Sonnet 5.5 | `claude-sonnet-5-5` | 2.00 | 10.00 | answers, OKF drafting |
| Claude Haiku 5.5 | `claude-haiku-5-5` | 0.10 (prompts ≤ 100K) | 0.50 | intent, sentiment, section selection, clustering |
| Claude Opus 5.5 (optional) | `claude-opus-5-5` | 4.00 | 20.00 | A/B test for OKF generation |

Prompt-cache reads are much cheaper than normal input (Sonnet 5.5: $0.10/MTok). Our stable system prompts and per-org catalog are designed to be cache hits.
Note: Sonnet 5.5 thinks adaptively. Thinking tokens are billed as output. We use `effort: "low"` for chat answers and measure the effect.

## 2. Cost per customer message (one graph run)

| Step | Model | Input tokens | Output tokens | Cost |
|---|---|---|---|---|
| Intent + follow-up rewrite | Haiku 5.5 | ~1,500 | ~120 | $0.00021 |
| Sentiment | Haiku 5.5 | ~1,000 | ~60 | $0.00013 |
| Section selection (catalog + 10 FTS candidates) | Haiku 5.5 | ~4,500 | ~100 | $0.00050 |
| Answer generation (system + 3–5 sections + history) | Sonnet 5.5 | ~6,000 | ~500 (incl. thinking) | $0.01700 |
| Citation verification, confidence, escalation | code | — | — | $0 |
| **Total per message** | | | | **≈ $0.018** |

With prompt caching on the ~1.5K-token system prompt, roughly **$0.015–0.018**. Unsupported questions that skip answer generation cost about **$0.001**.

### Monthly LLM cost by volume (avg 3 messages per conversation, about $0.05 per conversation)

| Conversations / month | LLM cost / month |
|---|---|
| 1,000 | ~$55 |
| 10,000 | ~$550 |
| 50,000 | ~$2,700 |

Levers if this is too high (in order): caching, trimming evidence to the best 3 sections, `effort: "low"`, Haiku for "easy" FAQ-type answers (measure quality first), batch API (50 % off) for non-real-time jobs.

## 3. Knowledge ingestion cost (one-off per document)

Example: a 40-page product manual (~25,000 tokens of text).

| Step | Model | Tokens | Cost |
|---|---|---|---|
| Plan concepts | Sonnet 5.5 | 25K in / 2K out | ~$0.07 |
| Draft ~10 concepts (relevant pages each) | Sonnet 5.5 | 10 × (5K in / 1.5K out) | ~$0.25 |
| Retries on failed quote verification (~30 %) | Sonnet 5.5 | | ~$0.08 |
| **Total** | | | **≈ $0.40 per 40-page manual** (≈ $0.80 with Opus 5.5) |

Docling extraction itself is free (CPU), taking roughly 1–5 s per page on CPU, more with OCR.

## 4. Evaluation & development spend

| Item | Estimate |
|---|---|
| One eval run (50+ questions, Sonnet answers + Haiku judge) | ~$1–2 |
| Developer testing during build (10 weeks) | ~$10–40 per month |
| Ingesting the TechNova sample docs repeatedly while tuning | ~$5 total |

**Recommendation:** set a monthly spend limit in the Anthropic Console (e.g. $50 during development).

## 5. Infrastructure

### Local development: **$0**
Docker Desktop on your PC: postgres, valkey, mailpit, api, worker, web. Langfuse Cloud Hobby (free). Mock ticket provider (no Zoho needed).

### Small production (one company, up to ~10k conversations/month)

| Component | Option | Estimated monthly |
|---|---|---|
| App server (api + worker + web) | 1 VM, 4 vCPU / 8 GB RAM (Docling needs memory) | $40–80 |
| PostgreSQL 18 | managed small tier (or on the VM, with backups) | $15–60 |
| Valkey | on the same VM, or managed small tier | $0–20 |
| Object storage (originals) | S3-compatible | $1–5 |
| Langfuse | Cloud Hobby (free up to 50k units) → paid tier, or self-host | $0–100 |
| Email sending | transactional email provider free/small tier | $0–20 |
| Domain + TLS | Let's Encrypt free. Domain ~$1/mo | ~$1 |
| Backups / monitoring | snapshots, uptime check | $5–15 |
| **Infrastructure total** | | **≈ $60–300 / month** |

### SaaS (multi-tenant, many companies)
Scale is roughly linear in LLM cost (§2), which dominates. Infra grows in steps: separate worker VMs for ingestion, bigger managed Postgres, self-hosted Langfuse (needs ClickHouse + S3), CDN for the widget. Plan pricing so each plan covers at least **3× its expected LLM cost**.

## 6. Third-party subscriptions (the business's own costs)

| Service | Note |
|---|---|
| Zoho Desk | Per-agent subscription by edition (a Free edition exists with 5,000 API credits/day). API calls consume daily credits: create ticket = 1 credit, search = 3. Typical usage is well below limits |
| Freshdesk (later) | Per-agent plans. API rate limits by plan |
| Anthropic | Pay-as-you-go. Rate limits depend on usage tier |
| GitHub | Free for public / small private. Actions minutes allowance |
| Docker Desktop | Free for personal/small business. Paid for larger companies (check current terms) |

## 7. Cost controls built into the design

- Per-org daily token budget (Valkey counter). When exceeded, the widget offers a ticket instead of AI answers.
- Rate limits per widget key / IP / conversation (`SECURITY_DESIGN.md` §9).
- `agent_executions.cost_usd` per run, plus a cost chart on the dashboard.
- Haiku for every step that doesn't need Sonnet.
- Prompt caching with byte-stable system prompts (no timestamps in prompts).
- Max 4,000 characters per customer message, and max evidence tokens per answer.
