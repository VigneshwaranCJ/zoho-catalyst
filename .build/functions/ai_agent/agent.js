'use strict';
/**
 * Minimal agent loop (ReAct-style, prompt-based tool calling).
 * The model must reply with JSON: {"tool": "...", "args": {...}} or {"final": "..."}.
 * Prompt-based tool calling works with any QuickML model, not only those with native tool support.
 */
const { complete } = require('./llm');
const { describeTools, runTool } = require('./tools');

const MAX_STEPS = 5;

function systemPrompt() {
  return `You are a helpful assistant running on Zoho Catalyst. You can use tools.

TOOLS:
${describeTools()}

RULES:
- Reply with ONE JSON object and nothing else.
- To use a tool: {"tool": "<name>", "args": {...}}
- To answer the user: {"final": "<your answer>"}
- Use a tool whenever it gives a more accurate answer (math, time, saved notes, uploaded documents).
- For general knowledge, chit-chat or creative requests, answer directly from your own knowledge.
- After a TOOL_RESULT, either call another tool or give the final answer.`;
}

function buildPrompt(history, scratchpad) {
  const lines = [systemPrompt(), '', 'CONVERSATION:'];
  for (const m of history) lines.push(`${m.role === 'user' ? 'USER' : 'ASSISTANT'}: ${m.content}`);
  lines.push(...scratchpad);
  lines.push('', 'Respond with JSON only:');
  return lines.join('\n');
}

/** Extract the first JSON object from model output (models sometimes wrap it in prose or ```json). */
function parseAction(text) {
  const start = text.indexOf('{');
  const end = text.lastIndexOf('}');
  if (start !== -1 && end > start) {
    try {
      return JSON.parse(text.slice(start, end + 1));
    } catch { /* fall through */ }
  }
  return { final: text.trim() };
}

async function runAgent({ message, sessionId, storage }) {
  const history = await storage.getHistory(sessionId);
  history.push({ role: 'user', content: message });

  const scratchpad = [];
  const steps = [];
  let answer = null;

  for (let i = 0; i < MAX_STEPS && answer === null; i++) {
    const raw = await complete(buildPrompt(history, scratchpad));
    const action = parseAction(raw);

    if (action.tool) {
      const result = await runTool(action.tool, action.args, { storage });
      steps.push({ tool: action.tool, args: action.args || {}, result });
      scratchpad.push(`ASSISTANT: ${JSON.stringify({ tool: action.tool, args: action.args || {} })}`);
      scratchpad.push(`TOOL_RESULT ${action.tool}: ${JSON.stringify(result)}`);
    } else {
      answer = String(action.final ?? raw);
    }
  }
  if (answer === null) answer = 'I could not finish within the step limit. Please rephrase the question.';

  history.push({ role: 'assistant', content: answer });
  await storage.saveHistory(sessionId, history);
  return { answer, steps };
}

module.exports = { runAgent, parseAction };
