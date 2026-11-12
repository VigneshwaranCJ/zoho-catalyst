// The function is served by Catalyst at /server/<function_name>/ on the same domain as the client.
const API = '/server/ai_agent';
const log = document.getElementById('log');
const form = document.getElementById('form');
const input = document.getElementById('input');
const statusEl = document.getElementById('status');

let sessionId;
try {
  sessionId = localStorage.getItem('agentSession') || crypto.randomUUID();
  localStorage.setItem('agentSession', sessionId);
} catch {
  sessionId = crypto.randomUUID();
}

function add(text, cls, steps) {
  const div = document.createElement('div');
  div.className = `msg ${cls}`;
  div.textContent = text;
  if (steps && steps.length) {
    const s = document.createElement('div');
    s.className = 'steps';
    steps.forEach((st) => {
      const cites = st.tool === 'ask_documents' && st.result && st.result.citations;
      if (cites && cites.length) {
        const src = document.createElement('div');
        src.textContent = '📄 Sources: ' + [...new Set(cites.map((c) => c.document + (c.page != null ? ` (p. ${c.page})` : '')))].join(', ');
        s.appendChild(src);
        return;
      }
      const line = document.createElement('div');
      line.innerHTML = '🔧 <code></code>';
      line.querySelector('code').textContent = `${st.tool}(${JSON.stringify(st.args)}) → ${JSON.stringify(st.result)}`;
      s.appendChild(line);
    });
    div.appendChild(s);
  }
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

fetch(`${API}/health`)
  .then((r) => r.json())
  .then((h) => { statusEl.textContent = `${h.provider} · ${h.storage}`; })
  .catch(() => { statusEl.textContent = 'offline'; });

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const message = input.value.trim();
  if (!message) return;
  add(message, 'user');
  input.value = '';
  const btn = form.querySelector('button');
  btn.disabled = true;
  try {
    const res = await fetch(`${API}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, sessionId }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || res.statusText);
    add(data.answer, 'bot', data.steps);
  } catch (err) {
    add(`Error: ${err.message}`, 'bot error');
  } finally {
    btn.disabled = false;
    input.focus();
  }
});
