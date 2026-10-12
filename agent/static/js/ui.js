// Shared UI pieces: escaping, markdown, clickable textbook words and citations,
// the word popover, the textbook-page viewer, speech, toasts.

import { api } from './api.js';
import { app, wordBasics } from './state.js';

export const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function el(html) {
  const t = document.createElement('template');
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

// ---------------------------------------------------------------- toast
let toastTimer;
export function toast(msg, ms = 2600) {
  document.querySelector('.toast')?.remove();
  const t = el(`<div class="toast" role="status">${esc(msg)}</div>`);
  document.body.appendChild(t);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.remove(), ms);
}

// ---------------------------------------------------------------- speech
let warnedNoVoice = false;
function chineseVoice() {
  const voices = window.speechSynthesis?.getVoices() || [];
  return voices.find(v => /zh[-_]CN/i.test(v.lang)) || voices.find(v => /^zh/i.test(v.lang)) || null;
}
if (window.speechSynthesis) speechSynthesis.onvoiceschanged = () => chineseVoice();

/** Read Chinese aloud with the device's own voice (pinyin shown in the app is the textbook's). */
export function speak(text, rate = 0.85) {
  if (!window.speechSynthesis) { toast('Audio isn’t supported in this browser.'); return; }
  const voice = chineseVoice();
  if (!voice && !warnedNoVoice) {
    warnedNoVoice = true;
    toast('No Chinese voice found on this device — install one in your OS language settings for better audio.', 5000);
  }
  const u = new SpeechSynthesisUtterance(text);
  u.lang = 'zh-CN';
  if (voice) u.voice = voice;
  u.rate = rate;
  speechSynthesis.cancel();
  speechSynthesis.speak(u);
}
export const speakBtn = (text, small = false) =>
  `<button class="speak${small ? ' small' : ''}" data-speak="${esc(text)}" title="Listen" aria-label="Listen">🔊</button>`;

// ---------------------------------------------------------------- status pills & bars
const STATUS_LABEL = { new: 'New', learning: 'Learning', young: 'Known', mature: 'Mastered' };
export const statusPill = s => `<span class="pill ${esc(s)}">${STATUS_LABEL[s] || esc(s)}</span>`;
export function masteryBar(m) {
  const pct = n => (m.total ? (100 * n) / m.total : 0);
  return `<div class="bar" title="${m.mature} mastered · ${m.young} known · ${m.learning} learning · ${m.new} new">` +
    `<span class="s-mature" style="width:${pct(m.mature)}%"></span><span class="s-young" style="width:${pct(m.young)}%"></span>` +
    `<span class="s-learning" style="width:${pct(m.learning)}%"></span></div>`;
}
export const citeBtn = (level, page) =>
  `<button class="cite" data-level="${level}" data-page="${page}" title="Open this textbook page">📖 HSK ${level} · p.${page}</button>`;

// ---------------------------------------------------------------- textbook words in text
const CJK_RUN = /[一-鿿]+/g;

function segmentRun(run) {
  const forms = app.lexicon?.forms;
  if (!forms) return esc(run);
  let out = '';
  let i = 0;
  while (i < run.length) {
    let hit = '';
    for (let size = Math.min(app.maxForm, run.length - i); size > 0; size--) {
      const chunk = run.slice(i, i + size);
      if (forms[chunk]) { hit = chunk; break; }
    }
    if (hit) {
      out += `<span class="hz" role="button" tabindex="0" data-ids="${forms[hit].join(' ')}">${hit}</span>`;
      i += hit.length;
    } else {
      out += run[i++];
    }
  }
  return out;
}

/** Make Chinese words that are in the textbooks' word lists clickable (HTML in, HTML out; skips tags and <code>). */
export function linkifyHanzi(html) {
  let inCode = 0;
  return html.split(/(<[^>]+>)/).map(part => {
    if (part.startsWith('<')) {
      if (/^<(code|pre)\b/i.test(part)) inCode++;
      else if (/^<\/(code|pre)>/i.test(part)) inCode = Math.max(0, inCode - 1);
      return part;
    }
    return inCode ? part : part.replace(CJK_RUN, segmentRun);
  }).join('');
}

/** Turn "(HSK Level 2, page 47)" citations into buttons that open the page. */
export const linkifyCitations = html =>
  html.replace(/\(HSK Level ([123]), page (\d+)\)/g, (_, l, p) => citeBtn(l, p));

/** Plain text, escaped, with textbook words made clickable (no paragraph wrapping). */
export const rich = text => linkifyHanzi(esc(text));

// ---------------------------------------------------------------- markdown
function inline(text) {
  const codes = [];
  let s = esc(text).replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
  s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*\w])\*([^*\n]+?)\*(?!\w)/g, '$1<em>$2</em>')
    .replace(/(^|\W)_([^_\n]+?)_(?!\w)/g, '$1<em>$2</em>');
  s = s.replace(/🧑‍🏫?\s*Teacher'?s note \(not from the textbook\)/gi, m => `<span class="teacher-note">${m}</span>`);
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[+i]}</code>`);
}

const BLOCK_START = /^(\s*$|#{1,6}\s|```|>\s?|\s*([-*•]|\d+[.)])\s+|\s*\|.*\|\s*$)/;

/** Render the tutor's markdown safely (everything is escaped first; no raw HTML or links). */
export function renderMarkdown(src, { links = true } = {}) {
  const lines = String(src || '').replace(/\r\n/g, '\n').split('\n');
  let html = '';
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (/^\s*$/.test(line)) { i++; continue; }
    if (/^```/.test(line)) {
      const buf = [];
      for (i++; i < lines.length && !/^```/.test(lines[i]); i++) buf.push(lines[i]);
      i++;
      html += `<pre><code>${esc(buf.join('\n'))}</code></pre>`;
      continue;
    }
    let m = line.match(/^(#{1,6})\s+(.*)$/);
    if (m) { const n = Math.min(m[1].length + 2, 6); html += `<h${n}>${inline(m[2])}</h${n}>`; i++; continue; }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { html += '<hr>'; i++; continue; }
    if (/^\s*\|.*\|\s*$/.test(line) && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1] || '')) {
      const cells = l => l.trim().replace(/^\||\|$/g, '').split('|').map(c => inline(c.trim()));
      html += '<table><thead><tr>' + cells(line).map(c => `<th>${c}</th>`).join('') + '</tr></thead><tbody>';
      for (i += 2; i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i]); i++) {
        html += '<tr>' + cells(lines[i]).map(c => `<td>${c}</td>`).join('') + '</tr>';
      }
      html += '</tbody></table>';
      continue;
    }
    if (/^\s*>/.test(line)) {
      const buf = [];
      for (; i < lines.length && /^\s*>/.test(lines[i]); i++) buf.push(lines[i].replace(/^\s*>\s?/, ''));
      html += `<blockquote>${renderMarkdown(buf.join('\n'), { links: false })}</blockquote>`;
      continue;
    }
    m = line.match(/^\s*([-*•]|\d+[.)])\s+/);
    if (m) {
      const ordered = /\d/.test(m[1]);
      const items = [];
      while (i < lines.length) {
        const mm = lines[i].match(/^\s*([-*•]|\d+[.)])\s+(.*)$/);
        if (mm) { items.push(mm[2]); i++; continue; }
        if (items.length && /^\s{2,}\S/.test(lines[i])) { items[items.length - 1] += ' ' + lines[i].trim(); i++; continue; }
        break;
      }
      const tag = ordered ? 'ol' : 'ul';
      html += `<${tag}>` + items.map(t => `<li>${inline(t)}</li>`).join('') + `</${tag}>`;
      continue;
    }
    const para = [];
    for (; i < lines.length && !(para.length && BLOCK_START.test(lines[i])); i++) para.push(lines[i]);
    html += `<p>${para.map(inline).join('<br>')}</p>`;
  }
  return links ? linkifyHanzi(linkifyCitations(html)) : html;
}

// ---------------------------------------------------------------- word popover
let popover = null;
export function closePopover() { popover?.remove(); popover = null; }

function showWordPopover(target) {
  closePopover();
  const entries = (target.dataset.ids || '').split(' ').map(wordBasics).filter(Boolean);
  if (!entries.length) return;
  popover = el(`<div class="popover" role="dialog" aria-label="Word">${entries.slice(0, 3).map(w => `
    <div class="entry">
      <div class="row between"><div><span class="hz-big">${esc(w.hanzi)}</span> <span class="pinyin">${esc(w.pinyin)}</span></div>
        ${speakBtn(w.hanzi.replace(/[（(][^）)]*[）)]/g, ''), true)}</div>
      <div style="margin:4px 0 8px"><span class="faint">${esc(w.pos)}</span> ${esc(w.meaning)}</div>
      <div class="row between"><span class="pill level">HSK ${w.level}${w.lesson ? ' · L' + w.lesson : ''}</span>
        <span class="row" style="gap:6px">
          <button class="btn small" data-add="${esc(w.id)}">+ Flashcards</button>
          <a class="btn small" href="#/word/${encodeURIComponent(w.id)}">Details</a></span></div>
    </div>`).join('')}
    <div class="faint" style="margin-top:8px">From the textbook's word list.</div></div>`);
  document.body.appendChild(popover);
  const r = target.getBoundingClientRect();
  const left = Math.min(window.scrollX + r.left, window.scrollX + document.documentElement.clientWidth - popover.offsetWidth - 12);
  const below = r.bottom + popover.offsetHeight + 12 < window.innerHeight;
  popover.style.left = Math.max(12, left) + 'px';
  popover.style.top = (below ? window.scrollY + r.bottom + 6 : window.scrollY + r.top - popover.offsetHeight - 6) + 'px';
}

// ---------------------------------------------------------------- textbook page viewer
export async function openPage(level, page) {
  closePopover();
  const back = el(`<div class="modal-back"><div class="modal" role="dialog" aria-modal="true">
    <header><h2>HSK ${level} · page ${page}</h2><div class="seg"><button class="on" data-tab="scan">Scan</button>
      <button data-tab="text">Transcript</button></div><button class="icon-btn" data-close aria-label="Close">✕</button></header>
    <div class="body"><div class="muted">Loading…</div></div></div></div>`);
  document.body.appendChild(back);
  const close = () => { back.remove(); document.removeEventListener('keydown', onKey); };
  const onKey = e => { if (e.key === 'Escape') close(); };
  document.addEventListener('keydown', onKey);
  back.addEventListener('click', e => { if (e.target === back || e.target.closest('[data-close]')) close(); });
  const body = back.querySelector('.body');
  try {
    const p = await api.get(`/api/page/${level}/${page}`);
    const lesson = p.lesson ? `Lesson ${p.lesson.number} · ${esc(p.lesson.title_zh)} (${esc(p.lesson.title_en)}) · ` : '';
    const head = `<p class="faint" style="margin:0 0 10px">${lesson}printed page ${p.printed_page} · PDF page ${p.page}</p>`;
    const scan = p.image_url ? `<img class="scan" src="${p.image_url}" alt="Scan of HSK ${level} page ${page}">`
      : '<div class="callout info">No scanned image available for this page.</div>';
    const text = `<pre class="transcript">${esc(p.transcript)}</pre>`;
    body.innerHTML = head + scan;
    back.querySelectorAll('[data-tab]').forEach(b => b.addEventListener('click', () => {
      back.querySelectorAll('[data-tab]').forEach(x => x.classList.toggle('on', x === b));
      body.innerHTML = head + (b.dataset.tab === 'scan' ? scan : text);
    }));
  } catch (err) {
    body.innerHTML = `<div class="callout error">${esc(err.message)}</div>`;
  }
}

// ---------------------------------------------------------------- global delegation
export function initUI() {
  document.addEventListener('click', async e => {
    const t = e.target;
    const speakEl = t.closest('[data-speak]');
    if (speakEl) { e.preventDefault(); speak(speakEl.dataset.speak); return; }
    const cite = t.closest('.cite[data-page]');
    if (cite) { e.preventDefault(); openPage(cite.dataset.level, cite.dataset.page); return; }
    const add = t.closest('[data-add]');
    if (add) {
      e.preventDefault();
      try { await api.post('/api/review/add', { word_id: add.dataset.add }); toast('Added to your flashcards.'); add.disabled = true; }
      catch (err) { toast(err.message); }
      return;
    }
    const hz = t.closest('.hz[data-ids]');
    if (hz) { e.preventDefault(); showWordPopover(hz); return; }
    if (popover && !t.closest('.popover')) closePopover();
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closePopover();
    const hz = e.target.closest?.('.hz[data-ids]');
    if (hz && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); showWordPopover(hz); }
  });
  window.addEventListener('hashchange', closePopover);
}
