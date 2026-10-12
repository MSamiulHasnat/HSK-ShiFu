// Shared app state and navigation, imported by every view (kept separate from
// app.js so views don't import the router that imports them).

import { api } from './api.js';

export const app = {
  lexicon: null,      // { forms: {written form: [word ids]}, words: {id: [hanzi, pinyin, meaning, level, lesson, pos]} }
  maxForm: 1,
  status: null,       // { provider, model, tutor_available }
  settings: { target_level: 1, daily_new: 15 },
  pendingTutor: null, // { focus, message } handed to the tutor view on navigation

  go(hash) {
    if (location.hash === hash) window.dispatchEvent(new HashChangeEvent('hashchange'));
    else location.hash = hash;
  },

  /** Open the tutor and start a new conversation about `focus` with `message`. */
  startTutor(focus, message) {
    app.pendingTutor = { focus, message };
    app.go('#/tutor');
  },

  async loadSettings() {
    try { app.settings = await api.get('/api/settings'); } catch { /* keep defaults */ }
    return app.settings;
  },

  async saveSettings(changes) {
    app.settings = await api.post('/api/settings', changes);
    return app.settings;
  },
};

export const LEVELS = [1, 2, 3];

export function wordBasics(id) {
  const w = app.lexicon?.words[id];
  if (!w) return null;
  const [hanzi, pinyin, meaning, level, lesson, pos] = w;
  return { id, hanzi, pinyin, meaning, level, lesson, pos };
}

export function fmtInterval(seconds) {
  if (seconds < 60) return '<1m';
  if (seconds < 3600) return Math.round(seconds / 60) + 'm';
  if (seconds < 86400) return Math.round(seconds / 3600) + 'h';
  const days = seconds / 86400;
  if (days < 30) return Math.round(days) + 'd';
  if (days < 365) return (days / 30).toFixed(days < 60 ? 1 : 0) + 'mo';
  return (days / 365).toFixed(1) + 'y';
}

export function fmtAgo(ts) {
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return 'just now';
  if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
  if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
  if (diff < 86400 * 7) return Math.floor(diff / 86400) + 'd ago';
  return new Date(ts * 1000).toLocaleDateString();
}
