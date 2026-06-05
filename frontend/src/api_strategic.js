import { BASE, fetchJSON } from './api_shared';

export const requestFrontendAuthCode = () =>
  fetchJSON(`${BASE}/auth/request-code`, { method: 'POST' });

export const verifyFrontendAuthCode = (code) =>
  fetchJSON(`${BASE}/auth/verify-code`, {
    method: 'POST',
    body: JSON.stringify({ code }),
  });

export const getFrontendAuthSession = () =>
  fetchJSON(`${BASE}/auth/session`);

export const getFinvizNews = ({ forceRefresh = false } = {}) =>
  fetchJSON(`${BASE}/news/finviz${forceRefresh ? '?force_refresh=true' : ''}`);

export const getStockTitanNews = ({ forceRefresh = false } = {}) =>
  fetchJSON(`${BASE}/news/stocktitan${forceRefresh ? '?force_refresh=true' : ''}`);

export const getAllNews = ({ forceRefresh = false } = {}) =>
  fetchJSON(`${BASE}/news/all${forceRefresh ? '?force_refresh=true' : ''}`);

export const getLiveQuote = (ticker) =>
  fetchJSON(`${BASE}/news/quote/${ticker}`);

export const agenticScan = () =>
  fetchJSON(`${BASE}/agentic/scan`, { method: 'POST' });

export const agenticRefreshAll = () =>
  fetchJSON(`${BASE}/agentic/refresh`, { method: 'POST' });

export const agenticCandidates = (activeOnly = true, minProbability = 0, state = '') =>
  fetchJSON(`${BASE}/agentic/candidates?active_only=${activeOnly}&min_probability=${minProbability}${state ? `&state=${state}` : ''}`);

export const agenticCandidateDetail = (ticker) =>
  fetchJSON(`${BASE}/agentic/candidates/${ticker}`);

export const agenticRefreshCandidate = (ticker) =>
  fetchJSON(`${BASE}/agentic/candidates/${ticker}/refresh`, { method: 'POST' });

export const agenticDeactivate = (ticker) =>
  fetchJSON(`${BASE}/agentic/candidates/${ticker}/deactivate`, { method: 'POST' });

export const agenticAlerts = (limit = 50) =>
  fetchJSON(`${BASE}/agentic/alerts?limit=${limit}`);

export const agenticStatus = () =>
  fetchJSON(`${BASE}/agentic/status`);

export const agenticLearningStats = () =>
  fetchJSON(`${BASE}/agentic/learning/stats`);

export const qualitySeparatorStatus = () =>
  fetchJSON(`${BASE}/agentic/quality-separator/status`);

export const qualitySeparatorProfiles = () =>
  fetchJSON(`${BASE}/agentic/quality-separator/profiles`);

export const qualitySeparatorEvaluate = (ticker) =>
  fetchJSON(`${BASE}/agentic/quality-separator/evaluate`, {
    method: 'POST',
    body: JSON.stringify({ ticker })
  });

export const qualitySeparatorReport = () =>
  fetchJSON(`${BASE}/agentic/quality-separator/report`);

export const agenticRecordOutcome = (ticker, peakPrice, exitPrice) =>
  fetchJSON(`${BASE}/agentic/learning/record-outcome`, {
    method: 'POST',
    body: JSON.stringify({ ticker, peak_price: peakPrice, exit_price: exitPrice }),
  });

export const agenticApplyWeights = () =>
  fetchJSON(`${BASE}/agentic/learning/apply-suggested-weights`, { method: 'POST' });

export const agenticRollbackWeights = () =>
  fetchJSON(`${BASE}/agentic/learning/rollback-weights`, { method: 'POST' });

export const agenticMissedOpportunities = () =>
  fetchJSON(`${BASE}/agentic/missed-opportunities`, { method: 'POST' });

export const mlTrain = () =>
  fetchJSON(`${BASE}/agentic/ml/train`, { method: 'POST' });

export const mlStatus = () =>
  fetchJSON(`${BASE}/agentic/ml/status`);

export const mlApprove = (version, approvedBy) =>
  fetchJSON(`${BASE}/agentic/ml/approve`, {
    method: 'POST',
    body: JSON.stringify({ version, approved_by: approvedBy })
  });

export const mlDrift = () =>
  fetchJSON(`${BASE}/agentic/ml/drift`);

export const mlPredict = (ticker) =>
  fetchJSON(`${BASE}/agentic/ml/predict/${ticker}`);

export const newsImpactCandidates = (minScore = 0, decision = '') => {
  const qs = new URLSearchParams();
  if (minScore) qs.append('min_score', String(minScore));
  if (decision) qs.append('decision', decision);
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return fetchJSON(`${BASE}/agentic/news-impact/candidates${suffix}`);
};

export const newsImpactDetail = (ticker) =>
  fetchJSON(`${BASE}/agentic/news-impact/${ticker}`);

export const newsImpactEvaluate = (payload) =>
  fetchJSON(`${BASE}/agentic/news-impact/evaluate`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });

export const newsImpactLearningSummary = () =>
  fetchJSON(`${BASE}/agentic/news-impact/learning/summary`);

export const newsImpactLearningRecommendations = () =>
  fetchJSON(`${BASE}/agentic/news-impact/learning/recommendations`);

export const preNewsScan = () =>
  fetchJSON(`${BASE}/agentic/pre-news/scan`, { method: 'POST' });

export const preNewsAnomalies = (minScore = 0, activeOnly = true) =>
  fetchJSON(`${BASE}/agentic/pre-news/anomalies?min_score=${minScore}&active_only=${activeOnly}`);

export const preNewsDetail = (ticker) =>
  fetchJSON(`${BASE}/agentic/pre-news/${ticker}`);

export const preNewsLearning = () =>
  fetchJSON(`${BASE}/agentic/pre-news/learning`);

export const preNewsMissedReview = () =>
  fetchJSON(`${BASE}/agentic/pre-news/missed-review`, { method: 'POST' });

export const preNewsEvaluation = (params = {}) => {
  const qs = new URLSearchParams();
  if (params.date_from) qs.append('date_from', params.date_from);
  if (params.date_to) qs.append('date_to', params.date_to);
  if (params.ticker) qs.append('ticker', params.ticker);
  if (params.anomaly_type) qs.append('anomaly_type', params.anomaly_type);
  if (params.alert_quality) qs.append('alert_quality', params.alert_quality);
  if (params.min_score != null) qs.append('min_score', params.min_score);
  if (params.outcome_label) qs.append('outcome_label', params.outcome_label);
  qs.append('include_unresolved', params.include_unresolved !== false ? 'true' : 'false');
  return fetchJSON(`${BASE}/agentic/pre-news/evaluation?${qs.toString()}`);
};

export const preNewsExportEvaluation = (date) =>
  fetchJSON(`${BASE}/agentic/pre-news/evaluation/export/${date}`, { method: 'POST' });

export const preNewsExportList = () =>
  fetchJSON(`${BASE}/agentic/pre-news/evaluation/exports`);

export const preNewsAnalyze = () =>
  fetchJSON(`${BASE}/agentic/pre-news/evaluation/analyze`, { method: 'POST' });

export const preNewsReport = () =>
  fetchJSON(`${BASE}/agentic/pre-news/evaluation/report`);

export const preNewsReportMarkdown = () =>
  fetchJSON(`${BASE}/agentic/pre-news/evaluation/report/markdown`);

export const preNewsBaselines = (params = {}) => {
  const qs = new URLSearchParams();
  if (params.baseline_type) qs.append('baseline_type', params.baseline_type);
  if (params.ticker) qs.append('ticker', params.ticker);
  if (params.session_date) qs.append('session_date', params.session_date);
  if (params.limit) qs.append('limit', String(params.limit));
  return fetchJSON(`${BASE}/agentic/pre-news/baselines?${qs.toString()}`);
};

export const preNewsBaselinesSummary = () =>
  fetchJSON(`${BASE}/agentic/pre-news/baselines/summary`);

export const preNewsBaselinesExport = (sessionDate) =>
  fetchJSON(`${BASE}/agentic/pre-news/baselines/export/${sessionDate}`, { method: 'POST' });

export const historicalTrainingRun = (mode = 'recommend_only', approvedFeatures = []) =>
  fetchJSON(`${BASE}/agentic/training/historical/run`, {
    method: 'POST',
    body: JSON.stringify({ mode, approved_features: approvedFeatures })
  });

export const historicalTrainingStatus = () =>
  fetchJSON(`${BASE}/agentic/training/historical/status`);

export const historicalTrainingInsights = () =>
  fetchJSON(`${BASE}/agentic/training/historical/insights`);

export const historicalTrainingRecommendations = () =>
  fetchJSON(`${BASE}/agentic/training/historical/recommendations`);

export const historicalTrainingApply = (approvedFeatures = []) =>
  fetchJSON(`${BASE}/agentic/training/historical/apply-approved`, {
    method: 'POST',
    body: JSON.stringify({ approved_features: approvedFeatures })
  });

export const historicalTrainingRollback = () =>
  fetchJSON(`${BASE}/agentic/training/historical/rollback`, { method: 'POST' });

export const historicalTrainingEvents = (ticker = '', catalystType = '', hasOutcome = '', limit = 500) => {
  const qs = new URLSearchParams();
  if (ticker) qs.append('ticker', ticker);
  if (catalystType) qs.append('catalyst_type', catalystType);
  if (hasOutcome !== '' && hasOutcome !== null && hasOutcome !== undefined) {
    qs.append('has_outcome', String(hasOutcome));
  }
  qs.append('limit', String(limit));
  return fetchJSON(`${BASE}/agentic/training/historical/events?${qs.toString()}`);
};

export const historicalTrainingAddEvent = (data) =>
  fetchJSON(`${BASE}/agentic/training/historical/events`, { method: 'POST', body: JSON.stringify(data) });

export const historicalTrainingBuildDataset = () =>
  fetchJSON(`${BASE}/agentic/training/historical/build-dataset`, { method: 'POST' });

export const historicalTrainingResults = () =>
  fetchJSON(`${BASE}/agentic/training/historical/results`);

export const historicalTrainingMissedOpportunities = (missed = []) =>
  fetchJSON(`${BASE}/agentic/training/historical/missed-opportunities`, {
    method: 'POST',
    body: JSON.stringify({ missed })
  });

export const newsMomentumCandidates = (activeOnly = true, limit = 50) =>
  fetchJSON(`${BASE}/news-momentum/candidates?active_only=${activeOnly}&limit=${limit}`);

export const newsMomentumCandidate = (ticker) =>
  fetchJSON(`${BASE}/news-momentum/candidates/${ticker}`);

export const newsMomentumDeactivate = (ticker) =>
  fetchJSON(`${BASE}/news-momentum/candidates/${ticker}/deactivate`, { method: 'POST' });

export const newsMomentumTopRanked = (limit = 20) =>
  fetchJSON(`${BASE}/news-momentum/top-ranked?limit=${limit}`);

export const newsMomentumTopExpectedReturn = (limit = 20) =>
  fetchJSON(`${BASE}/news-momentum/top-expected-return?limit=${limit}`);

export const newsMomentumTopContinuation = (limit = 20) =>
  fetchJSON(`${BASE}/news-momentum/top-continuation?limit=${limit}`);

export const newsMomentumTopMultiday = (limit = 20) =>
  fetchJSON(`${BASE}/news-momentum/top-multiday?limit=${limit}`);

export const newsMomentumTelegramQuality = () =>
  fetchJSON(`${BASE}/news-momentum/telegram-quality`);

export const newsMomentumHistory = (limit = 100) =>
  fetchJSON(`${BASE}/news-momentum/history?limit=${limit}`);

export const newsMomentumConfig = () =>
  fetchJSON(`${BASE}/news-momentum/config`);

export const newsMomentumUpdateConfig = (data) =>
  fetchJSON(`${BASE}/news-momentum/config`, { method: 'POST', body: JSON.stringify(data) });

export const newsMomentumScanNow = () =>
  fetchJSON(`${BASE}/news-momentum/scan-now`, { method: 'POST' });

export const newsMomentumStats = () =>
  fetchJSON(`${BASE}/news-momentum/stats`);

export const newsMomentumSourceHealth = () =>
  fetchJSON(`${BASE}/news-momentum/source-health`);

export const newsMomentumCatalystStats = () =>
  fetchJSON(`${BASE}/news-momentum/catalyst-stats`);

export const newsMomentumClassifyHeadline = (headline) =>
  fetchJSON(`${BASE}/news-momentum/classify-headline?headline=${encodeURIComponent(headline)}`);

export const newsMomentumMissedWinners = (limit = 50) =>
  fetchJSON(`${BASE}/news-momentum/missed-winners?limit=${limit}`);

export const newsMomentumMissedWinnersReport = () =>
  fetchJSON(`${BASE}/news-momentum/missed-winners/report`);

export const newsMomentumTimingReviews = (params = {}) => {
  const qs = new URLSearchParams();
  if (params.ticker) qs.append('ticker', params.ticker);
  if (params.label) qs.append('label', params.label);
  if (params.source_system) qs.append('source_system', params.source_system);
  if (params.event_type) qs.append('event_type', params.event_type);
  if (params.date_from) qs.append('date_from', params.date_from);
  if (params.date_to) qs.append('date_to', params.date_to);
  qs.append('limit', String(params.limit || 250));
  return fetchJSON(`${BASE}/news-momentum/timing-reviews?${qs.toString()}`);
};

export const newsMomentumTimingSummary = (params = {}) => {
  const qs = new URLSearchParams();
  if (params.ticker) qs.append('ticker', params.ticker);
  if (params.source_system) qs.append('source_system', params.source_system);
  if (params.event_type) qs.append('event_type', params.event_type);
  if (params.date_from) qs.append('date_from', params.date_from);
  if (params.date_to) qs.append('date_to', params.date_to);
  return fetchJSON(`${BASE}/news-momentum/timing-reviews/summary?${qs.toString()}`);
};

export const newsMomentumUpdateMissedStatus = (recordId, status) =>
  fetchJSON(`${BASE}/news-momentum/missed-winners/${recordId}/status`, {
    method: 'POST',
    body: JSON.stringify({ status }),
  });

export const newsMomentumApplyShadow = (catalystType) =>
  fetchJSON(`${BASE}/news-momentum/missed-winners/apply-shadow/${catalystType}`, { method: 'POST' });

export const secCandidates = (opts = {}) => {
  const qs = new URLSearchParams();
  if (opts.behavior) qs.append('behavior', opts.behavior);
  if (opts.action) qs.append('action', opts.action);
  if (opts.limit) qs.append('limit', opts.limit);
  return fetchJSON(`${BASE}/sec-intelligence/candidates?${qs}`);
};

export const secCandidateDetail = (ticker) =>
  fetchJSON(`${BASE}/sec-intelligence/candidates/${ticker}`);

export const secFilings = (limit = 50) =>
  fetchJSON(`${BASE}/sec-intelligence/filings?limit=${limit}`);

export const secFilingsForTicker = (ticker, limit = 25) =>
  fetchJSON(`${BASE}/sec-intelligence/filings/${ticker}?limit=${limit}`);

export const secDilutionRisk = (limit = 50) =>
  fetchJSON(`${BASE}/sec-intelligence/dilution-risk?limit=${limit}`);

export const secStructuralTraps = (limit = 100) =>
  fetchJSON(`${BASE}/sec-intelligence/structural-traps?limit=${limit}`);

export const secCleanWatchlist = (limit = 100) =>
  fetchJSON(`${BASE}/sec-intelligence/clean-watchlist?limit=${limit}`);

export const secSerialDiluters = (limit = 100) =>
  fetchJSON(`${BASE}/sec-intelligence/serial-diluters?limit=${limit}`);

export const secHistory = (ticker) =>
  fetchJSON(`${BASE}/sec-intelligence/history/${ticker}`);

export const secScanNow = (tickers, concurrency = 4) =>
  fetchJSON(`${BASE}/sec-intelligence/scan-now`, {
    method: 'POST',
    body: JSON.stringify({ tickers, concurrency }),
  });

export const secStats = () =>
  fetchJSON(`${BASE}/sec-intelligence/stats`);
