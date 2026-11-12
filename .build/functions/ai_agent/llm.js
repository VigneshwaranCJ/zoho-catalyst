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

async function callQuickML(prompt) {
  const url = process.env.QUICKML_ENDPOINT_URL;
  if (!url) throw new Error('QUICKML_ENDPOINT_URL is not set.');
  const token = await getAccessToken();
  // Headers as listed under the endpoint's "Required Headers" in the console.
  const headers = {
    Authorization: `Zoho-oauthtoken ${token}`,
    'Content-Type': 'application/json',
    Environment: process.env.QUICKML_ENVIRONMENT || 'Development',
  };
  if (process.env.QUICKML_ORG_ID) headers['CATALYST-ORG'] = process.env.QUICKML_ORG_ID;
  if (process.env.QUICKML_ENDPOINT_KEY) headers['x-quickml-endpoint-key'] = process.env.QUICKML_ENDPOINT_KEY;

  const field = process.env.QUICKML_PROMPT_FIELD || 'prompt';
  const res = await fetch(url, { method: 'POST', headers, body: JSON.stringify({ [field]: prompt }) });
  const text = await res.text();
  if (!res.ok) throw new Error(`QuickML HTTP ${res.status}: ${text.slice(0, 500)}`);
  return extractText(JSON.parse(text));
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
  if (/\btime\b|\bdate\b|\btoday\b/.test(lower)) return JSON.stringify({ tool: 'get_current_time', args: {} });
  if (math && /[+\-*/%^]/.test(math[0])) return JSON.stringify({ tool: 'calculator', args: { expression: math[0].trim() } });
  return JSON.stringify({ final: `(mock model) You said: "${msg}". Set LLM_PROVIDER=quickml for real answers.` });
}

async function complete(prompt) {
  const provider = (process.env.LLM_PROVIDER || 'mock').toLowerCase();
  if (provider === 'quickml') return callQuickML(prompt);
  return callMock(prompt);
}

module.exports = { complete, extractText };
