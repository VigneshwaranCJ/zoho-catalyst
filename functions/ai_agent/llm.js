'use strict';
/**
 * LLM providers.
 *  - quickml: Catalyst QuickML LLM Serving endpoint (GLM-4.7-Flash / Qwen), called over REST.
 *  - mock:    offline, rule-based stand-in so the agent loop can be tested without credentials.
 *
 * QuickML endpoints are created in the console from a saved playground configuration
 * (model, instructions, temperature, max tokens are fixed there). The request carries the prompt.
 * Copy the exact URL and sample body from the endpoint's "Endpoint Details" page; if the body
 * field is not "prompt", set QUICKML_PROMPT_FIELD.
 */

let cachedToken = { value: null, expiresAt: 0 };

async function getAccessToken() {
  if (cachedToken.value && Date.now() < cachedToken.expiresAt) return cachedToken.value;

  const { ZOHO_ACCOUNTS_URL, ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN } = process.env;
  if (!ZOHO_CLIENT_ID || !ZOHO_CLIENT_SECRET || !ZOHO_REFRESH_TOKEN) {
    throw new Error('Missing ZOHO_CLIENT_ID / ZOHO_CLIENT_SECRET / ZOHO_REFRESH_TOKEN env variables.');
  }
  const params = new URLSearchParams({
    refresh_token: ZOHO_REFRESH_TOKEN,
    client_id: ZOHO_CLIENT_ID,
    client_secret: ZOHO_CLIENT_SECRET,
    grant_type: 'refresh_token',
  });
  const res = await fetch(`${ZOHO_ACCOUNTS_URL || 'https://accounts.zoho.in'}/oauth/v2/token`, {
    method: 'POST',
    body: params,
  });
  const data = await res.json();
  if (!data.access_token) throw new Error(`OAuth refresh failed: ${JSON.stringify(data)}`);
  cachedToken = { value: data.access_token, expiresAt: Date.now() + ((data.expires_in || 3600) - 120) * 1000 };
  return cachedToken.value;
}

/**
 * POST to any QuickML GenAI endpoint (LLM or RAG) and return the parsed JSON.
 * Headers follow the endpoint's "Required Headers" in the console.
 * QuickML intermittently returns HTTP 500 LLM_CALL_FAILED; the same request usually succeeds on retry.
 */
async function postQuickML({ url, endpointKey, field, input, label }) {
  if (!url) throw new Error(`${label} endpoint URL is not set.`);
  const token = await getAccessToken();
  const headers = {
    Authorization: `Zoho-oauthtoken ${token}`,
    'Content-Type': 'application/json',
    Environment: process.env.QUICKML_ENVIRONMENT || 'Development',
  };
  if (process.env.QUICKML_ORG_ID) headers['CATALYST-ORG'] = process.env.QUICKML_ORG_ID;
  if (endpointKey) headers['x-quickml-endpoint-key'] = endpointKey;
  const body = JSON.stringify({ [field || 'prompt']: input });

  // Measured 2026-11-11: ~35-40% of calls fail with LLM_CALL_FAILED, each failure in <0.5 s.
  // 6 attempts brings a per-call failure to well under 1% while adding at most ~4.5 s.
  const MAX_ATTEMPTS = Number(process.env.QUICKML_MAX_ATTEMPTS) || 6;
  for (let attempt = 1; ; attempt++) {
    const res = await fetch(url, { method: 'POST', headers, body });
    const text = await res.text();
    if (res.ok) return JSON.parse(text);
    const retryable = res.status >= 500 || res.status === 429;
    if (!retryable || attempt >= MAX_ATTEMPTS) {
      throw new Error(`${label} HTTP ${res.status}: ${text.slice(0, 500)}`);
    }
    console.warn(`${label} HTTP ${res.status} (attempt ${attempt}/${MAX_ATTEMPTS}), retrying`);
    await new Promise((r) => setTimeout(r, 300 * attempt));
  }
}

async function callQuickML(prompt) {
  const data = await postQuickML({
    url: process.env.QUICKML_ENDPOINT_URL,
    endpointKey: process.env.QUICKML_ENDPOINT_KEY,
    field: process.env.QUICKML_PROMPT_FIELD,
    input: prompt,
    label: 'QuickML',
  });
  return extractText(data);
}

/**
 * Ask the QuickML RAG endpoint (Knowledge Base documents). Returns { answer, citations }.
 * Works for "Response Generation" / "Agentic RAG" (answer + citations) and "Document Search" (chunks only).
 */
async function askRag(question) {
  const data = await postQuickML({
    url: process.env.RAG_ENDPOINT_URL,
    endpointKey: process.env.RAG_ENDPOINT_KEY,
    // RAG endpoints expect {"query": ...} ({"prompt": ...} gives 400 LESS_THAN_MIN_OCCURANCE).
    field: process.env.RAG_PROMPT_FIELD || 'query',
    input: question,
    label: 'QuickML RAG',
  });
  return parseRag(data);
}

function parseRag(data) {
  const items = [data?.result, data?.data?.result, data?.data].find(Array.isArray) || [];
  const first = items[0] || {};

  // Answer text: generation modes put it in content / data; document search has none.
  let answer;
  try {
    answer = extractText(data);
  } catch {
    answer = typeof first.content === 'string' ? first.content : null;
  }

  // Citations: explicit citations[] or, for document search, the result chunks themselves.
  const raw = Array.isArray(first.citations) ? first.citations
    : Array.isArray(data?.citations) ? data.citations
    : items.filter((i) => i && typeof i.text === 'string');
  const citations = raw.slice(0, 5).map((c) => ({
    document: c.document_name || c.documentName || c.source || 'document',
    page: c.page_number ?? c.page ?? null,
    score: typeof c.score === 'number' ? Number(c.score.toFixed(3)) : c.score ?? null,
    text: String(c.text || c.content || '').slice(0, 600),
  }));

  if (!answer && !citations.length) {
    throw new Error(`Unrecognised RAG response shape: ${JSON.stringify(data).slice(0, 500)}`);
  }
  return { answer, citations };
}

/** Pull the generated text out of the response, tolerating a few envelope shapes. */
function extractText(data) {
  const candidates = [
    data?.data?.[0]?.data, // QuickML LLM endpoint: {"data":[{"data":"<LLM-Response>"}],"usage":{...}}
    data?.result?.[0]?.content,
    data?.data?.result?.[0]?.content,
    data?.response,
    data?.data?.response,
    data?.output,
    data?.choices?.[0]?.message?.content,
    typeof data?.result === 'string' ? data.result : undefined,
  ];
  const found = candidates.find((c) => typeof c === 'string' && c.length);
  if (!found) throw new Error(`Unrecognised QuickML response shape: ${JSON.stringify(data).slice(0, 500)}`);
  return found;
}

/**
 * Offline stand-in: looks at the latest user message / tool result in the prompt
 * and produces the same JSON protocol a real model would.
 */
async function callMock(prompt) {
  const lastTool = prompt.lastIndexOf('TOOL_RESULT');
  const lastUser = prompt.lastIndexOf('USER:');
  if (lastTool > lastUser) {
    const result = prompt.slice(lastTool).split('\n')[0].replace(/^TOOL_RESULT \w+:\s*/, '');
    return JSON.stringify({ final: `Here is what I found: ${result}` });
  }
  const msg = prompt.slice(lastUser + 5).split('\n')[0].trim();
  const lower = msg.toLowerCase();
  const math = msg.match(/[\d(][\d\s+\-*/%().^]*[\d)]/);
  if (/\b(remember|note that|save)\b/.test(lower)) {
    return JSON.stringify({ tool: 'save_note', args: { text: msg.replace(/^.*?(remember|note that|save)\s*(that)?\s*/i, '') } });
  }
  if (/\bnotes?\b|\brecall\b/.test(lower)) return JSON.stringify({ tool: 'list_notes', args: {} });
  if (/\b(document|docs|policy|policies|handbook|manual)\b/.test(lower)) {
    return JSON.stringify({ tool: 'ask_documents', args: { question: msg } });
  }
  if (/\btime\b|\bdate\b|\btoday\b/.test(lower)) return JSON.stringify({ tool: 'get_current_time', args: {} });
  if (math && /[+\-*/%^]/.test(math[0])) return JSON.stringify({ tool: 'calculator', args: { expression: math[0].trim() } });
  return JSON.stringify({ final: `(mock model) You said: "${msg}". Set LLM_PROVIDER=quickml for real answers.` });
}

async function complete(prompt) {
  const provider = (process.env.LLM_PROVIDER || 'mock').toLowerCase();
  if (provider === 'quickml') return callQuickML(prompt);
  return callMock(prompt);
}

module.exports = { complete, extractText, askRag, parseRag };
