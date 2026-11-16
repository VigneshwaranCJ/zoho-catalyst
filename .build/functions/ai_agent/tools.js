'use strict';
/**
 * Tools the agent can call. Each tool: { description, params, run(args, ctx) }.
 * The agent loop (agent.js) lists these in the system prompt and executes them.
 */

const { askRag } = require('./llm');

const tools = {
  ask_documents: {
    description:
      "Answer questions from the organisation's uploaded documents (QuickML Knowledge Base via RAG). " +
      'Use for anything about company policies, product docs, manuals or other uploaded files. ' +
      'Returns an answer and citations; mention the document names you used.',
    params: { question: 'string, a self-contained question' },
    async run({ question }) {
      if (!question) return { error: 'question is required' };
      if (!process.env.RAG_ENDPOINT_URL) {
        return { error: 'Document search is not configured (RAG_ENDPOINT_URL is not set).' };
      }
      return askRag(String(question).slice(0, 2000));
    },
  },

  calculator: {
    description: 'Evaluate an arithmetic expression. Supports + - * / % ^ and parentheses.',
    params: { expression: 'string, e.g. "(12.5 * 4) / 3"' },
    async run({ expression }) {
      const expr = String(expression || '');
      if (!/^[\d\s+\-*/%().^]+$/.test(expr)) {
        return { error: 'Only numbers and + - * / % ^ ( ) are allowed.' };
      }
      // Safe: input is restricted to digits and arithmetic operators by the regex above.
      const value = Function(`"use strict"; return (${expr.replace(/\^/g, '**')});`)();
      return { expression: expr, result: value };
    },
  },

  get_current_time: {
    description: 'Get the current date and time, optionally in an IANA time zone.',
    params: { timezone: 'string, optional, e.g. "Asia/Kolkata"' },
    async run({ timezone }) {
      const tz = timezone || 'Asia/Kolkata';
      try {
        return { timezone: tz, now: new Date().toLocaleString('en-IN', { timeZone: tz }) };
      } catch {
        return { error: `Unknown time zone: ${tz}` };
      }
    },
  },

  save_note: {
    description: 'Save a note to long-term memory (Catalyst Data Store) so it can be recalled later.',
    params: { text: 'string, the note to save' },
    async run({ text }, ctx) {
      if (!text) return { error: 'text is required' };
      const saved = await ctx.storage.saveNote(String(text).slice(0, 2000));
      return { saved: true, ...saved };
    },
  },

  list_notes: {
    description: 'List the most recently saved notes from long-term memory.',
    params: { limit: 'number, optional, default 10' },
    async run({ limit }, ctx) {
      return { notes: await ctx.storage.listNotes(Math.min(Number(limit) || 10, 50)) };
    },
  },
};

function describeTools() {
  return Object.entries(tools)
    .map(([name, t]) => `- ${name}: ${t.description}\n  args: ${JSON.stringify(t.params)}`)
    .join('\n');
}

async function runTool(name, args, ctx) {
  const tool = tools[name];
  if (!tool) return { error: `Unknown tool "${name}". Available: ${Object.keys(tools).join(', ')}` };
  try {
    return await tool.run(args || {}, ctx);
  } catch (err) {
    return { error: err.message };
  }
}

module.exports = { tools, describeTools, runTool };
