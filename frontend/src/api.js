const BASE = '/api/v1';

async function fetchJSON(url, options = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

// Signals
export const getSignals = (scanType = 'volume') =>
  fetchJSON(`${BASE}/signals/generate?scan_type=${scanType}`, { method: 'POST', body: '{}' });

export const analyzeSignal = (ticker) =>
  fetchJSON(`${BASE}/signals/${ticker}`);

export const recordOutcome = (signalId, outcome, pnlPercent = 0) =>
  fetchJSON(`${BASE}/signals/outcome`, {
    method: 'POST',
    body: JSON.stringify({ signal_id: signalId, outcome, pnl_percent: pnlPercent })
  });

// Analysis (V3)
export const getVolumeProfile = (ticker) =>
  fetchJSON(`${BASE}/analysis/volume-profile/${ticker}`);

export const getRegime = (ticker) =>
  fetchJSON(`${BASE}/analysis/regime/${ticker}`);

export const getStage = (ticker) =>
  fetchJSON(`${BASE}/analysis/stage/${ticker}`);

export const getSegment = (ticker) =>
  fetchJSON(`${BASE}/analysis/segment/${ticker}`);

export const getCompleteAnalysis = (ticker) =>
  fetchJSON(`${BASE}/analysis/complete/${ticker}`);

export const getLiveQuote = (ticker) =>
  fetchJSON(`${BASE}/analysis/live-quote/${ticker}`);

export const getFinvizNews = () =>
  fetchJSON(`${BASE}/news/finviz`);

export const getBearishAnalysis = (ticker) =>
  fetchJSON(`${BASE}/analysis/bearish/${ticker}`);

// Order Flow (V4)
export const getOrderFlow = (ticker) =>
  fetchJSON(`${BASE}/order-flow/${ticker}`);

// Backtest (V4)
export const runBacktest = (config) =>
  fetchJSON(`${BASE}/backtest`, { method: 'POST', body: JSON.stringify(config) });

// Performance (V4)
export const getPerformance = (lastN = 100) =>
  fetchJSON(`${BASE}/performance?last_n=${lastN}`);

export const getAdjustments = () =>
  fetchJSON(`${BASE}/performance/adjustments`);

// Models (V2)
export const getModelStatus = () =>
  fetchJSON(`${BASE}/models/status`);

export const trainModels = () =>
  fetchJSON(`${BASE}/models/train`, { method: 'POST' });

// Discovery Engine
export const discoverTickers = (sources = 'finviz_gainers,finviz_active,news', maxTotal = 80) =>
  fetchJSON(`${BASE}/scanner/discover?sources=${sources}&max_total=${maxTotal}`);

// Watchlist — CRUD
export const getWatchlist = (includeArchived = false) =>
  fetchJSON(`${BASE}/watchlist/?include_archived=${includeArchived}`);

export const addToWatchlist = (data) =>
  fetchJSON(`${BASE}/watchlist/`, { method: 'POST', body: JSON.stringify(data) });

export const getWatchlistDetail = (ticker) =>
  fetchJSON(`${BASE}/watchlist/${ticker}`);

export const updateWatchlistItem = (ticker, data) =>
  fetchJSON(`${BASE}/watchlist/${ticker}`, { method: 'PUT', body: JSON.stringify(data) });

export const removeFromWatchlist = (ticker) =>
  fetchJSON(`${BASE}/watchlist/${ticker}`, { method: 'DELETE' });

export const archiveWatchlistItem = (ticker, reason = 'manual') =>
  fetchJSON(`${BASE}/watchlist/${ticker}/archive?reason=${reason}`, { method: 'POST' });

export const restoreWatchlistItem = (ticker) =>
  fetchJSON(`${BASE}/watchlist/${ticker}/restore`, { method: 'POST' });

// Watchlist — Alerts
export const getWatchlistAlerts = () =>
  fetchJSON(`${BASE}/watchlist/alerts/all`);

export const getTickerAlerts = (ticker) =>
  fetchJSON(`${BASE}/watchlist/${ticker}/alerts`);

export const markAlertRead = (alertId) =>
  fetchJSON(`${BASE}/watchlist/alerts/${alertId}/read`, { method: 'POST' });

// Watchlist — Timeline
export const getTickerTimeline = (ticker) =>
  fetchJSON(`${BASE}/watchlist/${ticker}/timeline`);

// Watchlist — Refresh
export const refreshWatchlist = () =>
  fetchJSON(`${BASE}/watchlist/refresh`, { method: 'POST' });

export const refreshWatchlistItem = (ticker) =>
  fetchJSON(`${BASE}/watchlist/${ticker}/refresh`, { method: 'POST' });

// Watchlist — Custom Price Alerts
export const getCustomAlerts = (ticker) =>
  fetchJSON(`${BASE}/watchlist/${ticker}/alerts/custom`);

export const createCustomAlert = (ticker, data) =>
  fetchJSON(`${BASE}/watchlist/${ticker}/alerts/custom`, { method: 'POST', body: JSON.stringify(data) });

export const deleteCustomAlert = (alertId) =>
  fetchJSON(`${BASE}/watchlist/alerts/custom/${alertId}`, { method: 'DELETE' });

export const getAllActiveAlerts = () =>
  fetchJSON(`${BASE}/watchlist/alerts/custom/all`);

// Watchlist — Earnings Calendar
export const getTickerEarnings = (ticker) =>
  fetchJSON(`${BASE}/watchlist/${ticker}/earnings`);

export const refreshEarningsCalendar = () =>
  fetchJSON(`${BASE}/watchlist/refresh-earnings`, { method: 'POST' });

export const checkEarningsWarnings = () =>
  fetchJSON(`${BASE}/watchlist/check-earnings-warnings`, { method: 'POST' });

// Watchlist — News Feed
export const getTickerNews = (ticker, limit = 10) =>
  fetchJSON(`${BASE}/watchlist/${ticker}/news?limit=${limit}`);

// Intelligence Engine
export const analyzeIntelligence = (ticker) =>
  fetchJSON(`${BASE}/intelligence/analyze/${ticker}`, { method: 'POST' });

export const analyzeBatchIntelligence = (tickers) =>
  fetchJSON(`${BASE}/intelligence/analyze-batch`, {
    method: 'POST', body: JSON.stringify({ tickers })
  });

export const getMarketContext = (refresh = false) =>
  fetchJSON(`${BASE}/intelligence/market-context?refresh=${refresh}`);

export const getActiveTrades = () =>
  fetchJSON(`${BASE}/intelligence/active-trades`);

export const startTradeTracking = (data) =>
  fetchJSON(`${BASE}/intelligence/track`, {
    method: 'POST', body: JSON.stringify(data)
  });

export const updateTradeTracking = (ticker, currentPrice) =>
  fetchJSON(`${BASE}/intelligence/track/${ticker}/update`, {
    method: 'POST', body: JSON.stringify({ current_price: currentPrice })
  });

export const closeTradeTracking = (ticker, exitPrice) =>
  fetchJSON(`${BASE}/intelligence/track/${ticker}/close`, {
    method: 'POST', body: JSON.stringify({ exit_price: exitPrice })
  });

export const getLearningWeights = () =>
  fetchJSON(`${BASE}/intelligence/learning/weights`);

export const computeLearningAdjustments = () =>
  fetchJSON(`${BASE}/intelligence/learning/adjust`, { method: 'POST' });

// Trading 212 Discovery
export const discoverTrading212 = (type = 'movers', maxTotal = 20) =>
  fetchJSON(`${BASE}/scanner/discover/trading212?type=${type}&max_total=${maxTotal}`);

// Health
export const getHealth = () => fetchJSON('/health');
