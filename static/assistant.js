/*
 * Chat UI for the local AI assistant.
 * The server streams newline-delimited JSON events; answers are drawn with DOM nodes only
 * (never innerHTML), so model output can not inject markup.
 */
(function () {
  'use strict';

  const root = document.getElementById('assistant');
  if (!root) return;

  const log = document.getElementById('chat-log');
  const empty = document.getElementById('chat-empty');
  const form = document.getElementById('chat-form');
  const input = document.getElementById('chat-input');
  const sendButton = document.getElementById('send-button');
  const stopButton = document.getElementById('stop-button');
  const clearButton = document.getElementById('clear-button');
  const banner = document.getElementById('ai-banner');
  const focusChip = document.getElementById('focus-chip');
  const focusText = document.getElementById('focus-text');
  const modelSelect = document.getElementById('model-select');
  const modelStatus = document.getElementById('model-status');
  const footerModel = document.getElementById('footer-model');
  const entryBase = root.dataset.entryBase || '/entries/';
  const storageKey = `archain-chat-${root.dataset.userId || '0'}`;
  const modelsUrl = root.dataset.modelsUrl;

  let messages = [];
  let focusId = root.dataset.focusId ? Number(root.dataset.focusId) : null;
  let focusTitle = root.dataset.focusTitle || '';
  let controller = null;
  let busy = false;
  let statusOk = true;
  let lastInfo = null;
  let currentModel = '';

  // Never fail silently: any script error is shown in the banner at the top of the page.
  function showProblem(text) {
    banner.replaceChildren();
    const message = document.createElement('p');
    message.textContent = text;
    banner.append(message);
    banner.hidden = false;
  }
  window.addEventListener('error', (event) => {
    if (event.message) showProblem(`Script error: ${event.message}. Press Ctrl+F5 to reload the page.`);
  });
  window.addEventListener('unhandledrejection', (event) => {
    const reason = event.reason && event.reason.message ? event.reason.message : String(event.reason);
    showProblem(`Script error: ${reason}. Press Ctrl+F5 to reload the page.`);
  });

  // ---- persistence (per tab, per user) -----------------------------------------
  function persist() {
    try {
      const keep = messages.filter((m) => !m.pending).slice(-30);
      sessionStorage.setItem(storageKey, JSON.stringify({ messages: keep, focusId, focusTitle }));
    } catch (error) { /* storage can be unavailable */ }
  }

  function restore() {
    try {
      const saved = JSON.parse(sessionStorage.getItem(storageKey) || 'null');
      if (saved && Array.isArray(saved.messages)) {
        messages = saved.messages;
        if (!root.dataset.focusId && saved.focusId) {
          focusId = saved.focusId;
          focusTitle = saved.focusTitle || '';
        }
      }
    } catch (error) { messages = []; }
  }

  // ---- tiny, safe markdown renderer -----------------------------------------------
  function inline(parent, text) {
    const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\[#\d+\])/g;
    let last = 0;
    let match;
    while ((match = pattern.exec(text))) {
      if (match.index > last) parent.append(document.createTextNode(text.slice(last, match.index)));
      const token = match[0];
      if (token.startsWith('**')) {
        const strong = document.createElement('strong');
        strong.textContent = token.slice(2, -2);
        parent.append(strong);
      } else if (token.startsWith('`')) {
        const code = document.createElement('code');
        code.textContent = token.slice(1, -1);
        parent.append(code);
      } else {
        const id = token.slice(2, -1);
        const link = document.createElement('a');
        link.className = 'cite';
        link.href = entryBase + id;
        link.textContent = `#${id}`;
        parent.append(link);
      }
      last = match.index + token.length;
    }
    if (last < text.length) parent.append(document.createTextNode(text.slice(last)));
  }

  function renderRich(container, text) {
    container.replaceChildren();
    let list = null;
    text.replace(/\r/g, '').split('\n').forEach((line) => {
      const item = /^\s*(?:[-*•]|\d+[.)])\s+(.*)$/.exec(line);
      if (item) {
        if (!list) {
          list = document.createElement(/^\s*\d/.test(line) ? 'ol' : 'ul');
          container.append(list);
        }
        const li = document.createElement('li');
        inline(li, item[1]);
        list.append(li);
        return;
      }
      list = null;
      if (!line.trim()) return;
      const heading = /^\s*#{1,4}\s+(.*)$/.exec(line);
      const block = document.createElement(heading ? 'h4' : 'p');
      inline(block, heading ? heading[1] : line);
      container.append(block);
    });
  }

  // ---- rendering ------------------------------------------------------------------
  function fillMessage(node, message) {
    node.replaceChildren();
    const bubble = document.createElement('div');
    bubble.className = 'bubble';

    if (message.role === 'user') {
      bubble.textContent = message.content;
    } else {
      if (message.content) {
        const body = document.createElement('div');
        body.className = 'bubble-body';
        renderRich(body, message.content);
        bubble.append(body);
      } else if (message.pending) {
        const wait = document.createElement('p');
        wait.className = 'muted typing';
        wait.textContent = message.status || 'Reading the diary…';
        bubble.append(wait);
      }
      if (message.error) {
        const error = document.createElement('p');
        error.className = 'form-error';
        error.textContent = message.error;
        bubble.append(error);
      }
      if (message.sources && message.sources.length && !message.pending) {
        const row = document.createElement('p');
        row.className = 'sources';
        row.append(document.createTextNode('Looked at: '));
        message.sources.forEach((source, index) => {
          const link = document.createElement('a');
          link.className = 'cite';
          link.href = entryBase + source.id;
          link.textContent = `#${source.id} ${source.title}`;
          row.append(link);
          if (index < message.sources.length - 1) row.append(document.createTextNode(' · '));
        });
        bubble.append(row);
      }
      if (message.note || message.stats) {
        const meta = document.createElement('p');
        meta.className = 'helper';
        const parts = [];
        if (message.note) parts.push(message.note);
        if (message.stats) {
          const { tokens, seconds, tps } = message.stats;
          parts.push(`${tokens || '?'} tokens in ${seconds}s${tps ? ` (${tps} tokens/s)` : ''}`);
        }
        meta.textContent = parts.join(' · ');
        bubble.append(meta);
      }
    }
    node.className = `chat-message role-${message.role}`;
    node.append(bubble);
  }

  function nearBottom() {
    return log.scrollHeight - log.scrollTop - log.clientHeight < 90;
  }

  function render() {
    log.replaceChildren();
    messages.forEach((message) => {
      const node = document.createElement('div');
      fillMessage(node, message);
      log.append(node);
    });
    empty.hidden = messages.length > 0;
    log.hidden = messages.length === 0;
    log.scrollTop = log.scrollHeight;
  }

  let frame = null;
  function updateLast() {
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = null;
      const node = log.lastElementChild;
      if (!node) return;
      const stick = nearBottom();
      fillMessage(node, messages[messages.length - 1]);
      if (stick) log.scrollTop = log.scrollHeight;
    });
  }

  function renderFocus() {
    focusChip.hidden = !focusId;
    focusText.textContent = focusId ? `Focused on entry #${focusId}${focusTitle ? ` – ${focusTitle}` : ''}` : '';
  }

  function setBusy(value) {
    busy = value;
    sendButton.disabled = value;
    stopButton.hidden = !value;
    input.disabled = false;
  }

  // ---- talking to the server ------------------------------------------------------------
  function historyForServer() {
    const turns = [];
    for (let index = 0; index < messages.length - 1; index += 1) {
      const question = messages[index];
      const answer = messages[index + 1];
      if (question.role === 'user' && answer.role === 'assistant' && !answer.pending && !answer.error && answer.content) {
        turns.push({ role: 'user', content: question.content }, { role: 'assistant', content: answer.content });
      }
    }
    return turns.slice(-6);
  }

  function handleEvent(event, reply) {
    switch (event.type) {
      case 'meta': reply.sources = event.sources || []; break;
      case 'queued': reply.status = 'Waiting for another request to finish…'; break;
      case 'start': reply.status = 'Reading the diary… (the first words can take a while on a CPU)'; break;
      case 'thinking': reply.status = 'The model is reasoning…'; break;
      case 'delta': reply.content += event.text; break;
      case 'done': reply.stats = { tokens: event.tokens, seconds: event.seconds, tps: event.tps }; break;
      case 'error': reply.error = event.message; break;
      default: break;
    }
  }

  async function ask(question) {
    if (busy) return;
    const user = { role: 'user', content: question };
    const reply = { role: 'assistant', content: '', pending: true, status: 'Sending…' };
    const history = historyForServer();
    messages.push(user, reply);
    controller = new AbortController();
    setBusy(true);

    try {
      render();
      const response = await fetch(root.dataset.chatUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, history, entry: focusId, model: currentModel }),
        signal: controller.signal,
      });
      if (!response.ok || !response.body) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `Request failed (${response.status})`);
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let newline;
        while ((newline = buffer.indexOf('\n')) >= 0) {
          const line = buffer.slice(0, newline).trim();
          buffer = buffer.slice(newline + 1);
          if (line) {
            try { handleEvent(JSON.parse(line), reply); } catch (error) { /* ignore a broken line */ }
          }
        }
        updateLast();
      }
    } catch (error) {
      if (error.name === 'AbortError') {
        reply.note = 'Stopped';
      } else {
        reply.error = error.message || 'Something went wrong.';
      }
    } finally {
      reply.pending = false;
      controller = null;
      setBusy(false);
      persist();
      render();
    }
  }

  function submit(text) {
    const question = text.trim();
    if (!question || busy) return;
    input.value = '';
    // Never gate on the status check: it can be slow while Ollama loads a big model. The chat request
    // itself reports the real problem (server unreachable, model missing...) in the conversation.
    ask(question);
  }

  // ---- model selector ------------------------------------------------------------
  async function loadModels() {
    if (!modelsUrl) return;
    try {
      const res = await fetch(modelsUrl);
      if (!res.ok) throw new Error('Failed to load models');
      const data = await res.json();
      currentModel = data.current || '';
      footerModel.textContent = currentModel;
      modelSelect.innerHTML = '';
      (data.models || []).forEach(m => {
        const opt = document.createElement('option');
        opt.value = m;
        opt.textContent = m;
        if (m === currentModel) opt.selected = true;
        modelSelect.append(opt);
      });
      modelStatus.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
          <polyline points="22 4 12 14.01 9 11.01"/>
        </svg>
        <span style="color: var(--muted);">${data.models?.length || 0} models available</span>
      `;
    } catch (e) {
      modelStatus.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <circle cx="12" cy="12" r="10"/>
          <line x1="15" y1="9" x2="9" y2="15"/>
          <line x1="9" y1="9" x2="15" y2="15"/>
        </svg>
        <span style="color: #dc2626;">Could not load models</span>
      `;
      modelSelect.innerHTML = '<option value="" disabled>Error loading models</option>';
    }
  }

  modelSelect.addEventListener('change', () => {
    currentModel = modelSelect.value;
    footerModel.textContent = currentModel;
    // Clear chat when model changes to avoid confusion
    if (messages.length > 0) {
      if (confirm('Changing model will clear the conversation. Continue?')) {
        messages = [];
        persist();
        render();
      } else {
        modelSelect.value = currentModel;
      }
    }
  });

  // ---- events -------------------------------------------------------------------------------
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    submit(input.value);
  });

  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      submit(input.value);
    }
  });

  document.querySelectorAll('[data-prompt]').forEach((element) => {
    element.addEventListener('click', () => submit(element.dataset.prompt));
  });

  stopButton.addEventListener('click', () => { if (controller) controller.abort(); });

  clearButton.addEventListener('click', () => {
    if (controller) controller.abort();
    messages = [];
    persist();
    render();
    input.focus();
  });

  document.getElementById('focus-clear').addEventListener('click', () => {
    focusId = null;
    focusTitle = '';
    renderFocus();
    persist();
  });

  // ---- backend status banner ---------------------------------------------------------------------
  function showBanner(info) {
    banner.replaceChildren();
    const message = document.createElement('p');
    message.textContent = info.message || 'The AI server is not available.';
    banner.append(message);
    if (info.hint) {
      const hint = document.createElement('code');
      hint.textContent = info.hint;
      banner.append(hint);
    }
    if (info.installed && info.installed.length) {
      const installed = document.createElement('p');
      installed.className = 'helper';
      installed.textContent = `Installed models: ${info.installed.join(', ')}. Set ARCHAIN_AI_MODEL to use one of them.`;
      banner.append(installed);
    }
    const retry = document.createElement('button');
    retry.type = 'button';
    retry.className = 'btn btn-ghost btn-sm';
    retry.textContent = 'Check again';
    retry.addEventListener('click', checkStatus);
    banner.append(retry);
    banner.hidden = false;
  }

  async function checkStatus() {
    try {
      const response = await fetch(root.dataset.statusUrl);
      const info = await response.json();
      lastInfo = info;
      const wasOk = statusOk;
      statusOk = info.state === 'ok';
      if (statusOk) {
        banner.hidden = true;
        fetch(root.dataset.warmupUrl, { method: 'POST' }).catch(() => {});
        if (!wasOk) loadModels();
      } else {
        showBanner(info);
      }
    } catch (error) {
      statusOk = false;
      lastInfo = { message: 'Could not check the AI server.' };
      showBanner(lastInfo);
    }
    setBusy(busy);
  }

  try {
    restore();
    renderFocus();
    render();
  } catch (error) {
    // A stale or broken saved conversation must never block the page: start fresh.
    messages = [];
    try { sessionStorage.removeItem(storageKey); } catch (ignore) { /* storage unavailable */ }
    render();
  }
  loadModels();
  checkStatus();
  // Recover on its own once Ollama / the model becomes available.
  setInterval(() => { if (!statusOk && !busy) checkStatus(); }, 10000);
})();