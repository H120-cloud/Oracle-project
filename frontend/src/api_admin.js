// Admin Diagnostics API client (read-only).
import { fetchJSON, BASE } from './api_shared';

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
