// Thin client for the HSK ShiFu server (agent/server.py + agent/api_study.py).

async function request(method, path, body) {
  const resp = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map(d => d.msg).join('; ') : data.detail;
    throw new Error(detail || `${resp.status} ${resp.statusText}`);
  }
  return data;
}

export const api = {
  get: path => request('GET', path),
  post: (path, body) => request('POST', path, body || {}),
  word: id => request('GET', '/api/words/' + encodeURIComponent(id)),
};

/**
 * POST /chat/stream and dispatch its Server-Sent Events to handlers:
 * { meta, thinking, delta, done, error }. Resolves when the stream ends.
 */
export async function streamChat(body, handlers, signal) {
  const resp = await fetch('/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
  if (!resp.ok || !resp.body) {
    const data = await resp.json().catch(() => ({}));
    throw new Error(data.detail || `${resp.status} ${resp.statusText}`);
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut;
    while ((cut = buffer.indexOf('\n\n')) !== -1) {
      const raw = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      let event = 'message';
      let data = '';
      for (const line of raw.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) data += line.slice(5).trim();
      }
      if (data && handlers[event]) handlers[event](JSON.parse(data));
    }
  }
}
