import React, { useState, useEffect } from 'react';
import {
  historicalTrainingStatus,
  historicalTrainingRun,
  historicalTrainingInsights,
  historicalTrainingRecommendations,
  historicalTrainingApply,
  historicalTrainingRollback,
  historicalTrainingEvents,
  historicalTrainingAddEvent,
  historicalTrainingBuildDataset,
  historicalTrainingResults,
  historicalTrainingMissedOpportunities,
} from '../api_strategic';

function StatCard({ label, value }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <div className="text-xs text-gray-400 uppercase tracking-wider">{label}</div>
      <div className="text-2xl font-bold text-white mt-1">{value}</div>
    </div>
  );
}

export default function HistoricalTraining() {
  const [status, setStatus] = useState(null);
  const [insights, setInsights] = useState(null);
  const [recommendations, setRecommendations] = useState([]);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [runMode, setRunMode] = useState('recommend_only');
  const [message, setMessage] = useState('');
  const [selectedRecs, setSelectedRecs] = useState(new Set());
  const [newEvent, setNewEvent] = useState({ ticker: '', catalyst_type: 'EARNINGS', price_at_news: 0 });
  const [results, setResults] = useState(null);
  const [missedInsights, setMissedInsights] = useState([]);

  useEffect(() => { loadAll(); }, []);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [s, i, r, e, res] = await Promise.all([
        historicalTrainingStatus(),
        historicalTrainingInsights(),
        historicalTrainingRecommendations(),
        historicalTrainingEvents('', '', '', 50),
        historicalTrainingResults(),
      ]);
      setStatus(s); setInsights(i); setRecommendations(r); setEvents(e.events || []);
      if (res?.has_results) setResults(res.report);
    } catch (err) { setMessage(`Error: ${err.message}`); }
    finally { setLoading(false); }
  };

  const handleRun = async () => {
    setLoading(true); setMessage('');
    try { await historicalTrainingRun(runMode, Array.from(selectedRecs)); setMessage('Run complete'); await loadAll(); }
    catch (err) { setMessage(`Run failed: ${err.message}`); }
    finally { setLoading(false); }
  };

  const handleApply = async () => {
    setLoading(true);
    try { const res = await historicalTrainingApply(Array.from(selectedRecs)); setMessage(`Applied ${res.result?.applied || 0}`); await loadAll(); }
    catch (err) { setMessage(`Apply failed: ${err.message}`); }
    finally { setLoading(false); }
  };

  const handleRollback = async () => {
    setLoading(true);
    try { const res = await historicalTrainingRollback(); setMessage(res.message); await loadAll(); }
    catch (err) { setMessage(`Rollback failed: ${err.message}`); }
    finally { setLoading(false); }
  };

  const handleAddEvent = async () => {
    setLoading(true);
    try { await historicalTrainingAddEvent(newEvent); setMessage('Event added'); setNewEvent({ ticker: '', catalyst_type: 'EARNINGS', price_at_news: 0 }); await loadAll(); }
    catch (err) { setMessage(`Add failed: ${err.message}`); }
    finally { setLoading(false); }
  };

  const handleBuildDataset = async () => {
    setLoading(true);
    try { const res = await historicalTrainingBuildDataset(); setMessage(`Dataset: ${res.total_events} events`); await loadAll(); }
    catch (err) { setMessage(`Build failed: ${err.message}`); }
    finally { setLoading(false); }
  };

  const handleAnalyzeMissed = async () => {
    setLoading(true);
    try {
      const missed = [{ ticker: 'EXAMPLE', move_pct: 45, classification: 'rejected_wrong', candidate_probability_at_time: 35, rejection_reason: 'Trap risk 68%' }];
      const res = await historicalTrainingMissedOpportunities(missed);
      setMissedInsights(res.insights || []);
      setMessage(`Analyzed ${res.count} missed opportunities`);
    }
    catch (err) { setMessage(`Missed analysis failed: ${err.message}`); }
    finally { setLoading(false); }
  };

  const toggleRec = (feature) => {
    const next = new Set(selectedRecs);
    if (next.has(feature)) next.delete(feature); else next.add(feature);
    setSelectedRecs(next);
  };

  const stat = status?.dataset || {};
  const weights = status?.current_weights || {};

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Historical Catalyst Training</h1>
        <div className="flex items-center gap-2">
          <select value={runMode} onChange={(e) => setRunMode(e.target.value)} className="bg-gray-800 text-white text-sm rounded-lg px-3 py-2 border border-gray-700">
            <option value="analyse_only">Analyse Only</option>
            <option value="recommend_only">Recommend Only</option>
            <option value="approved_apply">Approved Apply</option>
          </select>
          <button onClick={handleRun} disabled={loading} className="bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium px-4 py-2 rounded-lg disabled:opacity-50">{loading ? 'Running...' : 'Run Training'}</button>
          <button onClick={handleApply} disabled={loading || selectedRecs.size === 0} className="bg-green-600 hover:bg-green-500 text-white text-sm font-medium px-4 py-2 rounded-lg disabled:opacity-50">Apply Selected</button>
          <button onClick={handleRollback} disabled={loading} className="bg-red-600 hover:bg-red-500 text-white text-sm font-medium px-4 py-2 rounded-lg disabled:opacity-50">Rollback</button>
          <button onClick={handleBuildDataset} disabled={loading} className="bg-gray-700 hover:bg-gray-600 text-white text-sm font-medium px-4 py-2 rounded-lg disabled:opacity-50">Build Dataset</button>
        </div>
      </div>

      {message && <div className="bg-gray-800 border border-gray-700 text-gray-200 px-4 py-3 rounded-lg text-sm">{message}</div>}

      <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
        <h2 className="text-lg font-semibold text-white mb-2">Calibration Status</h2>
        <div className="text-sm text-gray-300">
          {status?.current_weights?.is_approved ? (
            <span className="text-green-400">Calibrated v{status?.current_weights?.version || 1} — Approved</span>
          ) : (
            <span className="text-yellow-400">Uncalibrated — Using default weights</span>
          )}
        </div>
        {results && (
          <div className="mt-2 text-xs text-gray-500">
            Last run: {results.run_id} ({results.mode}) — {results.total_events} events, {results.resolved_events} resolved, {results.recommendations} recommendations
          </div>
        )}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Total Events" value={stat.total_events || 0} />
        <StatCard label="Resolved" value={stat.resolved_events || 0} />
        <StatCard label="Unresolved" value={stat.unresolved_events || 0} />
        <StatCard label="Pending Recs" value={recommendations.length} />
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
        <h2 className="text-lg font-semibold text-white mb-3">Calibration Weights</h2>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
          {Object.entries(weights).filter(([k]) => k.endsWith('_w')).map(([k, v]) => (
            <div key={k} className="flex justify-between bg-gray-800 rounded-lg px-3 py-2">
              <span className="text-gray-400">{k.replace(/_/g, ' ')}</span>
              <span className="text-white font-mono">{Number(v).toFixed(2)}</span>
            </div>
          ))}
        </div>
        <div className="mt-2 text-xs text-gray-500">Version {weights.version || 1} — {weights.is_approved ? 'Approved' : 'Draft'}</div>
      </div>

      {recommendations.length > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <h2 className="text-lg font-semibold text-white mb-3">Recommendations</h2>
          <div className="space-y-2">
            {recommendations.map((rec, idx) => (
              <div key={idx} className={`flex items-start gap-3 rounded-lg px-3 py-2 border ${selectedRecs.has(rec.feature) ? 'border-green-500 bg-green-500/10' : 'border-gray-700 bg-gray-800'}`}>
                <input type="checkbox" checked={selectedRecs.has(rec.feature)} onChange={() => toggleRec(rec.feature)} className="mt-1" />
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-white font-medium text-sm">{rec.feature}</span>
                    <span className={`text-xs px-2 py-0.5 rounded-full ${rec.confidence === 'high' ? 'bg-green-900 text-green-400' : 'bg-yellow-900 text-yellow-400'}`}>{rec.confidence}</span>
                    <span className="text-xs text-gray-500">n={rec.sample_count}</span>
                  </div>
                  <div className="text-sm text-gray-300 mt-1">{rec.rationale}</div>
                  <div className="text-xs text-gray-500 mt-0.5">Proposed: {rec.proposed_threshold} (from {rec.current_threshold})</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {insights?.top_patterns?.length > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <h2 className="text-lg font-semibold text-white mb-3">Top Patterns</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {insights.top_patterns.slice(0, 6).map((b, idx) => (
              <div key={idx} className="bg-gray-800 rounded-lg p-3 text-sm">
                <div className="text-white font-medium">{b.bucket_name}</div>
                <div className="text-gray-400 mt-1">Clean: {b.clean_expansion_pct}% | Second Leg: {b.second_leg_pct}% | Trap: {b.trap_pct}%</div>
                <div className="text-xs text-gray-500 mt-1">n={b.sample_size} | Avg Move: {b.avg_move_pct}%</div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
        <h2 className="text-lg font-semibold text-white mb-3">Add Event</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <input value={newEvent.ticker} onChange={(e) => setNewEvent({ ...newEvent, ticker: e.target.value })} placeholder="Ticker" className="bg-gray-800 text-white text-sm rounded-lg px-3 py-2 border border-gray-700" />
          <select value={newEvent.catalyst_type} onChange={(e) => setNewEvent({ ...newEvent, catalyst_type: e.target.value })} className="bg-gray-800 text-white text-sm rounded-lg px-3 py-2 border border-gray-700">
            <option value="EARNINGS">Earnings</option>
            <option value="FDA_REGULATORY">FDA Regulatory</option>
            <option value="CONTRACT_LICENSING">Contract/Licensing</option>
            <option value="OFFERING_DILUTION">Offering/Dilution</option>
            <option value="OTHER_NEWS">Other News</option>
          </select>
          <input type="number" value={newEvent.price_at_news} onChange={(e) => setNewEvent({ ...newEvent, price_at_news: Number(e.target.value) })} placeholder="Price" className="bg-gray-800 text-white text-sm rounded-lg px-3 py-2 border border-gray-700" />
          <button onClick={handleAddEvent} disabled={loading || !newEvent.ticker} className="bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium px-4 py-2 rounded-lg disabled:opacity-50">Add</button>
        </div>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold text-white">Missed Opportunity Analysis</h2>
          <button onClick={handleAnalyzeMissed} disabled={loading} className="bg-purple-600 hover:bg-purple-500 text-white text-sm font-medium px-3 py-1.5 rounded-lg disabled:opacity-50">Analyze Missed</button>
        </div>
        {missedInsights.length === 0 && (
          <div className="text-sm text-gray-500">No missed-opportunity analysis yet. Click Analyze to cross-reference historical patterns.</div>
        )}
        <div className="space-y-2">
          {missedInsights.map((mi, idx) => (
            <div key={idx} className={`bg-gray-800 rounded-lg p-3 text-sm border ${mi.matches_winners ? 'border-green-700' : 'border-gray-700'}`}>
              <div className="flex items-center gap-2">
                <span className="text-white font-medium">{mi.ticker}</span>
                <span className="text-gray-400">moved {mi.move_pct}%</span>
                {mi.matches_winners && <span className="text-xs bg-green-900 text-green-400 px-2 py-0.5 rounded-full">Matches {mi.historical_win_rate}% historical win rate</span>}
              </div>
              <div className="text-gray-300 mt-1">{mi.recommended_fix}</div>
            </div>
          ))}
        </div>
      </div>

      {events.length > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <h2 className="text-lg font-semibold text-white mb-3">Recent Events</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left text-gray-300">
              <thead className="text-xs text-gray-500 uppercase bg-gray-800">
                <tr><th className="px-3 py-2">Ticker</th><th className="px-3 py-2">Type</th><th className="px-3 py-2">Price</th><th className="px-3 py-2">Outcome</th><th className="px-3 py-2">Date</th></tr>
              </thead>
              <tbody>
                {events.slice(0, 20).map((evt) => (
                  <tr key={evt.id} className="border-b border-gray-800">
                    <td className="px-3 py-2 font-medium">{evt.ticker}</td>
                    <td className="px-3 py-2">{evt.catalyst_type}</td>
                    <td className="px-3 py-2">{evt.price_at_news}</td>
                    <td className="px-3 py-2">{evt.outcome ? evt.outcome.outcome_class : '—'}</td>
                    <td className="px-3 py-2">{evt.event_date}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
