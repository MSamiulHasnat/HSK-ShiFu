// Dictionary: search the textbooks' word lists by hanzi, pinyin (tones optional) or English.

import { api } from '../api.js';
import { app } from '../state.js';
import { citeBtn, esc, rich, speakBtn, statusPill, toast } from '../ui.js';

const noParens = s => s.replace(/[（(][^）)]*[）)]/g, '');

async function detailHtml(id) {
  const w = await api.word(id);
  const lessonLink = w.lesson ? `<a href="#/course/${w.level}/${w.lesson}">HSK ${w.level} · Lesson ${w.lesson}${w.lesson_title ? ' · ' + esc(w.lesson_title) : ''}</a>` : `HSK ${w.level}`;
  return { w, html: `<div class="card stack">
    <div class="word-hero"><span class="hz-huge">${esc(w.hanzi)}</span>
      <div class="stack" style="gap:6px"><div style="font-size:22px;color:var(--accent)">${esc(w.pinyin)}</div>
        <div style="font-size:17px"><span class="faint">${esc(w.pos)}</span> ${esc(w.meaning)}</div>
        <div class="row" style="gap:6px">${speakBtn(noParens(w.hanzi))} ${statusPill(w.status)}
          <span class="pill level">${esc(w.kind_label)}${w.kind === 'extra' && w.hsk_level ? ` (HSK ${w.hsk_level})` : ''}</span></div></div></div>
    <div class="muted">Taught in ${lessonLink} ${w.page ? citeBtn(w.level, w.page) : ''}</div>
    <div class="row"><button class="btn primary" id="ask">Ask 王老师 about this word</button>
      ${w.status === 'new' ? `<button class="btn" data-add="${esc(w.id)}">+ Add to flashcards</button>` : ''}
      <a class="btn" href="#/practice?words=${encodeURIComponent(w.id)}">Drill it</a></div>
    ${w.sentences.length ? `<div><h3>In the textbook</h3>${w.sentences.map(s => `<div class="sentence">${speakBtn(s.text, true)}
      <div style="flex:1;min-width:0"><div class="zh">${rich(s.text)}</div>${s.pinyin ? `<div class="py">${esc(s.pinyin)}</div>` : ''}
      ${s.english ? `<div class="en">${esc(s.english)}</div>` : ''}</div>${citeBtn(s.level, s.page)}</div>`).join('')}</div>`
      : '<p class="faint">No example sentences containing this word were found in the lesson texts.</p>'}
    ${w.other_entries.length ? `<div><h3>Other entries for these characters</h3>${w.other_entries.map(o => `
      <a class="result" style="text-decoration:none;color:inherit" href="#/word/${encodeURIComponent(o.id)}"><b>${esc(o.hanzi)}</b>
        <span class="pinyin">${esc(o.pinyin)}</span><span class="m">${esc(o.pos)} ${esc(o.meaning)} · HSK ${o.level}${o.lesson ? ' L' + o.lesson : ''}</span></a>`).join('')}</div>` : ''}
  </div>` };
}

export async function render(root, { name, params, query }) {
  const selected = name === 'word' ? params[0] : null;
  root.innerHTML = `<div class="page wide"><h1>Dictionary</h1>
    <p class="sub">Every word from the HSK 1–3 textbooks’ word lists — search by characters, pinyin (tones optional) or English.</p>
    <input class="text" id="q" type="search" placeholder="e.g. 已经, yijing, already" value="${esc(query.q || '')}" autocomplete="off" aria-label="Search words">
    <div class="dict section${selected ? ' has-detail' : ''}" id="dict"><div class="results" id="results"></div><div id="detail"></div></div></div>`;
  const input = root.querySelector('#q');
  const results = root.querySelector('#results');
  const detail = root.querySelector('#detail');
  let timer = 0;
  let seq = 0;

  async function search(q) {
    const mine = ++seq;
    if (!q.trim()) {
      const lvl = app.settings.target_level;
      results.innerHTML = `<div class="empty" style="padding:22px"><div class="big">词</div>Type to search ${Object.keys(app.lexicon?.words || {}).length || ''} words.
        <div style="margin-top:10px"><a href="#/course?level=${lvl}">Browse HSK ${lvl} by lesson →</a></div></div>`;
      return;
    }
    const data = await api.get('/api/words/search?q=' + encodeURIComponent(q.trim()) + '&limit=60').catch(() => ({ results: [] }));
    if (mine !== seq) return;
    results.innerHTML = data.results.length ? data.results.map(w => `<a class="result${w.id === selected ? ' on' : ''}" style="text-decoration:none;color:inherit"
      href="#/word/${encodeURIComponent(w.id)}?q=${encodeURIComponent(q)}"><b>${esc(w.hanzi)}</b><span class="pinyin">${esc(w.pinyin)}</span>
      <span class="m">${esc(w.meaning)}</span><span class="pill level">${w.level}</span></a>`).join('')
      : `<div class="empty" style="padding:22px">No textbook word matches “${esc(q)}”.<div class="faint" style="margin-top:6px">
        This dictionary only contains words from the HSK 1–3 textbooks.</div></div>`;
  }

  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      history.replaceState(null, '', `#/dictionary?q=${encodeURIComponent(input.value)}`);
      search(input.value);
    }, 160);
  });

  await search(input.value);
  if (selected) {
    try {
      const { w, html } = await detailHtml(selected);
      detail.innerHTML = `${query.q ? `<a class="btn ghost small" href="#/dictionary?q=${encodeURIComponent(query.q)}" style="margin-bottom:8px">← Results</a>` : ''}${html}`;
      detail.querySelector('#ask').addEventListener('click', () => app.startTutor({ type: 'word', id: w.id },
        `Teach me the word ${w.hanzi} (${w.pinyin}). How is it used in the textbook? Then give me one question.`));
      if (!input.value) input.value = '';
    } catch (err) {
      detail.innerHTML = `<div class="callout error">${esc(err.message)}</div>`;
      toast(err.message);
    }
  } else {
    input.focus();
  }
}
