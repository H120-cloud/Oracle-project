export const BASE = '/api/v1';

export const DEFAULT_TIMEOUT_MS = 60_000;
export const ORACLE_FRONTEND_SESSION_TOKEN = 'ORACLE_FRONTEND_SESSION_TOKEN';

export function getFrontendSessionToken() {
  return sessionStorage.getItem(ORACLE_FRONTEND_SESSION_TOKEN);
}

export function setFrontendSessionToken(token) {
  sessionStorage.setItem(ORACLE_FRONTEND_SESSION_TOKEN, token);
}

export function clearFrontendSessionToken() {
  sessionStorage.removeItem(ORACLE_FRONTEND_SESSION_TOKEN);
}

// Shared 401 handling so every authed request path (fetchJSON, blob downloads)
// reacts to an expired/invalid token identically: drop the dead token and let
// the auth gate surface the "session expired" notice instead of failing silently.
export function handleAuthFailure(status, token) {
  if (status === 401 && token) {
    clearFrontendSessionToken();
    window.dispatchEvent(new CustomEvent('oracle-auth-expired'));
  }
}

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
    const token = getFrontendSessionToken();
    const headers = { 'Content-Type': 'application/json', ...rest.headers };
    if (token && !headers.Authorization) {
      headers.Authorization = `Bearer ${token}`;
    }

    const res = await fetch(url, {
      headers,
      ...rest,
      signal: controller.signal,
    });
    if (!res.ok) {
      handleAuthFailure(res.status, token);
      throw new Error(`${res.status} ${res.statusText}`);
    }
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
