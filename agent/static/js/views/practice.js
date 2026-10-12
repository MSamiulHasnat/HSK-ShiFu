// Practice: exam-style drills and timed practice tests, built from the textbooks.

import { api } from '../api.js';
import { app, LEVELS } from '../state.js';
import { citeBtn, el, esc, rich, speak, speakBtn } from '../ui.js';

const TYPES = [['meaning', 'Meaning'], ['hanzi', 'Characters'], ['pinyin', 'Pinyin & tones'], ['listen', 'Listening'],
  ['cloze', 'Fill the gap'], ['order', 'Sentence order']];
const LESSONS = { 1: 15, 2: 15, 3: 20 };
const noParens = s => s.replace(/[（(][^）)]*[）)]/g, '');
const isHanziOpts = q => ['hanzi', 'listen', 'cloze'].includes(q.type);
const hzClass = text => (/[一-鿿]/.test(text) ? 'hz-font' : '');

function promptHtml(q) {
  const w = q.word;
  switch (q.type) {
    case 'meaning': return `<div class="hz-huge">${esc(w.hanzi)}</div>${speakBtn(noParens(w.hanzi))}`;
    case 'pinyin': return `<div class="hz-huge">${esc(w.hanzi)}</div>`;
    case 'hanzi': return `<div class="en-big">${esc(q.prompt.text)}</div><div class="faint">${esc(q.prompt.pos)}</div>`;
    case 'listen': return `<button class="btn big" data-play>🔊 Play</button><div class="faint" style="margin-top:8px">Press <kbd>R</kbd> to replay</div>`;
    case 'cloze': return `<div class="cloze">${esc(q.prompt.before)}<span class="gap" id="gap">？</span>${esc(q.prompt.after)}</div>`;
    case 'order': return `<div class="answer-row" id="answer"></div><div class="tiles" id="tiles">${q.tiles.map((t, i) =>
      `<button class="tile" data-tile="${i}">${esc(t)}</button>`).join('')}</div><span class="hz-font" style="font-size:20px">${esc(q.ending)}</span>`;
    default: return '';
  }
}

function explainHtml(q, correct) {
  const w = q.word;
  const answer = q.type === 'order' ? q.answer_tiles.join('') + q.ending : q.options[q.answer].label;
  const s = q.sentence;
  return `<div class="feedback ${correct ? 'ok' : 'no'}">
    <b>${correct ? '✓ Correct' : '✗ Not quite'}</b>${correct ? '' : ` — the answer is <span class="${hzClass(answer)}" style="font-size:18px">${esc(answer)}</span>`}
    <div class="row" style="margin-top:8px;gap:8px">${speakBtn(noParens(w.hanzi), true)}
      <a href="#/word/${encodeURIComponent(w.id)}" class="hz-font" style="font-size:20px;color:inherit;text-decoration:none">${esc(w.hanzi)}</a>
      <span class="pinyin">${esc(w.pinyin)}</span><span><span class="faint">${esc(w.pos)}</span> ${esc(w.meaning)}</span>${citeBtn(w.level, w.page)}</div>
    ${s ? `<div style="margin-top:8px">${speakBtn(s.text, true)} <span class="hz-font" style="font-size:17px">${rich(s.text)}</span>
      ${s.pinyin ? `<div class="pinyin" style="font-size:13px">${esc(s.pinyin)}</div>` : ''}${s.english ? `<div style="font-size:13.5px">${esc(s.english)}</div>` : ''}
      <div style="margin-top:4px">${citeBtn(s.level, s.page)}</div></div>` : ''}</div>`;
}

/** Show one question; resolves with { correct, given } once answered. */
function ask(container, q, { exam }) {
  return new Promise(resolve => {
    const card = el(`<div class="q-card"><div class="q-instr">${esc(q.instruction)}</div>
      <div class="q-prompt">${promptHtml(q)}</div>
      ${q.type === 'order' ? '<div class="row" style="justify-content:center"><button class="btn primary" id="check" disabled>Check</button></div>'
        : `<div class="options">${q.options.map((o, i) => `<button class="opt${isHanziOpts(q) ? ' hz-opt' : ''}" data-opt="${i}">
          <span class="k">${i + 1}</span><span>${esc(o.label)}</span></button>`).join('')}</div>`}
      <div id="after"></div></div>`);
    container.replaceChildren(card);
    const audio = q.type === 'listen' ? q.prompt.audio : null;
    if (audio) setTimeout(() => speak(audio), 150);
    card.querySelector('[data-play]')?.addEventListener('click', () => speak(audio));
    let answered = false;

    function finish(correct, given) {
      answered = true;
      document.removeEventListener('keydown', onKey);
      if (exam) { resolve({ correct, given }); return; }
      const after = card.querySelector('#after');
      after.innerHTML = explainHtml(q, correct) +
        '<div class="row" style="justify-content:flex-end;margin-top:12px"><button class="btn primary" id="next">Next <kbd>Enter</kbd></button></div>';
      const next = () => { document.removeEventListener('keydown', onNext); resolve({ correct, given }); };
      const onNext = e => {
        if (!card.isConnected) { document.removeEventListener('keydown', onNext); return; }
        if (e.key === 'Enter') { e.preventDefault(); next(); }
      };
      after.querySelector('#next').addEventListener('click', next);
      setTimeout(() => document.addEventListener('keydown', onNext), 50);
    }

    function choose(i) {
      if (answered) return;
      const correct = i === q.answer;
      card.querySelectorAll('[data-opt]').forEach(b => {
        b.disabled = true;
        const n = +b.dataset.opt;
        if (exam) b.classList.toggle('chosen', n === i);
        else if (n === q.answer) b.classList.add('right');
        else if (n === i) b.classList.add('wrong');
      });
      if (q.type === 'cloze' && !exam) card.querySelector('#gap').textContent = q.options[q.answer].label;
      finish(correct, q.options[i].label);
    }
    card.querySelectorAll('[data-opt]').forEach(b => b.addEventListener('click', () => choose(+b.dataset.opt)));

    if (q.type === 'order') {
      const placed = [];
      const answerRow = card.querySelector('#answer');
      const check = card.querySelector('#check');
      const sync = () => {
        answerRow.replaceChildren(...placed.map((t, k) => {
          const b = el(`<button class="tile">${esc(q.tiles[t])}</button>`);
          b.addEventListener('click', () => { if (answered) return; placed.splice(k, 1); card.querySelector(`[data-tile="${t}"]`).classList.remove('used'); sync(); });
          return b;
        }));
        check.disabled = placed.length !== q.tiles.length;
      };
      card.querySelectorAll('[data-tile]').forEach(b => b.addEventListener('click', () => {
        if (answered || b.classList.contains('used')) return;
        b.classList.add('used');
        placed.push(+b.dataset.tile);
        sync();
      }));
      check.addEventListener('click', () => {
        const given = placed.map(t => q.tiles[t]).join('');
        check.disabled = true;
        finish(given === q.answer_tiles.join(''), given);
      });
    }

    const onKey = e => {
      if (!card.isConnected) { document.removeEventListener('keydown', onKey); return; }
      if (e.target.closest('input, textarea')) return;
      if (/^[1-4]$/.test(e.key) && q.options) choose(+e.key - 1);
      else if (e.key.toLowerCase() === 'r' && audio) speak(audio);
    };
    document.addEventListener('keydown', onKey);
  });
}

async function runDrill(root, questions, title) {
  root.innerHTML = `<div class="page" style="max-width:720px"><div class="row between"><h1 style="margin:0">${esc(title)}</h1>
    <a class="btn ghost small" href="#/practice">✕ Quit</a></div>
    <div class="progress-line"><span id="bar" style="width:0"></span></div><div id="q"></div></div>`;
  const results = [];
  for (let i = 0; i < questions.length; i++) {
    if (!root.isConnected) return;
    root.querySelector('#bar').style.width = `${(100 * i) / questions.length}%`;
    const r = await ask(root.querySelector('#q'), questions[i], { exam: false });
    results.push({ q: questions[i], ...r });
    api.post('/api/drill/answer', { word_id: questions[i].word.id, correct: r.correct, mode: 'drill' })
      .then(() => window.dispatchEvent(new Event('hsk:progress'))).catch(() => {});
  }
  showResults(root, results, title);
}

function showResults(root, results, title, extra = '') {
  const right = results.filter(r => r.correct).length;
  const pct = Math.round((100 * right) / Math.max(1, results.length));
  const wrong = results.filter(r => !r.correct);
  const ids = [...new Set(wrong.map(r => r.q.word.id))];
  root.innerHTML = `<div class="page" style="max-width:720px"><h1>${esc(title)} — results</h1>
    <div class="card" style="text-align:center"><div class="result-ring" style="--p:${pct}"><div>${pct}%</div></div>
      <b>${right} of ${results.length} correct</b>${extra}</div>
    ${wrong.length ? `<div class="section"><h2>Review your mistakes</h2><div class="card" style="padding:4px 16px">${wrong.map(r => {
      const q = r.q;
      const answer = q.type === 'order' ? q.answer_tiles.join('') + q.ending : q.options[q.answer].label;
      return `<div class="mistake"><span class="hz-mid">${esc(q.word.hanzi)}</span><div style="flex:1;min-width:0">
        <div><span class="pinyin">${esc(q.word.pinyin)}</span> · ${esc(q.word.meaning)}</div>
        <div class="faint">${esc(q.instruction)} You: ${esc(r.given ?? '—')} · Answer: <b class="${hzClass(answer)}">${esc(answer)}</b></div></div>${citeBtn(q.word.level, q.word.page)}</div>`;
    }).join('')}</div></div>` : ''}
    <div class="row section">
      ${ids.length ? `<a class="btn primary" href="#/practice?words=${encodeURIComponent(ids.join(','))}">Drill my mistakes</a>
        <button class="btn" id="tutorReview">Go over them with 王老师</button>` : ''}
      <a class="btn" href="#/practice">New practice</a><a class="btn" href="#/today">Today</a></div></div>`;
  root.querySelector('#tutorReview')?.addEventListener('click', () => app.startTutor({ type: 'review', word_ids: ids.slice(0, 8) },
    `I just got these wrong in practice: ${wrong.slice(0, 8).map(r => r.q.word.hanzi).join('、')}. Help me understand them, then quiz me.`));
}

async function runTest(root, level) {
  const test = await api.get(`/api/test/${level}`);
  const all = test.sections.flatMap(s => s.questions.map(q => ({ q, section: s.title })));
  const started = Date.now();
  const deadline = started + test.minutes * 60000;
  root.innerHTML = `<div class="page" style="max-width:720px"><div class="row between"><h1 style="margin:0">HSK ${level} practice test</h1>
    <span class="timer" id="timer"></span></div><div class="faint" id="sec"></div>
    <div class="progress-line"><span id="bar" style="width:0"></span></div><div id="q"></div>
    <p class="faint">${esc(test.note)} Answers are revealed at the end.</p></div>`;
  let timedOut = false;
  let abandoned = false;
  const tick = () => {
    const left = Math.max(0, deadline - Date.now());
    const t = root.querySelector('#timer');
    if (!root.isConnected || !t) { abandoned = timedOut = true; clearInterval(timer); return; }
    t.textContent = `${Math.floor(left / 60000)}:${String(Math.floor(left / 1000) % 60).padStart(2, '0')}`;
    t.classList.toggle('low', left < 120000);
    if (!left) timedOut = true;
  };
  const timer = setInterval(tick, 500);
  tick();
  const results = [];
  for (let i = 0; i < all.length && !timedOut; i++) {
    if (!root.isConnected) { clearInterval(timer); return; }
    root.querySelector('#bar').style.width = `${(100 * i) / all.length}%`;
    root.querySelector('#sec').textContent = `${all[i].section} · question ${i + 1} of ${all.length}`;
    const r = await Promise.race([ask(root.querySelector('#q'), all[i].q, { exam: true }),
      new Promise(res => { const w = setInterval(() => { if (timedOut) { clearInterval(w); res(null); } }, 300); })]);
    if (!r) break;
    results.push({ q: all[i].q, section: all[i].section, ...r });
    await new Promise(res => setTimeout(res, 220));
  }
  clearInterval(timer);
  if (abandoned) return; // left the page: don't submit a half-finished test
  for (let i = results.length; i < all.length; i++) results.push({ q: all[i].q, section: all[i].section, correct: false, given: null });
  const sections = {};
  for (const r of results) {
    sections[r.section] = sections[r.section] || { right: 0, total: 0 };
    sections[r.section].total++;
    if (r.correct) sections[r.section].right++;
  }
  const seconds = Math.round((Date.now() - started) / 1000);
  const score = results.filter(r => r.correct).length;
  results.forEach(r => api.post('/api/drill/answer', { word_id: r.q.word.id, correct: r.correct, mode: 'test' }).catch(() => {}));
  await api.post('/api/test/result', { level, score, total: results.length, seconds, sections }).catch(() => {});
  window.dispatchEvent(new Event('hsk:progress'));
  const breakdown = `<div class="grid cols-2" style="margin-top:14px;text-align:left">${Object.entries(sections).map(([name, s]) =>
    `<div class="stat"><div class="v">${s.right}/${s.total}</div><div class="k">${esc(name)}</div></div>`).join('')}</div>
    <p class="faint">${timedOut ? 'Time ran out — unanswered questions count as wrong. ' : ''}Time: ${Math.floor(seconds / 60)}m ${seconds % 60}s.
    ${esc(test.note)}</p>`;
  showResults(root, results, `HSK ${level} practice test`, breakdown);
}

function setup(root, query) {
  let level = +(query.level || app.settings.target_level || 1);
  let lesson = query.lesson ? +query.lesson : 0;
  const types = new Set(TYPES.map(t => t[0]));
  let count = 10;
  const draw = () => {
    root.innerHTML = `<div class="page"><h1>Practice</h1>
      <p class="sub">Exam-style questions built from your textbook’s own words and sentences. Every answer is checked against the book.</p>
      <div class="grid cols-2">
        <div class="card stack"><h2 style="margin:0">Quick drill</h2>
          <div class="seg" id="lv">${LEVELS.map(l => `<button data-v="${l}" class="${l === level ? 'on' : ''}">HSK ${l}</button>`).join('')}</div>
          <label class="field">Lesson<select class="text" id="lesson"><option value="0">All lessons</option>
            ${Array.from({ length: LESSONS[level] }, (_, i) => `<option value="${i + 1}" ${lesson === i + 1 ? 'selected' : ''}>Lesson ${i + 1}</option>`).join('')}</select></label>
          <div><div class="faint" style="margin-bottom:6px">Question types</div><div class="row" style="gap:6px">${TYPES.map(([k, label]) =>
            `<button class="chip${types.has(k) ? ' on' : ''}" data-type="${k}">${label}</button>`).join('')}</div></div>
          <div class="row between"><div class="seg" id="count">${[10, 20, 30].map(n => `<button data-v="${n}" class="${n === count ? 'on' : ''}">${n} questions</button>`).join('')}</div>
            <button class="btn primary" id="go">Start drill</button></div></div>
        <div class="card stack"><h2 style="margin:0">Practice test</h2>
          <p class="muted" style="margin:0">30 questions in sections — listening, reading, fill-in-the-blank, and sentence building at HSK 3 — with a 25-minute timer.
            No feedback until the end, like the real thing.</p>
          <p class="faint" style="margin:0">Built from the textbook; not an official HSK paper.</p>
          <div class="row">${LEVELS.map(l => `<button class="btn${l === app.settings.target_level ? ' primary' : ''}" data-test="${l}">HSK ${l} test</button>`).join('')}</div></div>
      </div></div>`;
    root.querySelectorAll('#lv button').forEach(b => b.addEventListener('click', () => { level = +b.dataset.v; lesson = 0; draw(); }));
    root.querySelector('#lesson').addEventListener('change', e => { lesson = +e.target.value; });
    root.querySelectorAll('[data-type]').forEach(b => b.addEventListener('click', () => {
      if (types.has(b.dataset.type) && types.size > 1) types.delete(b.dataset.type); else types.add(b.dataset.type);
      b.classList.toggle('on', types.has(b.dataset.type));
    }));
    root.querySelectorAll('#count button').forEach(b => b.addEventListener('click', () => { count = +b.dataset.v; draw(); }));
    root.querySelector('#go').addEventListener('click', async () => {
      const qs = `level=${level}${lesson ? '&lesson=' + lesson : ''}&count=${count}&types=${[...types].join(',')}`;
      const { questions } = await api.get('/api/drill?' + qs);
      runDrill(root, questions, `HSK ${level}${lesson ? ' · Lesson ' + lesson : ''} drill`);
    });
    root.querySelectorAll('[data-test]').forEach(b => b.addEventListener('click', () => runTest(root, +b.dataset.test)));
  };
  draw();
}

export async function render(root, { query }) {
  if (query.words) {
    const { questions } = await api.get(`/api/drill?word_ids=${encodeURIComponent(query.words)}&count=${Math.min(30, query.words.split(',').length * 2)}`);
    runDrill(root, questions, 'Mistakes drill');
  } else if (query.mode === 'test') {
    root.innerHTML = `<div class="page" style="max-width:640px"><div class="card stack" style="text-align:center">
      <h1>HSK ${+query.level || 1} practice test</h1><p class="muted">30 questions · 25 minutes · answers revealed at the end.</p>
      <div class="row" style="justify-content:center"><button class="btn primary big" id="begin">Begin</button><a class="btn big" href="#/practice">Back</a></div></div></div>`;
    root.querySelector('#begin').addEventListener('click', () => runTest(root, +query.level || 1));
  } else {
    setup(root, query);
  }
  return () => speechSynthesis?.cancel();
}
