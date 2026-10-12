// Course: the three books as a lesson map, and each lesson's words, grammar and texts.

import { api } from '../api.js';
import { app, LEVELS } from '../state.js';
import { citeBtn, esc, masteryBar, rich, speakBtn, statusPill } from '../ui.js';

const noParens = s => s.replace(/[（(][^）)]*[）)]/g, '');

async function renderMap(root, level) {
  const map = await api.get('/api/course');
  const book = map.levels.find(l => l.level === level);
  root.innerHTML = `<div class="page wide">
    <h1>Course</h1><p class="sub">The HSK Standard Course, lesson by lesson. Bars show how many of each lesson’s words you know.</p>
    <div class="row between" style="margin-bottom:16px">
      <div class="seg" id="levels">${LEVELS.map(l => `<button data-level="${l}" class="${l === level ? 'on' : ''}">HSK ${l}</button>`).join('')}</div>
      <div class="legend"><span><i style="background:var(--st-mature)"></i>Mastered</span><span><i style="background:var(--st-young)"></i>Known</span>
        <span><i style="background:var(--st-learning)"></i>Learning</span></div>
    </div>
    <div class="lesson-grid">${book.lessons.map(l => `
      <a class="lesson-card" href="#/course/${l.level}/${l.number}" style="text-decoration:none">
        <span class="num">LESSON ${l.number}</span>
        <span class="zh">${esc(l.title_zh)}</span>
        <span class="en">${esc(l.title_en)}</span>
        ${masteryBar(l.mastery)}
        <span class="faint">${l.word_count} words · ${l.grammar.length} grammar point${l.grammar.length === 1 ? '' : 's'} · p.${l.start_page}–${l.end_page}</span>
      </a>`).join('')}</div></div>`;
  root.querySelectorAll('#levels button').forEach(b => b.addEventListener('click', () => app.go(`#/course?level=${b.dataset.level}`)));
}

async function renderLesson(root, level, number) {
  const d = await api.get(`/api/course/${level}/${number}`);
  const prev = number > 1 ? `#/course/${level}/${number - 1}` : null;
  const lastNumber = { 1: 15, 2: 15, 3: 20 }[level];
  const next = number < lastNumber ? `#/course/${level}/${number + 1}` : null;
  const withEnglish = d.sentences.filter(s => s.english || s.pinyin);
  const others = d.sentences.filter(s => !s.english && !s.pinyin);

  root.innerHTML = `<div class="page">
    <div class="row between"><a class="btn ghost small" href="#/course?level=${level}">← HSK ${level} lessons</a>
      <span class="row">${prev ? `<a class="btn ghost small" href="${prev}">‹ Prev</a>` : ''}${next ? `<a class="btn ghost small" href="${next}">Next ›</a>` : ''}</span></div>
    <div class="lesson-head" style="margin:10px 0 18px">
      <div class="faint">HSK ${level} · Lesson ${number} · pages ${d.start_page}–${d.end_page}</div>
      <div class="zh">${esc(d.title_zh)}</div>
      <div class="muted">${esc(d.title_pinyin)}${d.title_pinyin ? ' · ' : ''}${esc(d.title_en)}</div>
      <div style="max-width:380px;margin-top:10px">${masteryBar(d.mastery)}</div>
    </div>
    <div class="row">
      <button class="btn primary" id="study">Study with 王老师</button>
      <a class="btn" href="#/review?level=${level}&lesson=${number}">Learn these words</a>
      <a class="btn" href="#/practice?level=${level}&lesson=${number}">Drill this lesson</a>
      <button class="btn" id="roleplay">Role-play the dialogue</button>
    </div>

    <div class="section"><h2>Words <span class="badge soft">${d.words.length}</span></h2>
      <div class="card" style="padding:4px 12px"><table class="word-table"><tbody>${d.words.map(w => `
        <tr><td class="hz-cell"><a href="#/word/${encodeURIComponent(w.id)}" style="color:inherit;text-decoration:none">${esc(w.hanzi)}</a></td>
          <td class="pinyin">${esc(w.pinyin)}</td>
          <td><span class="pos">${esc(w.pos)}</span> ${esc(w.meaning)}${w.kind !== 'core' ? ` <span class="faint">· ${esc(w.kind_label)}${w.hsk_level ? ' (HSK ' + w.hsk_level + ')' : ''}</span>` : ''}</td>
          <td class="hide-sm">${statusPill(w.status)}</td>
          <td style="text-align:right;white-space:nowrap">${speakBtn(noParens(w.hanzi), true)} ${citeBtn(w.level, w.page)}</td></tr>`).join('')}
      </tbody></table></div></div>

    ${d.grammar.length ? `<div class="section"><h2>Grammar</h2><div class="card" style="padding:4px 16px">${d.grammar.map((g, i) => `
      <div class="grammar-item"><span class="n">${i + 1}</span><div class="t">${rich(g.title)}</div>
        ${citeBtn(level, g.page)}<button class="btn small" data-grammar="${i}">Learn it</button></div>`).join('')}</div></div>` : ''}

    ${d.sentences.length ? `<div class="section"><h2>Sentences from this lesson</h2>
      <div class="row" style="margin-bottom:8px"><label class="row" style="gap:6px;font-size:13.5px"><input type="checkbox" id="showPy" checked> pinyin</label>
        <label class="row" style="gap:6px;font-size:13.5px"><input type="checkbox" id="showEn" checked> English</label></div>
      <div class="card" style="padding:4px 16px" id="sentences">${[...withEnglish, ...others].map(s => `
        <div class="sentence">${speakBtn(s.text, true)}<div style="flex:1;min-width:0">
          <div class="zh">${rich(s.text)}</div>
          ${s.pinyin ? `<div class="py">${esc(s.pinyin)}</div>` : ''}
          ${s.english ? `<div class="en">${esc(s.english)}</div>` : ''}</div>${citeBtn(s.level, s.page)}</div>`).join('')}
      </div><p class="faint">Pinyin and English are shown only where the book prints them alongside the sentence.</p></div>` : ''}
  </div>`;

  root.querySelector('#study').addEventListener('click', () => app.startTutor({ type: 'lesson', level, lesson: number },
    `Let's study HSK ${level} Lesson ${number} (${d.title_zh}). Teach it to me step by step, starting with the first text and its new words.`));
  root.querySelector('#roleplay').addEventListener('click', () => app.startTutor({ type: 'lesson', level, lesson: number },
    `Let's role-play the first dialogue of HSK ${level} Lesson ${number}. You play speaker A and I'll answer as speaker B. Correct my lines as we go.`));
  root.querySelectorAll('[data-grammar]').forEach(b => b.addEventListener('click', () => {
    const g = d.grammar[+b.dataset.grammar];
    app.startTutor({ type: 'grammar', level, lesson: number, page: g.page },
      `Explain this grammar point from HSK ${level} Lesson ${number}: ${g.title}. Then give me one exercise.`);
  }));
  const box = root.querySelector('#sentences');
  root.querySelector('#showPy')?.addEventListener('change', e => box.querySelectorAll('.py').forEach(x => { x.hidden = !e.target.checked; }));
  root.querySelector('#showEn')?.addEventListener('change', e => box.querySelectorAll('.en').forEach(x => { x.hidden = !e.target.checked; }));
}

export async function render(root, { params, query }) {
  if (params.length >= 2) return renderLesson(root, +params[0], +params[1]);
  return renderMap(root, +(query.level || app.settings.target_level || 1));
}
