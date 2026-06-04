export const BASE = '/api/v1';

export const DEFAULT_TIMEOUT_MS = 60_000;

export async function fetchJSON(url, options = {}) {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, signal: externalSignal, ...rest } = options;
  const controller = new AbortController();
  const timer = timeoutMs > 0
    ? setTimeout(() => controller.abort(new DOMException('Request timed out', 'TimeoutError')), timeoutMs)
    : null;

  if (externalSignal) {
    if (externalSignal.aborted) controller.abort(externalSignal.reason);
    else externalSignal.addEventListener('abort', () => controller.abort(externalSignal.reason), { once: true });
  }

  try {
    const res = await fetch(url, {
      headers: { 'Content-Type': 'application/json', ...rest.headers },
      ...rest,
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.json();
  } catch (err) {
    if (err.name === 'AbortError' || err.name === 'TimeoutError') {
      throw new Error(`Request timed out after ${timeoutMs / 1000}s`);
    }
    throw err;
  } finally {
    if (timer) clearTimeout(timer);
  }
}

export const getHealth = () => fetchJSON('/health');
