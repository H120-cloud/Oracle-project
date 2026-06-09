// Admin Diagnostics API client (read-only).
import { fetchJSON, BASE, getFrontendSessionToken, handleAuthFailure } from './api_shared';

function qs(params) {
  const sp = new URLSearchParams();
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') sp.append(k, v);
  });
  const s = sp.toString();
  return s ? `?${s}` : '';
}

export const getNewsLatency = (p) => fetchJSON(`${BASE}/admin/news-latency${qs(p)}`);
export const getRocketShadow = (p) => fetchJSON(`${BASE}/admin/rocket-shadow${qs(p)}`);
export const getTelegramOutbox = (p) => fetchJSON(`${BASE}/admin/telegram-outbox${qs(p)}`);
export const getSourceHealth = (p) => fetchJSON(`${BASE}/admin/source-health${qs(p)}`);
export const getBlockedAlerts = (p) => fetchJSON(`${BASE}/admin/blocked-alerts${qs(p)}`);
export const getFastWatchAlerts = (p) => fetchJSON(`${BASE}/admin/fast-watch-alerts${qs(p)}`);
export const getReports = () => fetchJSON(`${BASE}/admin/reports`);

// Live scraper speed probe — runs the real fetches, can take up to ~timeout s.
export const getScraperSpeedTest = (timeout = 15) =>
  fetchJSON(`${BASE}/admin/scraper-speed-test?timeout=${timeout}`, { timeoutMs: (timeout + 10) * 1000 });

// URL builders for downloads.
export const dataDownloadUrl = (kind, fmt, params) =>
  `${BASE}/admin/download/${kind}${qs({ ...(params || {}), format: fmt })}`;
export const reportDownloadUrl = (name) =>
  `${BASE}/admin/download/report/${encodeURIComponent(name)}`;

// Authenticated file download (the bearer token must travel in a header, so a
// plain <a href> won't work). Fetches as a blob and triggers a browser save.
export async function downloadAdminFile(url, fallbackName) {
  const token = getFrontendSessionToken();
  const res = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    handleAuthFailure(res.status, token);
    throw new Error(`${res.status} ${res.statusText}`);
  }
  const blob = await res.blob();
  const cd = res.headers.get('Content-Disposition') || '';
  const m = /filename="?([^"]+)"?/.exec(cd);
  const name = (m && m[1]) || fallbackName || 'download';
  const objUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = objUrl;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(objUrl);
}
