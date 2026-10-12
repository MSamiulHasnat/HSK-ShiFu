// Review: spaced-repetition flashcards over the textbook's word lists.

import { api } from '../api.js';
import { app, fmtInterval } from '../state.js';
import { citeBtn, esc, rich, speak, speakBtn } from '../ui.js';

const GRADES = [[1, 'Again'], [2, 'Hard'], [3, 'Good'], [4, 'Easy']];
const noParens = s => s.replace(/[（(][^）)]*[）)]/g, '');

export async function render(root, { query }) {
  const level = query.level ? +query.level : null;
  const lesson = query.lesson ? +query.lesson : null;
  const scope = lesson ? `level=${level}&lesson=${lesson}` : '';
  let autoplay = localStorage.getItem('hsk.autoplay') !== 'off';
  let queue = [];
  let counts = {};
  let idx = 0;
  let revealed = false;
  let busy = false;
  const done = { reviewed: 0, again: 0, missed: new Map() };

  root.innerHTML = `<div class="page" style="max-width:720px">
    <div class="row between"><div><h1>Review</h1>
      <p class="sub" style="margin:0">${lesson ? `Words from HSK ${level} · Lesson ${lesson} <a href="#/review" class="faint">(show everything due)</a>`
        : `Due cards and new words from HSK 1–${app.settings.target_level}`}</p></div>
      <div class="counts" id="counts"></div></div>
    <div class="section" id="stage"></div>
    <div class="row between faint" style="margin-top:14px"><span><kbd>Space</kbd> show answer · <kbd>1</kbd>–<kbd>4</kbd> grade · <kbd>R</kbd> replay audio</span>
      <label class="row" style="gap:6px"><input type="checkbox" id="autoplay" ${autoplay ? 'checked' : ''}> auto-play audio</label></div>
  </div>`;
  const stage = root.querySelector('#stage');
  root.querySelector('#autoplay').addEventListener('change', e => {
    autoplay = e.target.checked;
    localStorage.setItem('hsk.autoplay', autoplay ? 'on' : 'off');
  });

  function paintCounts() {
    const left = queue.slice(idx);
    const isNew = c => c.status === 'new';
    root.querySelector('#counts').innerHTML =
      `<span class="c-new"><b>${left.filter(isNew).length}</b> new</span>` +
      `<span class="c-learn"><b>${left.filter(c => c.status === 'learning').length}</b> learning</span>` +
      `<span class="c-rev"><b>${left.filter(c => !isNew(c) && c.status !== 'learning').length}</b> review</span>`;
  }

  async function load() {
    const data = await api.get(`/api/review/queue?limit=50${scope ? '&' + scope : ''}`);
    queue = data.cards;
    counts = data.counts;
    idx = 0;
  }

  function finished() {
    const missed = [...done.missed.values()];
    const capped = !lesson && counts.new_available > counts.new;
    stage.innerHTML = `<div class="flash">
      <div style="font-size:44px">${done.reviewed ? '🎉' : '✅'}</div>
      <h2 style="margin:0">${done.reviewed ? 'Session complete' : 'Nothing due right now'}</h2>
      ${done.reviewed ? `<p class="muted" style="margin:0">${done.reviewed} answer${done.reviewed === 1 ? '' : 's'} ·
        ${Math.round((100 * (done.reviewed - done.again)) / done.reviewed)}% remembered</p>` : ''}
      ${capped ? `<p class="muted" style="margin:0">You’ve reached today’s new-word limit (${app.settings.daily_new}). Change it on the Today page, or learn a lesson’s words from the Course.</p>` : ''}
      ${missed.length ? `<div class="word-chips" style="justify-content:center;margin-top:8px">${missed.map(w =>
        `<a class="word-chip" style="text-decoration:none;color:inherit" href="#/word/${encodeURIComponent(w.id)}"><b>${esc(w.hanzi)}</b><span class="pinyin">${esc(w.pinyin)}</span></a>`).join('')}</div>` : ''}
      <div class="row" style="justify-content:center;margin-top:10px">
        ${missed.length ? `<a class="btn primary" href="#/practice?words=${encodeURIComponent(missed.map(w => w.id).join(','))}">Drill the ones I missed</a>` : ''}
        <a class="btn" href="#/practice${lesson ? `?level=${level}&lesson=${lesson}` : ''}">Practice</a>
        <a class="btn" href="#/today">Back to Today</a></div></div>`;
    root.querySelector('#counts').innerHTML = '';
  }

  function show() {
    if (idx >= queue.length) return finished();
    revealed = false;
    const c = queue[idx];
    const w = c.word;
    paintCounts();
    stage.innerHTML = `<div class="flash" id="card">
      <div class="row" style="gap:8px"><span class="pill ${c.status}">${c.status === 'new' ? 'New word' : c.status === 'learning' ? 'Learning' : 'Review'}</span>
        <span class="pill level">HSK ${w.level}${w.lesson ? ' · L' + w.lesson : ''}</span></div>
      <div class="hz-huge">${esc(w.hanzi)}</div>
      ${speakBtn(noParens(w.hanzi))}
      <div id="back" hidden style="width:100%">
        <div class="py-big">${esc(w.pinyin)}</div>
        <div class="meaning"><span class="faint">${esc(w.pos)}</span> ${esc(w.meaning)}</div>
        <div style="margin-top:6px">${citeBtn(w.level, w.page)}</div>
        ${c.example ? `<div class="example"><div class="row" style="justify-content:center">${speakBtn(c.example.text, true)}
          <span class="hz-font" style="font-size:19px">${rich(c.example.text)}</span></div>
          ${c.example.pinyin ? `<div class="pinyin" style="font-size:13.5px">${esc(c.example.pinyin)}</div>` : ''}
          ${c.example.english ? `<div style="font-size:14px">${esc(c.example.english)}</div>` : ''}
          <div style="margin-top:4px">${citeBtn(c.example.level, c.example.page)}</div></div>` : ''}
      </div>
    </div>
    <div id="controls" style="margin-top:16px"><button class="btn primary big" id="reveal" style="width:100%">Show answer</button></div>`;
    stage.querySelector('#reveal').addEventListener('click', reveal);
    if (autoplay) speak(noParens(w.hanzi));
  }

  function reveal() {
    if (revealed || idx >= queue.length) return;
    revealed = true;
    const c = queue[idx];
    stage.querySelector('#back').hidden = false;
    stage.querySelector('#controls').innerHTML = `<div class="grades">${GRADES.map(([g, label]) =>
      `<button class="grade g${g}" data-grade="${g}">${label}<small>${fmtInterval(c.intervals[g])}</small></button>`).join('')}</div>`;
    stage.querySelectorAll('[data-grade]').forEach(b => b.addEventListener('click', () => grade(+b.dataset.grade)));
  }

  async function grade(g) {
    if (!revealed || busy) return;
    busy = true;
    const c = queue[idx];
    try {
      await api.post('/api/review/answer', { word_id: c.word.id, grade: g });
      done.reviewed++;
      if (g === 1) { done.again++; done.missed.set(c.word.id, c.word); }
      idx++;
      if (idx >= queue.length) await load(); // learning steps that came due, or the next batch
      window.dispatchEvent(new Event('hsk:progress'));
      show();
    } catch (err) {
      stage.insertAdjacentHTML('beforeend', `<div class="callout error" style="margin-top:10px">${esc(err.message)}</div>`);
    } finally {
      busy = false;
    }
  }

  const onKey = e => {
    if (e.target.closest('input, textarea') || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); revealed ? grade(3) : reveal(); }
    else if (/^[1-4]$/.test(e.key)) grade(+e.key);
    else if (e.key.toLowerCase() === 'r' && queue[idx]) speak(noParens(queue[idx].word.hanzi));
  };
  document.addEventListener('keydown', onKey);

  await load();
  show();
  return () => { document.removeEventListener('keydown', onKey); speechSynthesis?.cancel(); };
}
