// Today: what to do now, how the student is doing, and settings.

import { api } from '../api.js';
import { app, LEVELS } from '../state.js';
import { esc, masteryBar, toast } from '../ui.js';

function nextLesson(courseMap, target) {
  for (const lvl of courseMap.levels.filter(l => l.level <= target)) {
    const lesson = lvl.lessons.find(l => l.mastery.new + l.mastery.learning > 0);
    if (lesson) return lesson;
  }
  return null;
}

function themeSeg() {
  const current = localStorage.getItem('hsk.theme') || 'auto';
  return `<div class="seg" id="theme">${['auto', 'light', 'dark'].map(t =>
    `<button data-theme="${t}" class="${t === current ? 'on' : ''}">${t[0].toUpperCase() + t.slice(1)}</button>`).join('')}</div>`;
}

export async function render(root) {
  const [stats, courseMap] = await Promise.all([api.get('/api/progress'), api.get('/api/course')]);
  const s = stats.settings;
  app.settings = s;
  const target = s.target_level;
  const levels = stats.levels.filter(l => l.level <= target);
  const known = levels.reduce((a, l) => a + l.known, 0);
  const total = levels.reduce((a, l) => a + l.total, 0);
  const lesson = nextLesson(courseMap, target);
  const maxDay = Math.max(1, ...stats.activity.map(d => d.answers));
  const todo = stats.due_now + stats.new_left_today;
  const pct = v => (v == null ? '—' : Math.round(v * 100) + '%');

  root.innerHTML = `<div class="page">
    <div class="row between" style="align-items:flex-end">
      <div><h1>你好！<span class="muted" style="font-weight:400;font-size:18px"> (Nǐ hǎo!)</span></h1>
        <p class="sub" style="margin:0">Let's get you ready for the exam.</p></div>
      <div class="row"><span class="muted" style="font-size:13px">Preparing for</span>
        <div class="seg" id="target">${LEVELS.map(l => `<button data-level="${l}" class="${l === target ? 'on' : ''}">HSK ${l}</button>`).join('')}</div></div>
    </div>

    <a class="hero section" href="#/tutor" style="text-decoration:none;color:inherit">
      <span class="seal" style="width:56px;height:56px;font-size:30px;border-radius:14px">师</span>
      <div class="grow"><b style="font-size:18px">Learn with 王老师, your HSK tutor</b>
        <div class="muted" style="font-size:13.5px">Lessons step by step, questions that check your answers, and the textbook page behind every fact.</div></div>
      <span class="btn primary big">Start a lesson</span></a>

    <div class="hero section" style="background:var(--surface)">
      <div class="num">${todo}</div>
      <div class="grow">${todo
        ? `<b>${stats.due_now} card${stats.due_now === 1 ? '' : 's'} to review · ${stats.new_left_today} new word${stats.new_left_today === 1 ? '' : 's'} today</b>
           <div class="muted" style="font-size:13.5px">Spaced repetition brings each word back just before you'd forget it.</div>`
        : `<b>All caught up for today 🎉</b><div class="muted" style="font-size:13.5px">Try a drill, or study the next lesson with 王老师.</div>`}</div>
      <a class="btn big" href="${todo ? '#/review' : '#/practice'}">${todo ? 'Start review' : 'Practice'}</a>
    </div>

    <div class="grid cols-4 section">
      <div class="stat"><div class="v">🔥 ${stats.streak}</div><div class="k">day streak</div></div>
      <div class="stat"><div class="v">${known}<span class="muted" style="font-size:15px"> / ${total}</span></div><div class="k">HSK ${target === 1 ? '1' : '1–' + target} words known</div></div>
      <div class="stat"><div class="v">${pct(stats.accuracy_7d)}</div><div class="k">accuracy, last 7 days</div></div>
      <div class="stat"><div class="v">${stats.answers_today}</div><div class="k">answers today</div></div>
    </div>

    ${lesson ? `<div class="section"><h2>Continue the course</h2>
      <div class="card row between">
        <div style="min-width:0;flex:1">
          <div class="faint">HSK ${lesson.level} · Lesson ${lesson.number}</div>
          <div class="hz-font" style="font-size:22px;font-weight:600">${esc(lesson.title_zh)}</div>
          <div class="muted" style="font-size:13.5px">${esc(lesson.title_en)} · ${lesson.word_count} words · ${lesson.grammar.length} grammar points</div>
          <div style="margin-top:8px;max-width:340px">${masteryBar(lesson.mastery)}</div>
        </div>
        <div class="row">
          <button class="btn primary" id="studyLesson">Study with 王老师</button>
          <a class="btn" href="#/review?level=${lesson.level}&lesson=${lesson.number}">Learn words</a>
          <a class="btn" href="#/course/${lesson.level}/${lesson.number}">Open</a>
        </div>
      </div></div>` : ''}

    <div class="grid cols-2 section">
      <div class="card"><h2>Vocabulary by level</h2>
        ${stats.levels.map(l => `<div class="level-row"><b>HSK ${l.level}</b>${masteryBar({ ...l, new: l.new })}
          <span class="faint">${l.known}/${l.total}</span></div>`).join('')}
        <div class="legend" style="margin-top:8px"><span><i style="background:var(--st-mature)"></i>Mastered</span>
          <span><i style="background:var(--st-young)"></i>Known</span><span><i style="background:var(--st-learning)"></i>Learning</span></div>
      </div>
      <div class="card"><h2>Last 14 days</h2>
        <div class="activity">${stats.activity.map((d, i) => `<div class="col${i === 13 ? ' today' : ''}" title="${d.date}: ${d.answers} answers, ${d.correct} correct">
          <span style="height:${(100 * d.answers) / maxDay}%"></span></div>`).join('')}</div>
        <div class="row between faint" style="margin-top:6px"><span>2 weeks ago</span><span>today</span></div>
      </div>
    </div>

    <div class="section"><h2>Words to work on</h2>
      ${stats.weak_words.length ? `<div class="card">
        <div class="word-chips">${stats.weak_words.map(w => `<a class="word-chip" href="#/word/${encodeURIComponent(w.id)}" style="text-decoration:none;color:inherit">
          <b>${esc(w.hanzi)}</b><span class="pinyin">${esc(w.pinyin)}</span><span class="faint">✗${w.wrong}</span></a>`).join('')}</div>
        <div class="row" style="margin-top:14px"><button class="btn primary" id="reviewWeak">Review these with 王老师</button>
          <button class="btn" id="drillWeak">Drill these</button></div></div>`
        : '<div class="card flat muted">Words you miss in reviews and drills will collect here.</div>'}
    </div>

    <div class="section"><h2>Practice tests</h2><div class="card">
      ${stats.tests.length ? stats.tests.map(t => `<div class="row between" style="padding:6px 0;border-bottom:1px solid var(--border)">
        <span>HSK ${t.level} practice test</span><span class="faint">${new Date(t.ts * 1000).toLocaleDateString()}</span>
        <b>${t.score}/${t.total} · ${Math.round((100 * t.score) / t.total)}%</b></div>`).join('')
        : '<p class="muted" style="margin:0 0 10px">A timed, sectioned test built from your textbook’s words and sentences.</p>'}
      <a class="btn" style="margin-top:10px" href="#/practice?mode=test&level=${target}">Take an HSK ${target} practice test</a></div></div>

    <div class="section"><h2>Settings</h2><div class="card stack">
      <div class="row between"><span>New words per day</span>
        <input class="text" id="dailyNew" type="number" min="0" max="100" value="${s.daily_new}" style="width:90px"></div>
      <div class="row between"><span>Theme</span>${themeSeg()}</div>
      <div class="row between"><span>Tutor model</span><span class="muted">${app.status?.provider
        ? esc(app.status.provider + (app.status.model ? ' · ' + app.status.model : '')) : 'not configured (set HSK_AGENT_PROVIDER)'}</span></div>
      <div class="row between"><span>Erase all study progress</span><button class="btn small" id="reset">Reset progress…</button></div>
    </div></div>
  </div>`;

  root.querySelectorAll('#target button').forEach(b => b.addEventListener('click', async () => {
    await app.saveSettings({ target_level: +b.dataset.level });
    window.dispatchEvent(new Event('hsk:progress'));
    render(root);
  }));
  root.querySelector('#dailyNew').addEventListener('change', async e => {
    await app.saveSettings({ daily_new: Math.max(0, Math.min(100, +e.target.value || 0)) });
    toast('Saved.');
    window.dispatchEvent(new Event('hsk:progress'));
  });
  root.querySelectorAll('#theme button').forEach(b => b.addEventListener('click', () => {
    const t = b.dataset.theme;
    localStorage.setItem('hsk.theme', t);
    if (t === 'auto') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.dataset.theme = t;
    root.querySelectorAll('#theme button').forEach(x => x.classList.toggle('on', x === b));
  }));
  root.querySelector('#reset').addEventListener('click', async () => {
    if (!confirm('Erase all flashcard progress, answers and test results? This cannot be undone.')) return;
    await api.post('/api/progress/reset', { confirm: 'RESET' });
    toast('Progress erased.');
    window.dispatchEvent(new Event('hsk:progress'));
    render(root);
  });
  root.querySelector('#studyLesson')?.addEventListener('click', () => app.startTutor(
    { type: 'lesson', level: lesson.level, lesson: lesson.number },
    `Let's study HSK ${lesson.level} Lesson ${lesson.number} (${lesson.title_zh}). Teach it to me step by step, starting with the first text and its new words.`));
  const weakIds = stats.weak_words.map(w => w.id);
  root.querySelector('#reviewWeak')?.addEventListener('click', () => app.startTutor(
    { type: 'review', word_ids: weakIds },
    `Help me review the words I keep getting wrong: ${stats.weak_words.map(w => w.hanzi).join('、')}. Quiz me on them one at a time.`));
  root.querySelector('#drillWeak')?.addEventListener('click', () =>
    app.go(`#/practice?words=${encodeURIComponent(weakIds.join(','))}`));
}
