'use strict';
/**
 * Catalyst Advanced I/O function (Express). Deployed URL:
 *   https://<project-domain>/server/ai_agent/
 * Routes:
 *   GET  /health   -> status + provider
 *   POST /chat     -> { message, sessionId } -> { answer, steps }
 *   GET  /notes    -> notes saved by the agent
 */
const fs = require('fs');
const path = require('path');
const express = require('express');

// Secrets live in functions/ai_agent/.env (gitignored). It is uploaded with `catalyst deploy`,
// because deploy replaces the console's environment variables with those in catalyst-config.json.
// Values already set in the environment win; the file only fills in missing ones.
for (const candidate of [
  path.join(__dirname, '.env'),
  path.join(process.cwd(), '.env'),
  path.join(__dirname, '..', '..', '.env'),
  path.join(__dirname, '..', '..', '..', '.env'),
]) {
  if (fs.existsSync(candidate)) {
    try {
      process.loadEnvFile(candidate);
      console.log(`Loaded local env file: ${candidate}`);
    } catch (err) {
      console.warn(`Could not load ${candidate}: ${err.message}`);
    }
    break;
  }
}
const { runAgent } = require('./agent');
const { createStorage } = require('./storage');

let catalyst = null;
try {
  catalyst = require('zcatalyst-sdk-node');
} catch {
  /* SDK not installed: local memory mode */
}

const app = express();
app.use(express.json({ limit: '64kb' }));

function storageFor(req) {
  if (catalyst && !process.env.LOCAL_MODE) {
    try {
      return createStorage(catalyst.initialize(req));
    } catch (err) {
      console.warn('Catalyst SDK init failed, using memory storage:', err.message);
    }
  }
  return createStorage(null);
}

app.get('/', (req, res) => {
  res.json({
    name: 'Catalyst AI Agent API',
    routes: { 'GET /health': 'status', 'POST /chat': '{ message, sessionId } -> { answer, steps }', 'GET /notes': 'saved notes' },
    ui: '/app/index.html',
  });
});

app.get('/health', (req, res) => {
  const required = ['QUICKML_ENDPOINT_KEY', 'ZOHO_CLIENT_ID', 'ZOHO_CLIENT_SECRET', 'ZOHO_REFRESH_TOKEN'];
  res.json({
    status: 'ok',
    provider: process.env.LLM_PROVIDER || 'mock',
    storage: storageFor(req).kind,
    secretsConfigured: required.every((k) => Boolean(process.env[k])),
  });
});

app.post('/chat', async (req, res) => {
  const message = String(req.body?.message || '').trim();
  const sessionId = String(req.body?.sessionId || 'default');
  if (!message) return res.status(400).json({ error: 'message is required' });
  if (message.length > 4000) return res.status(400).json({ error: 'message too long (max 4000 chars)' });

  try {
    const result = await runAgent({ message, sessionId, storage: storageFor(req) });
    res.json(result);
  } catch (err) {
    console.error('Agent error:', err);
    const busy = /LLM_CALL_FAILED|HTTP 5\d\d|HTTP 429/.test(err.message);
    res.status(busy ? 503 : 500).json({
      error: busy ? 'The AI model is busy right now. Please try again in a moment.' : err.message,
      detail: busy ? err.message : undefined,
    });
  }
});

app.get('/notes', async (req, res) => {
  try {
    res.json({ notes: await storageFor(req).listNotes(50) });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

module.exports = app;
