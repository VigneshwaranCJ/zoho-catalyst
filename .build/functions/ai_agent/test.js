'use strict';
// Offline tests for the agent loop with the mock provider and memory storage.
process.env.LOCAL_MODE = '1';
process.env.LLM_PROVIDER = 'mock';
const assert = require('assert');
const { runAgent, parseAction } = require('./agent');
const { createStorage } = require('./storage');
const { extractText } = require('./llm');

(async () => {
  const storage = createStorage(null);

  let r = await runAgent({ message: 'What is (12 + 8) * 3?', sessionId: 't1', storage });
  assert.strictEqual(r.steps[0].tool, 'calculator');
  assert.strictEqual(r.steps[0].result.result, 60);

  r = await runAgent({ message: 'Remember that the demo is on Friday', sessionId: 't1', storage });
  assert.strictEqual(r.steps[0].tool, 'save_note');

  r = await runAgent({ message: 'Show my notes', sessionId: 't1', storage });
  assert.strictEqual(r.steps[0].tool, 'list_notes');
  assert.match(JSON.stringify(r.steps[0].result), /demo is on Friday/);

  r = await runAgent({ message: 'What time is it?', sessionId: 't1', storage });
  assert.strictEqual(r.steps[0].tool, 'get_current_time');

  assert.strictEqual((await storage.getHistory('t1')).length, 8);

  // Parser tolerates fenced / chatty model output.
  assert.deepStrictEqual(parseAction('Sure!\n```json\n{"final":"hi"}\n```'), { final: 'hi' });
  assert.deepStrictEqual(parseAction('plain text'), { final: 'plain text' });

  // Calculator rejects code injection.
  const { runTool } = require('./tools');
  assert.ok((await runTool('calculator', { expression: 'process.exit()' }, {})).error);

  // QuickML response shape from the endpoint's sample response.
  assert.strictEqual(extractText({ data: [{ data: 'hello' }], usage: { total_tokens: 3 }, model: 'x' }), 'hello');
  // Older documented SDK shape.
  assert.strictEqual(extractText({ status: 'success', result: [{ content: 'ok', finish_reason: 'stop' }] }), 'ok');

  // QuickML retry: two 500s then success; and a 400 is not retried.
  {
    const { complete } = require('./llm');
    const saved = { ...process.env };
    Object.assign(process.env, {
      LLM_PROVIDER: 'quickml', QUICKML_ENDPOINT_URL: 'https://quickml.test/generate',
      ZOHO_CLIENT_ID: 'id', ZOHO_CLIENT_SECRET: 'secret', ZOHO_REFRESH_TOKEN: 'refresh',
    });
    const realFetch = global.fetch;
    const replies = [];
    let calls = 0;
    global.fetch = async (url) => {
      if (String(url).includes('/oauth/')) return { json: async () => ({ access_token: 't', expires_in: 3600 }) };
      calls++;
      const [status, body] = replies.shift();
      return { ok: status < 300, status, text: async () => body };
    };
    const quiet = console.warn;
    console.warn = () => {};
    try {
      replies.push([500, '{"code":"LLM_CALL_FAILED"}'], [500, '{"code":"LLM_CALL_FAILED"}'], [200, '{"data":[{"data":"ok"}]}']);
      assert.strictEqual(await complete('hi'), 'ok');
      assert.strictEqual(calls, 3);

      // Gives up after QUICKML_MAX_ATTEMPTS.
      calls = 0;
      process.env.QUICKML_MAX_ATTEMPTS = '2';
      replies.push([500, '{"code":"LLM_CALL_FAILED"}'], [500, '{"code":"LLM_CALL_FAILED"}']);
      await assert.rejects(complete('hi'), /HTTP 500/);
      assert.strictEqual(calls, 2);
      delete process.env.QUICKML_MAX_ATTEMPTS;

      calls = 0;
      replies.push([400, '{"code":"BAD_REQUEST"}']);
      await assert.rejects(complete('hi'), /HTTP 400/);
      assert.strictEqual(calls, 1);
    } finally {
      global.fetch = realFetch;
      console.warn = quiet;
      process.env = saved;
    }
  }

  // RAG response parsing: generation (SDK shape), LLM-like shape, and document search.
  {
    const { parseRag } = require('./llm');
    let r = parseRag({ status: 'success', result: [{ content: 'Leave is 20 days.', citations: [
      { document_name: 'HR Policy.pdf', document_id: '1', chunk_id: 'c1', page_number: 4, text: 'Employees get 20 days', score: 0.91234 },
    ] }] });
    assert.strictEqual(r.answer, 'Leave is 20 days.');
    assert.deepStrictEqual(r.citations[0], { document: 'HR Policy.pdf', page: 4, score: 0.912, text: 'Employees get 20 days' });

    r = parseRag({ data: [{ data: 'From the docs: yes.' }], usage: {} });
    assert.strictEqual(r.answer, 'From the docs: yes.');
    assert.strictEqual(r.citations.length, 0);

    r = parseRag({ status: 'success', result: [{ chunk_id: 'c9', document_name: 'Manual.docx', page_number: 2, text: 'Press reset', score: 0.5 }] });
    assert.strictEqual(r.answer, null);
    assert.strictEqual(r.citations[0].document, 'Manual.docx');

    assert.throws(() => parseRag({ unexpected: true }), /Unrecognised RAG/);
  }

  // ask_documents tool: unconfigured -> friendly error; configured -> calls the RAG endpoint.
  {
    const saved = { ...process.env };
    delete process.env.RAG_ENDPOINT_URL;
    assert.match((await runTool('ask_documents', { question: 'leave policy?' }, {})).error, /not configured/);

    Object.assign(process.env, {
      RAG_ENDPOINT_URL: 'https://quickml.test/rag', RAG_ENDPOINT_KEY: 'rag-key',
      ZOHO_CLIENT_ID: 'id', ZOHO_CLIENT_SECRET: 'secret', ZOHO_REFRESH_TOKEN: 'refresh',
    });
    const realFetch = global.fetch;
    let seen;
    global.fetch = async (url, opts) => {
      if (String(url).includes('/oauth/')) return { json: async () => ({ access_token: 't', expires_in: 3600 }) };
      seen = { url, headers: opts.headers, body: JSON.parse(opts.body) };
      return { ok: true, status: 200, text: async () => JSON.stringify({ result: [{ content: 'ok', citations: [] }] }) };
    };
    try {
      const out = await runTool('ask_documents', { question: 'leave policy?' }, {});
      assert.strictEqual(out.answer, 'ok');
      assert.strictEqual(seen.url, 'https://quickml.test/rag');
      assert.strictEqual(seen.headers['x-quickml-endpoint-key'], 'rag-key');
      assert.deepStrictEqual(seen.body, { query: 'leave policy?' });
    } finally {
      global.fetch = realFetch;
      process.env = saved;
    }
  }

  // Mock model routes document questions to ask_documents.
  {
    const r = await runAgent({ message: 'What does the leave policy say?', sessionId: 't2', storage });
    assert.strictEqual(r.steps[0].tool, 'ask_documents');
  }

  console.log('All tests passed');
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
