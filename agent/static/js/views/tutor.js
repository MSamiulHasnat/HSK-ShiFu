// Tutor: streaming chat with 王老师, grounded in pinned textbook pages.

import { api, streamChat } from '../api.js';
import { app, fmtAgo } from '../state.js';
import { citeBtn, el, esc, renderMarkdown, toast } from '../ui.js';

const SESSION_KEY = 'hsk.session';

function splitFactCheck(text) {
  const i = text.indexOf('⚠️ Fact check');
  return i === -1 ? [text, ''] : [text.slice(0, i).trimEnd(), text.slice(i)];
}

function sourcesHtml(sources) {
  const chips = (sources || []).map(c => {
    const m = c.match(/Level (\d), page (\d+)/);
    return m ? citeBtn(m[1], m[2]) : '';
  }).join(' ');
  return chips ? `<span class="faint">Teaching from</span> ${chips}` : '';
}

function checksHtml(checks) {
  if (!checks?.length) return '';
  const found = checks.filter(c => c.found).length;
  const own = checks.length - found;
  const summary = [found && `✓ ${found} from the textbook`, own && `${own} of 王老师’s own`].filter(Boolean).join(' · ');
  return `<details class="checks"><summary>Sentence check: ${summary}</summary>${checks.map(c => {
    const m = c.citation && c.citation.match(/Level (\d), page (\d+)/);
    return `<div class="check-row"><span class="${c.found ? 'ok' : 'own'}">${c.found ? '✓' : '•'}</span>
      <span class="hz-font">${esc(c.text)}</span>${m ? citeBtn(m[1], m[2])
        : '<span class="faint">not printed in the textbook — the tutor’s own example</span>'}</div>`;
  }).join('')}</details>`;
}

async function starters() {
  const out = [];
  try {
    const map = await api.get('/api/course');
    const target = app.settings.target_level;
    const lesson = map.levels.filter(l => l.level <= target).flatMap(l => l.lessons)
      .find(l => l.mastery.new + l.mastery.learning > 0) || map.levels[target - 1].lessons[0];
    out.push({ title: `Study HSK ${lesson.level} · Lesson ${lesson.number}`, sub: `${lesson.title_zh} — ${lesson.title_en}`,
      focus: { type: 'lesson', level: lesson.level, lesson: lesson.number },
      message: `Let's study HSK ${lesson.level} Lesson ${lesson.number} (${lesson.title_zh}). Teach it to me step by step, starting with the first text and its new words.` });
    out.push({ title: 'Role-play the lesson dialogue', sub: 'You play one speaker, 王老师 plays the other',
      focus: { type: 'lesson', level: lesson.level, lesson: lesson.number },
      message: `Let's role-play the first dialogue of HSK ${lesson.level} Lesson ${lesson.number}. You play speaker A and I'll answer as speaker B. Correct my lines as we go.` });
    const g = lesson.grammar[0];
    if (g) out.push({ title: 'Explain a grammar point', sub: g.title, focus: { type: 'grammar', level: lesson.level, lesson: lesson.number, page: g.page },
      message: `Explain this grammar point from HSK ${lesson.level} Lesson ${lesson.number}: ${g.title}. Then give me one exercise.` });
  } catch { /* starters are optional */ }
  try {
    const stats = await api.get('/api/progress');
    if (stats.weak_words.length) out.push({ title: 'Review my weak words', sub: stats.weak_words.map(w => w.hanzi).join('、'),
      focus: { type: 'review', word_ids: stats.weak_words.map(w => w.id) },
      message: `Help me review the words I keep getting wrong: ${stats.weak_words.map(w => w.hanzi).join('、')}. Quiz me on them one at a time.` });
  } catch { /* optional */ }
  out.push({ title: 'Teach me 把字句', sub: 'The 把 sentence, HSK 3', message: 'Teach me 把字句' });
  out.push({ title: '还是 vs 或者', sub: 'Both mean “or” — when do I use which?', message: 'What is the difference between 还是 and 或者?' });
  return out.slice(0, 6);
}

export async function render(root) {
  // Re-check every time: the model server may have started (or stopped) since the page loaded.
  app.status = await api.get('/api/status').catch(() => app.status);
  const status = app.status || {};
  root.innerHTML = `<div class="tutor-view">
    <div class="tutor-top">
      <div class="title"><b id="ttl">王老师 · your HSK tutor</b><div class="topic-chip" id="topic"></div></div>
      ${status.provider ? `<span class="model-tag" id="modelTag" title="Language model writing the replies">${esc(status.provider)}${status.model ? ' · ' + esc(status.model) : ''}</span>` : ''}
      <button class="btn small" id="newChat">+ New</button>
      <button class="btn small ghost" id="historyBtn">History</button>
    </div>
    <div class="chat-log" id="log" aria-live="polite"></div>
    <div class="composer">
      <div class="box"><textarea id="input" rows="1" placeholder="Answer, ask a question, or say what you want to learn…" aria-label="Message"></textarea>
        <button class="btn primary" id="send">Send</button></div>
      <div class="hint"><span>Enter to send · Shift+Enter for a new line · tap an underlined word for its textbook entry</span>
        <span>Facts come from the textbooks; 📖 opens the page.</span></div>
    </div></div>`;

  const log = root.querySelector('#log');
  const input = root.querySelector('#input');
  const sendBtn = root.querySelector('#send');
  let sessionId = null;
  let busy = false;
  let controller = null;
  let lastSend = null;

  const nearBottom = () => log.scrollHeight - log.scrollTop - log.clientHeight < 120;
  const scroll = (force = false) => { if (force || nearBottom()) log.scrollTop = log.scrollHeight; };
  const setTopic = topic => { root.querySelector('#topic').textContent = topic ? '📖 ' + topic : ''; };
  const setBusy = on => {
    busy = on;
    sendBtn.textContent = on ? 'Stop' : 'Send';
    sendBtn.classList.toggle('primary', !on);
  };

  function addStudent(text) {
    log.appendChild(el(`<div class="msg student"><div class="bubble">${esc(text)}</div></div>`));
    scroll(true);
  }

  function addTutor(content = '', meta = '', checks = null) {
    const node = el(`<div class="msg tutor"><div class="avatar">王</div><div class="bubble">
      <details class="thinking" hidden><summary>🤔 Thinking</summary><pre></pre></details>
      <div class="md"></div><div class="factcheck"></div><div class="sentence-checks"></div><div class="meta"></div></div></div>`);
    log.appendChild(node);
    const md = node.querySelector('.md');
    const thinking = node.querySelector('.thinking');
    let raw = '';
    let frame = 0;
    const paint = (cursor = true) => {
      frame = 0;
      md.innerHTML = renderMarkdown(raw) || '';
      md.classList.toggle('cursor', cursor);
      scroll();
    };
    const view = {
      typing() { md.innerHTML = '<span class="typing"><i></i><i></i><i></i></span>'; },
      think(chunk) {
        thinking.hidden = false;
        if (!raw) thinking.open = true;
        thinking.querySelector('pre').textContent += chunk;
        scroll();
      },
      delta(chunk) {
        if (!raw) thinking.open = false;
        raw += chunk;
        if (!frame) frame = requestAnimationFrame(() => paint(true));
      },
      finish(text, sources, thinkingText, checks) {
        cancelAnimationFrame(frame);
        const [body, check] = splitFactCheck(text);
        raw = body;
        paint(false);
        if (thinkingText && !thinking.querySelector('pre').textContent) {
          thinking.hidden = false;
          thinking.querySelector('pre').textContent = thinkingText;
        }
        node.querySelector('.factcheck').innerHTML = check ? `<div class="callout warn md">${renderMarkdown(check)}</div>` : '';
        node.querySelector('.sentence-checks').innerHTML = checksHtml(checks);
        const metaEl = node.querySelector('.meta');
        metaEl.innerHTML = sourcesHtml(sources);
        const copy = el('<button class="icon-btn" title="Copy reply" aria-label="Copy reply">⧉</button>');
        copy.addEventListener('click', () => navigator.clipboard?.writeText(body).then(() => toast('Copied.')));
        metaEl.appendChild(copy);
      },
      fail(message, retry) {
        cancelAnimationFrame(frame);
        md.classList.remove('cursor');
        const box = el(`<div class="callout error" style="margin-top:${raw ? 10 : 0}px">${esc(message)} </div>`);
        if (retry) {
          const b = el('<button class="btn small" style="margin-left:6px">Try again</button>');
          b.addEventListener('click', () => { node.remove(); retry(); });
          box.appendChild(b);
        }
        if (!raw) md.innerHTML = '';
        node.querySelector('.factcheck').appendChild(box);
      },
    };
    if (content) view.finish(content, null, null, checks);
    if (meta) node.querySelector('.meta').insertAdjacentHTML('afterbegin', meta);
    return view;
  }

  async function welcome() {
    sessionId = null;
    localStorage.removeItem(SESSION_KEY);
    setTopic('');
    root.querySelector('#ttl').textContent = '王老师 · your HSK tutor';
    log.innerHTML = `<div class="welcome"><div class="seal">师</div>
      <h2 style="margin-bottom:4px">我是王老师 <span class="muted" style="font-weight:400">(Wǒ shì Wáng lǎoshī)</span></h2>
      <p class="muted" style="margin:0 auto;max-width:520px">I teach from the HSK Standard Course textbooks (Levels 1–3). I'll explain one step at a time,
        ask you questions, check your answers — and show you the page every fact comes from.</p>
      ${status.tutor_available === false ? `<div class="callout warn" style="margin:16px auto 0;max-width:560px;text-align:left">
        ${status.provider ? `The tutor's model server (${esc(status.provider)} at <code>${esc(status.model)}</code>) isn't responding.
        Start it, then reload this page.` : `The tutor needs a language model: set <code>HSK_AGENT_PROVIDER</code> to <code>ollama</code>,
        <code>llamacpp</code> or <code>anthropic</code> and restart the server.`}
        Flashcards, drills, the course and the dictionary all work without one.</div>` : ''}
      <div class="starter-grid" id="starters"></div></div>`;
    const grid = log.querySelector('#starters');
    for (const s of await starters()) {
      const b = el(`<button class="starter"><b>${esc(s.title)}</b><span>${esc(s.sub)}</span></button>`);
      b.addEventListener('click', () => send(s.message, s.focus));
      grid.appendChild(b);
    }
  }

  async function loadSession(id) {
    try {
      const data = await api.get('/chat/sessions/' + encodeURIComponent(id));
      sessionId = data.session_id;
      localStorage.setItem(SESSION_KEY, sessionId);
      log.innerHTML = '';
      root.querySelector('#ttl').textContent = data.title || 'Conversation';
      setTopic(data.topic);
      data.history.forEach((m, i) => (m.role === 'assistant'
        ? addTutor(m.content, i === 1 ? sourcesHtml(data.sources) : '', m.checks)
        : addStudent(m.content)));
      scroll(true);
    } catch {
      welcome();
    }
  }

  async function send(text, focus = null) {
    text = (text ?? input.value).trim();
    if (!text || busy) return;
    if (status.tutor_available === false) { toast('The tutor’s model isn’t available (see the note above).'); return; }
    if (!sessionId) log.innerHTML = '';
    input.value = '';
    input.style.height = 'auto';
    lastSend = { text, focus };
    addStudent(text);
    const reply = addTutor();
    reply.typing();
    setBusy(true);
    controller = new AbortController();
    let finished = false;
    let topicChanged = false;
    try {
      await streamChat({ message: text, session_id: sessionId, focus }, {
        meta: m => {
          topicChanged = m.topic_changed;
          sessionId = m.session_id;
          localStorage.setItem(SESSION_KEY, sessionId);
          if (m.topic) setTopic(m.topic);
          if (m.title) root.querySelector('#ttl').textContent = m.title;
        },
        thinking: t => reply.think(t.text),
        delta: d => reply.delta(d.text),
        done: d => {
          const tag = root.querySelector('#modelTag');
          if (tag && d.provider && d.provider !== status.provider) {
            tag.textContent = d.provider + ' (fallback)';
            tag.title = `${status.provider} didn't respond, so ${d.provider} answered`;
          }
          finished = true; reply.finish(d.reply, topicChanged ? d.sources : null, d.thinking, d.checks); },
        error: e => { finished = true; reply.fail(e.detail, () => send(lastSend.text, lastSend.focus)); },
      }, controller.signal);
      if (!finished) reply.fail('The reply was cut off.', () => send(lastSend.text, lastSend.focus));
    } catch (err) {
      if (err.name === 'AbortError') reply.fail('Stopped.');
      else reply.fail('Request failed: ' + err.message, () => send(lastSend.text, lastSend.focus));
    } finally {
      setBusy(false);
      controller = null;
      input.focus();
    }
  }

  async function showHistory() {
    const drawer = el(`<div class="drawer" role="dialog" aria-label="Past conversations"><header><b>Conversations</b>
      <button class="icon-btn" aria-label="Close">✕</button></header><div class="list"><div class="empty">Loading…</div></div></div>`);
    document.body.appendChild(drawer);
    const close = () => drawer.remove();
    drawer.querySelector('header button').addEventListener('click', close);
    const list = drawer.querySelector('.list');
    const sessions = await api.get('/chat/sessions').catch(() => []);
    list.innerHTML = sessions.length ? '' : '<div class="empty">No conversations yet.</div>';
    for (const s of sessions) {
      const row = el(`<div class="session-row${s.id === sessionId ? ' on' : ''}"><span class="t">${esc(s.title || 'Conversation')}</span>
        <span class="faint">${fmtAgo(s.last_active)}</span><button class="icon-btn" title="Delete" aria-label="Delete">✕</button></div>`);
      row.addEventListener('click', () => { if (!busy) { close(); loadSession(s.id); } });
      row.querySelector('button').addEventListener('click', async e => {
        e.stopPropagation();
        await api.post('/chat/reset', { session_id: s.id });
        row.remove();
        if (s.id === sessionId) welcome();
      });
      list.appendChild(row);
    }
    return close;
  }

  let closeDrawer = null;
  sendBtn.addEventListener('click', () => (busy ? controller?.abort() : send()));
  input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } });
  input.addEventListener('input', () => { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 160) + 'px'; });
  root.querySelector('#newChat').addEventListener('click', () => { if (!busy) welcome(); });
  root.querySelector('#historyBtn').addEventListener('click', async () => { closeDrawer = await showHistory(); });

  const pending = app.pendingTutor;
  app.pendingTutor = null;
  if (pending) {
    sessionId = null;
    log.innerHTML = '';
    send(pending.message, pending.focus);
  } else if (localStorage.getItem(SESSION_KEY)) {
    await loadSession(localStorage.getItem(SESSION_KEY));
  } else {
    await welcome();
  }
  input.focus();
  return () => { controller?.abort(); closeDrawer?.(); };
}
