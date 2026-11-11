# UTCP Implementation Research

> Last updated: 2026-11-11. Sources: utcp.io docs (v1.1 docs set), `github.com/universal-tool-calling-protocol/python-utcp` README, PyPI metadata, utcp.io API reference for `UtcpClient`.

## 1. What UTCP is (plain language)

**Universal Tool Calling Protocol (UTCP)** is a way to describe tools so an AI client can call them **directly over their native protocol** (HTTP, CLI, SSE …). The alternative, MCP, routes calls through a dedicated MCP server.

- A tool provider publishes a **UTCP Manual**: a JSON document listing tools, their input/output JSON Schemas, and a **call template** that tells the client *how* to call each tool (e.g. "HTTP POST to this URL, put the API key in this header").
- The **UTCP client** reads manuals, keeps a tool registry, searches tools, substitutes secrets, and makes the call itself.
- No wrapper server is required. An existing REST API plus a manual is enough.

| Fact | Value |
|---|---|
| Spec / docs version | **1.1** (1.0 and 0.1 archived) |
| Core Python package | `utcp` **1.2.0** (2026-09-16). PyPI status **"4 - Beta"**. Python ≥ 3.10 |
| HTTP plugin | `utcp-http` **1.1.15** (2026-10-25): call templates `http`, `sse`, `streamable_http` |
| Other plugins | `utcp-cli` 1.1.5, `utcp-text` 1.1.0, `utcp-mcp` 1.2.0 (Python ≥ 3.11) |
| License | **MPL-2.0** (core). File-level copyleft: we can use it in closed code, and only modifications *to UTCP files themselves* must be shared |
| Governance | RFC process on utcp.io. Copyright "UTCP Contributors". No foundation |
| Releases | PyPI only (GitHub Releases page empty). No published 1.1→1.2 changelog |

**Classification: beta / young ecosystem.** It's usable, but we must pin versions and wrap it behind our own interface.

## 2. Core concepts with exact names

### 2.1 Manual and tool shape (1.x)
```json
{
  "manual_version": "1.0.0",
  "utcp_version": "1.1",
  "tools": [
    {
      "name": "search_knowledge",
      "description": "Search the organization's approved knowledge base.",
      "inputs":  { "type": "object", "properties": { "query": {"type": "string"} }, "required": ["query"] },
      "outputs": { "type": "object", "properties": { "results": {"type": "array"} } },
      "tags": ["knowledge", "read"],
      "tool_call_template": {
        "call_template_type": "http",
        "url": "${CSP_TOOL_BASE_URL}/tools/search_knowledge",
        "http_method": "POST",
        "auth": { "auth_type": "api_key", "api_key": "Bearer ${CSP_TOOL_TOKEN}", "var_name": "Authorization", "location": "header" }
      }
    }
  ]
}
```
> Exact keys inside `tool_call_template` (e.g. `http_method`, `content_type`, `body_field`, `header_fields`) must be confirmed against `utcp_http.http_call_template.HttpCallTemplate` when we install the package in Phase 6. We will **generate** the manual from code, not hand-write it, so a field-name mismatch fails tests instead of failing silently.

### 2.2 Call template types
`http`, `sse`, `streamable_http` (plugin `utcp-http`), `cli`, `text`, `mcp`. We only need **`http`**.

### 2.3 Auth types (built in)
| `auth_type` | Fields |
|---|---|
| `api_key` | `api_key`, `var_name` (default `X-Api-Key`), `location` (default `header`) |
| `basic` | `username`, `password` |
| `oauth2` | `token_url`, `client_id`, `client_secret`, optional `scope` (**client-credentials grant**) |

⚠️ **Zoho Desk uses the authorization-code + refresh-token grant**, not client credentials. UTCP's built-in `oauth2` therefore **can't** manage Zoho tokens directly. This is the main reason we put Zoho behind our own HTTP tool endpoints (§4).

### 2.4 Variables and secrets
- Placeholders `${VAR}` in manuals.
- Values come from client config `variables` or `load_variables_from` (e.g. `{"variable_loader_type": "dotenv", "env_file_path": ".env"}`).
- In 1.x variables are **namespaced per manual** (`<manual_name>__<VAR>`, e.g. `csp_tools__CSP_TOOL_TOKEN`).

### 2.5 Client API (from utcp.io API reference)
```python
from utcp.utcp_client import UtcpClient

client = await UtcpClient.create(config={...})        # pass config= by keyword
await client.register_manual(call_template)           # -> RegisterManualResult
tools = await client.search_tools(query, limit, any_of_tags_required)   # -> List[Tool]
result = await client.call_tool("csp_tools.search_knowledge", {"query": "warranty"})
async for chunk in client.call_tool_streaming(name, args): ...
await client.close()
```
Config keys: `variables`, `load_variables_from`, `tool_repository` (`in_memory`), `tool_search_strategy` (`tag_and_description_word_match`), `manual_call_templates`, `post_processing`, `allowed_communication_protocols`.
Registered tool names are namespaced **`<manual_name>.<tool_name>`**.

### 2.6 What UTCP gives us vs. what we must build
| Concern | UTCP native? | Our plan |
|---|---|---|
| Tool discovery / registry | ✅ | use it |
| Tool search | ✅ simple word/tag match | use it for the tool list. Our tool set is small (6), so all tools are given to Claude |
| Secret substitution | ✅ | use it, with values from env/secret manager |
| Auth (api_key/basic/client-cred OAuth) | ✅ | api_key for our internal tool server |
| Restricting protocols | ✅ `allowed_communication_protocols` | set to `["http"]` |
| HTTPS enforcement for remote hosts | ✅ | (local dev uses http://localhost) |
| **Timeouts** | ⚠️ per call template only | our adapter wraps each call in `asyncio.timeout()` |
| **Retries** | ❌ | our adapter: `tenacity`, exponential backoff, **only for idempotent/read tools** or calls carrying an idempotency key |
| **Permissions / allow-lists** | ❌ (recommendations only) | our policy layer (§5) |
| **Input/output validation** | ⚠️ schemas are declared, enforcement isn't guaranteed | our adapter validates with Pydantic before and after |
| **Execution logs** | ❌ | our adapter → `agent_executions.tool_calls`, audit log, Langfuse span |
| Rate limiting | ❌ | Redis limiter in the tool server |

## 3. Claude does not speak UTCP. The adapter we build

**Claude knows nothing about UTCP.** Claude's Messages API takes `tools=[{name, description, input_schema}]` and returns `tool_use` blocks. We build the translation:

```
┌──────────────┐  tool defs    ┌──────────────┐   tools=[...]   ┌─────────┐
│ UTCP manual  │──────────────►│ UtcpClaude-  │────────────────►│ Claude  │
│ (GET /utcp)  │  (via         │ Adapter      │◄────────────────│  API    │
└──────────────┘  UtcpClient)  │              │   tool_use      └─────────┘
                               │ 1. name map  │
                               │ 2. policy    │  call_tool()   ┌───────────────┐
                               │ 3. validate  │───────────────►│ Tool server   │
                               │ 4. inject ctx│◄───────────────│ (FastAPI)     │
                               │ 5. timeout/  │    result      │ → KB / Zoho / │
                               │    retry/log │                │   email       │
                               └──────────────┘                └───────────────┘
```

Adapter responsibilities (`backend/app/tools/utcp_adapter.py`):
1. **Schema translation**: UTCP `Tool.inputs` → Anthropic `input_schema`. `strict: true` with `additionalProperties: false` so Claude's arguments are schema-valid.
2. **Name mapping**: UTCP names contain a dot (`csp_tools.create_ticket`). Anthropic tool names are restricted to letters, digits, `_` and `-` (re-verify against the current tool-use docs in Phase 6). The adapter maps `csp_tools.create_ticket` ↔ `csp_tools__create_ticket` with a lookup table, never by string guessing.
3. **Policy check** (§5) before every call.
4. **Context injection**: `organization_id`, `conversation_id`, `customer_id` come from the **graph state** (authenticated session), and **never** from model output. Model-supplied values for these keys are dropped.
5. **Validation, timeout, retry, logging**: all listed in §2.6.
6. **Result shaping**: return `tool_result` blocks, with `is_error: true` on failure so Claude can recover gracefully.

**Why not `langchain-utcp-adapters`?** It exists under the official org (MIT), but its only release is 0.1.0 (2025-09-02, "UTCP 1.0.1+ compatible"), it is stale against core 1.2.0, it has 5 stars, and it targets LangChain tool objects. Our nodes call the Anthropic SDK directly, so we'd translate twice. A ~200-line adapter we own and test is lower risk. We can revisit it later.

**Where tool calling happens in the graph:** LangGraph decides *which step runs*, and each step decides deterministically which tool it needs. For example, the Ticket Creation node always calls `create_ticket` and never lets the model pick. Claude chooses tools only where model judgement helps (e.g. optional `get_customer_info` / `get_ticket_status` during "Where's my ticket?"). The answer-generation call has **no tools at all** (prompt-injection defence, see SECURITY_DESIGN §6).

Note for Claude Sonnet 5.5: forced `tool_choice` (`any`/`tool`) returns HTTP 400. That's another reason for code-driven tool calls in deterministic nodes. Where Claude picks, we use `tool_choice: auto` + `strict: true`.

## 4. The six tools: who exposes what

We **expose** one UTCP manual from our own FastAPI "tool server" (a router in the backend, separate port/path, separate auth) and **consume** it with `UtcpClient`.

| Tool (UTCP name `csp_tools.*`) | Exposed by | Backend action | Kind | Retry? |
|---|---|---|---|---|
| `search_knowledge` | our tool server | PostgreSQL FTS over live `knowledge_sections` | read | yes |
| `read_knowledge` | our tool server | load OKF file / section by path+anchor from org repo | read | yes |
| `get_customer_info` | our tool server | `customers` table (and later CRM) | read | yes |
| `create_ticket` | our tool server → `TicketProvider` | Zoho Desk / Mock / (Freshdesk later) | **write** | only with idempotency key |
| `get_ticket_status` | our tool server → `TicketProvider` | Zoho `GET /tickets/{id}` | read | yes |
| `send_notification` | our tool server → `Notifier` | SMTP / provider email | write | with idempotency key |

**Why wrap Zoho instead of pointing a UTCP manual straight at `desk.zoho.com`?**
- Zoho's OAuth refresh-token flow isn't covered by UTCP's built-in auth (§2.3).
- We need idempotency (duplicate-ticket prevention), PII redaction, tenant-specific credentials (each org has its own Zoho account and data centre) and the mock provider. None of these belong in the LLM-facing layer.
- The UTCP manual stays stable even when the provider changes (Zoho → Freshdesk). Only the `TicketProvider` implementation changes.

**Future option:** external parties can consume `GET /utcp` with their own API key to use our knowledge tools. That's "exposing" UTCP outward, and it's free once the tool server exists.

## 5. Permission model (enforced by adapter **and** tool server)

```python
TOOL_POLICY = {
  "search_knowledge":  {"nodes": {"knowledge_discovery", "agent_tools"}, "approval": "never"},
  "read_knowledge":    {"nodes": {"knowledge_retrieval", "agent_tools"}, "approval": "never"},
  "get_customer_info": {"nodes": {"agent_tools", "ticket_creation"},     "approval": "never"},
  "create_ticket":     {"nodes": {"ticket_creation"}, "approval": "policy",  # sensitive/urgent → human
                        "max_per_conversation": 1},
  "get_ticket_status": {"nodes": {"agent_tools"}, "approval": "never"},
  "send_notification": {"nodes": {"ticket_creation"}, "approval": "never", "llm_callable": False},
}
```
- **Adapter side:** a call is refused unless the current graph node is listed.
- **Tool-server side:** the request must carry a short-lived **service token** minted per graph run, scoped to `{org_id, conversation_id, allowed_tools}`. Even if someone bypassed the adapter, the server would refuse out-of-scope calls.
- Every call is written to `agent_executions.tool_calls` + `audit_logs`.

## 6. Packages & pins

```
utcp==1.2.*        # core (MPL-2.0)
utcp-http==1.1.*   # http call templates
```
(We don't install `utcp-cli` or `utcp-mcp`. Fewer plugins means less attack surface. `allowed_communication_protocols=["http"]`.)

## 7. Phase 6 verification tasks (before we rely on anything above)

1. Install the pinned versions and confirm the import paths: `utcp.utcp_client.UtcpClient`, `utcp_http.http_call_template.HttpCallTemplate`.
2. Confirm `HttpCallTemplate` field names and generate the manual from it. Contract test: `GET /utcp` parses with `UtcpManual` model.
3. Confirm variable namespacing (`<manual>__VAR`) with a real call.
4. Confirm timeout field units for the `http` template.
5. Confirm Anthropic tool-name pattern and that the name map round-trips.
6. Run each of the 6 tools through `UtcpClient.call_tool` in an integration test against the mock ticket provider.

## 8. Risks

| Risk | Mitigation |
|---|---|
| UTCP is beta, and 1.x minor releases may change fields | Pin minor versions. All UTCP code behind `ToolGateway` interface. Contract tests |
| Small community: issues may go unanswered | We use only the core + HTTP plugin. The adapter is ours. Fallback path: `ToolGateway` can call the same HTTP endpoints directly with httpx |
| No native retries/permissions | Implemented in adapter + tool server (and tested) |
| Confusion between UTCP and MCP concepts | UTCP only. `utcp-mcp` deliberately not installed |
