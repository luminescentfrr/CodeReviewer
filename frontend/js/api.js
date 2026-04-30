// api.js — API communication layer for CodeReview AI frontend
// Exposes: API_BASE, streamWithRetry(), healthCheck()

let API_BASE = 'http://127.0.0.1:8765';

function setApiBase(url) { API_BASE = url; }
function getApiBase() { return API_BASE; }

async function healthCheck() {
  try {
    const r = await fetch(`${API_BASE}/api/health`);
    return await r.json();
  } catch (e) {
    return { status: 'error', error: e.message };
  }
}

async function streamWithRetry(url, body, onEvent, maxRetries = 3) {
  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 300_000);
      const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      clearTimeout(timeout);

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const event = JSON.parse(line.slice(6));
              onEvent(event);
            } catch (e) {
              console.warn('SSE parse error:', e, line);
            }
          }
        }
      }
      return;
    } catch (e) {
      if (attempt < maxRetries - 1) {
        await new Promise(r => setTimeout(r, Math.pow(2, attempt) * 1000));
      } else if (typeof onError === 'function') {
        onError(e);
      }
    }
  }
}
