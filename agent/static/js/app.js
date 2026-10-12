// Router and app start-up. Each view module exports render(root, ctx) and may
// return a cleanup function, called when the student navigates away.

import { api } from './api.js';
import { app } from './state.js';
import { initUI, closePopover, esc } from './ui.js';
import * as today from './views/today.js';
import * as tutor from './views/tutor.js';
import * as course from './views/course.js';
import * as review from './views/review.js';
import * as practice from './views/practice.js';
import * as dictionary from './views/dictionary.js';

const ROUTES = { today, tutor, course, review, practice, dictionary, word: dictionary };
const main = document.getElementById('main');
let cleanup = null;
let renderId = 0;

function parseHash() {
  const [path, qs] = (location.hash.replace(/^#\/?/, '') || 'tutor').split('?');
  const [name, ...params] = path.split('/').map(decodeURIComponent);
  return { name: ROUTES[name] ? name : 'tutor', params, query: Object.fromEntries(new URLSearchParams(qs || '')) };
}

async function render() {
  const id = ++renderId;
  const { name, params, query } = parseHash();
  try { cleanup?.(); } catch { /* a view's cleanup must never block navigation */ }
  cleanup = null;
  closePopover();
  document.querySelectorAll('.nav a.item').forEach(a => a.classList.toggle('active', a.dataset.route === (name === 'word' ? 'dictionary' : name)));
  main.innerHTML = '';
  const root = document.createElement('div');
  main.appendChild(root);
  window.scrollTo(0, 0);
  try {
    const result = await ROUTES[name].render(root, { name, params, query });
    if (id === renderId) cleanup = typeof result === 'function' ? result : null;
    else if (typeof result === 'function') result();
  } catch (err) {
    root.innerHTML = `<div class="page"><div class="callout error">Something went wrong loading this page: ${esc(err.message || err)}</div></div>`;
    console.error(err);
  }
}

export async function refreshDueBadge() {
  try {
    const q = await api.get('/api/review/queue?limit=1');
    const n = q.counts.learning + q.counts.review + q.counts.new;
    const badge = document.getElementById('dueBadge');
    badge.textContent = n;
    badge.hidden = n === 0;
  } catch { /* badge is decoration */ }
}
window.addEventListener('hsk:progress', refreshDueBadge);

async function start() {
  const theme = localStorage.getItem('hsk.theme');
  if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
  initUI();
  const [lexicon, status] = await Promise.all([
    api.get('/api/lexicon').catch(() => null),
    api.get('/api/status').catch(() => null),
    app.loadSettings(),
  ]);
  if (lexicon) {
    app.lexicon = lexicon;
    app.maxForm = Math.max(1, ...Object.keys(lexicon.forms).map(f => f.length));
  }
  app.status = status;
  window.addEventListener('hashchange', render);
  render();
  refreshDueBadge();
}

start();
