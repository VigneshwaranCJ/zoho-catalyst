# Catalyst AI Agent

A simple tool-using AI agent running on **Zoho Catalyst**. It uses:

| Catalyst feature | Where it is used |
|---|---|
| **Serverless Functions** (Advanced I/O, Node 24, Express) | `functions/ai_agent/index.js`: the agent API |
| **QuickML LLM Serving** (GLM-4.7-Flash / Qwen) | `functions/ai_agent/llm.js`: the "brain" |
| **QuickML Knowledge Base + RAG** | `ask_documents` tool: answers from your uploaded documents, with citations |
| **Data Store + ZCQL** | `storage.js`: long-term notes (`AgentNotes` table) |
| **Cache** | `storage.js`: short-term chat history per session (2 h TTL) |
| **Web Client Hosting** | `client/`: chat UI served on the project domain |

```
Browser (client/) ──POST /server/ai_agent/chat──▶ ai_agent function
                                                 │  agent loop (max 5 steps)
                                                 ├─▶ QuickML LLM endpoint  (decide: tool or answer)
                                                 ├─▶ tools: calculator, get_current_time,
                                                 │          save_note / list_notes ─▶ Data Store
                                                 └─▶ Cache (conversation history)
```

The agent uses **prompt-based tool calling**: the model replies with `{"tool": ..., "args": ...}` or
`{"final": ...}`, the function runs the tool and loops. This works with any QuickML model, including
those without native tool calling. To add a tool, add an entry in `tools.js`.

## 1. Run locally (no Zoho account needed)

```bash
cd functions/ai_agent
npm install
npm test
npm run local
```
Open http://localhost:3000. It uses a **mock** model and in-memory storage, so you can try the full loop offline.

## 2. One-time Catalyst setup (console: https://console.catalyst.zoho.com)

1. **Create a project**, e.g. `AIAgent`. Pick your data center (IN/US/EU support LLM Serving).
2. **Data Store**: create table `AgentNotes` with a column `note` (Text / Var Char 2000).
   Set the table's permissions so the function can insert and select.
3. **Cache**: the default segment already exists; nothing to do.
4. **QuickML > Generative AI > LLM Serving**:
   - Open a model (e.g. **GLM-4.7-Flash**) > *Open Playground*.
   - Optionally paste instructions, set Temperature ~0.2 and Max Tokens ~1024 (low temperature keeps the JSON format reliable).
   - *Save Configuration* > *Endpoints* > *Create Endpoint*.
   - From **Endpoint Details** copy: the endpoint URL, the `CATALYST-ORG` value, and the **sample request body**.
     If the prompt field in the sample is not `prompt`, set `QUICKML_PROMPT_FIELD` to its name.
5. **OAuth credentials for the LLM call** (scope `QuickML.deployment.READ`):
   - Go to https://api-console.zoho.in (use `.com` / `.eu` for your DC) > *Self Client*.
   - Generate a code with scope `QuickML.deployment.READ`, then exchange it for a **refresh token**:
     ```bash
     curl -X POST "https://accounts.zoho.in/oauth/v2/token?grant_type=authorization_code&client_id=CLIENT_ID&client_secret=CLIENT_SECRET&code=CODE"
     ```
   - Keep the refresh token secret. Do not commit it.

## 3. Deploy

```bash
npm install -g zcatalyst-cli
```
```bash
catalyst login
```
From the project root (`E:\zoho_catalyst`), link this folder to your console project:
```bash
catalyst project:use
```
(or `catalyst init`, choose the existing project and keep the existing `functions` and `client` folders.)

Then:
```bash
catalyst deploy
```
The CLI prints the client URL (`https://<project>-<id>.development.catalystserverless.in/app/`)
and the function URL (`.../server/ai_agent/`).

**Set the environment variables** in the console: *Serverless > Functions > ai_agent > Configuration*
(or fill them in `functions/ai_agent/catalyst-config.json` before deploying, but never commit secrets):

| Variable | Value |
|---|---|
| `LLM_PROVIDER` | `quickml` (or `mock` for a demo without the LLM) |
| `QUICKML_ENDPOINT_URL` | Endpoint URL from step 2.4 |
| `QUICKML_ORG_ID` | `CATALYST-ORG` value from step 2.4 |
| `QUICKML_PROMPT_FIELD` | `prompt` unless the sample body uses another field |
| `ZOHO_ACCOUNTS_URL` | `https://accounts.zoho.in` / `.com` / `.eu` |
| `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_REFRESH_TOKEN` | From step 2.5 |

Test:
```bash
curl -X POST https://<your-domain>/server/ai_agent/chat -H "Content-Type: application/json" -d "{\"message\":\"What is 12*7?\",\"sessionId\":\"demo\"}"
```

`catalyst serve` runs the project locally against your real Data Store and Cache. Use it after `catalyst login`.

When ready for production: *Console > Deploy to Production* (projects start in the Development environment).

## 4. Document Q&A (RAG)

1. **QuickML > Generative AI > Knowledge Base > Upload Document**: add `.pdf`, `.docx` or `.txt` files
   (or link Zoho WorkDrive / Zoho Learn).
2. **Generative AI > RAG**: choose mode **Response Generation**, add the Knowledge Base documents,
   set Tolerance (default 0.2) and **Save Configuration**.
3. **Endpoints > Create Endpoint**, type **RAG configuration**, pick the saved configuration.
4. From its Endpoint Details copy the **Endpoint URL** and the `x-quickml-endpoint-key`, and put them in
   `catalyst-config.json` (`RAG_ENDPOINT_URL`) and `functions/ai_agent/.env` (`RAG_ENDPOINT_KEY`).
   The RAG endpoint takes `{"query": "..."}` (not `prompt`), set by `RAG_PROMPT_FIELD`.
5. `catalyst deploy`, then ask the agent something your documents answer. Replies show "📄 Sources".

The same OAuth token (`QuickML.deployment.READ`) is used for both the LLM and RAG endpoints.

## 5. Other Catalyst features to explore next

| Feature | Idea for this agent |
|---|---|
| **QuickML RAG** | Upload docs, create a RAG endpoint, add a `search_docs` tool |
| **Zia Services** (OCR, sentiment, keyword extraction, text analytics) | Tools like `analyze_sentiment` via `app.zia()` |
| **Authentication** (embedded / hosted login) | Per-user notes: filter by `CREATORID` |
| **Job Scheduling / Cron** | Daily summary of notes, sent via the **Mail** component |
| **Event Functions + Signals** | React to Data Store inserts (e.g., notify on a new note) |
| **Circuits** | Orchestrate multi-step agent workflows |
| **Stratus** (object storage) | Let users upload files for the agent to read |
| **AppSail** | Host a long-running agent server (e.g., streaming responses) instead of a function |
| **NoSQL** | Store full conversation transcripts |
| **Logs / APM** | *Console > DevOps > Logs* to debug the agent in production |

## Notes and limits

- The QuickML REST request/response body is only shown as a sample in the console, not fully in
  the public docs. `llm.js` accepts several response shapes. If you get "Unrecognised QuickML response shape",
  check the logged JSON and adjust `extractText`.
- The Node SDK `zcatalyst-sdk-node` is pinned to 2.5.0, the last supported version; Zoho recommends
  migrating to the newer JavaScript SDK over time.
- Function timeout is limited (about 30 s for Advanced I/O). Keep `MAX_STEPS` small and Max Tokens moderate.
