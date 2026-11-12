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

  console.log('All tests passed');
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
