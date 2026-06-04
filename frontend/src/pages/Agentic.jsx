import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  Zap, RefreshCw, Search, AlertTriangle,
  Activity, Target, Shield, Brain, Eye, XCircle,
  Lightbulb, TrendingUp, TrendingDown, AlertCircle, CheckCircle2, Volume2,
  Newspaper, Flame,
} from 'lucide-react'
import {
  agenticScan, agenticCandidates, agenticCandidateDetail,
  agenticRefreshCandidate, agenticDeactivate, agenticAlerts,
  agenticStatus, agenticLearningStats, agenticMissedOpportunities,
  agenticApplyWeights, agenticRollbackWeights,
  qualitySeparatorStatus, qualitySeparatorProfiles, qualitySeparatorReport,
  preNewsScan, preNewsAnomalies, preNewsLearning, preNewsMissedReview, preNewsEvaluation, preNewsExportEvaluation, preNewsExportList, preNewsAnalyze, preNewsReport, preNewsBaselinesSummary,
  mlTrain, mlStatus, mlApprove, mlDrift,
  newsImpactCandidates, newsImpactDetail, newsImpactLearningSummary,
} from '../api_strategic'

// ── Constants ───────────────────────────────────────────────────────────────

const STATE_COLORS = {
  initial_spike: 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30',
  spike_pullback: 'text-orange-400 bg-orange-500/10 border-orange-500/30',
  consolidation: 'text-blue-400 bg-blue-500/10 border-blue-500/30',
  second_leg_forming: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30',
  continuation_confirmed: 'text-green-400 bg-green-500/10 border-green-500/30',
  failed: 'text-red-400 bg-red-500/10 border-red-500/30',
  dead: 'text-gray-500 bg-gray-500/10 border-gray-500/30',
}

const STATE_LABELS = {
  initial_spike: 'Initial Spike',
  spike_pullback: 'Pullback',
  consolidation: 'Consolidation',
  second_leg_forming: '2nd Leg Forming',
  continuation_confirmed: 'Continuation ✓',
  failed: 'Failed',
  dead: 'Dead',
}

const CONFIDENCE_COLORS = {
  low: 'text-gray-400',
  watch: 'text-yellow-400',
  high: 'text-emerald-400',
  very_high: 'text-green-400',
}

// ── Helper Components ───────────────────────────────────────────────────────

function StateBadge({ state }) {
  return (
    <span className={`text-[11px] px-2 py-0.5 rounded border font-medium ${STATE_COLORS[state] || STATE_COLORS.dead}`}>
      {STATE_LABELS[state] || state}
    </span>
  )
}

function ProbabilityBar({ value, size = 'md' }) {
  const h = size === 'sm' ? 'h-1.5' : 'h-2.5'
  const color = value >= 70 ? 'bg-emerald-500' : value >= 50 ? 'bg-yellow-500' : value >= 30 ? 'bg-orange-500' : 'bg-red-500'
  return (
    <div className={`w-full ${h} bg-gray-700 rounded-full overflow-hidden`}>
      <div className={`${h} ${color} rounded-full transition-all`} style={{ width: `${Math.min(value, 100)}%` }} />
    </div>
  )
}

function MetricPill({ label, value, icon: Icon, color = 'text-gray-300' }) {
  return (
    <div className="flex items-center gap-1.5 text-xs">
      {Icon && <Icon className={`w-3 h-3 ${color}`} />}
      <span className="text-gray-500">{label}:</span>
      <span className={`font-medium ${color}`}>{value}</span>
    </div>
  )
}

function QualityDecisionBadge({ decision }) {
  const colors = {
    boost: 'text-emerald-300 bg-emerald-500/15 border-emerald-500/30',
    allow: 'text-blue-300 bg-blue-500/15 border-blue-500/30',
    downgrade: 'text-orange-300 bg-orange-500/15 border-orange-500/30',
    block: 'text-red-300 bg-red-500/15 border-red-500/30',
    allow_neutral: 'text-gray-300 bg-gray-500/15 border-gray-500/30',
  }
  const labels = {
    boost: 'BOOST',
    allow: 'ALLOW',
    downgrade: 'DOWNGRADE',
    block: 'BLOCK',
    allow_neutral: 'NEUTRAL',
  }
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded border font-bold ${colors[decision] || colors.allow_neutral}`}>
      {labels[decision] || decision?.toUpperCase()}
    </span>
  )
}

// V17 timing-state priority (lower = higher priority in the cockpit list)
const TIMING_STATE_PRIORITY = {
  ideal_entry: 0,
  waiting_for_confirmation: 1,
  too_early: 2,
  late_chase: 3,
  invalid_entry: 4,
  // legacy fallbacks
  ideal: 0,
  early: 2,
  late: 3,
}

function TimingStateBadge({ state, size = 'sm' }) {
  // Colors aligned with V17 spec:
  // too_early=gray, waiting_for_confirmation=yellow, ideal_entry=green, late_chase=orange, invalid_entry=red
  const colors = {
    too_early: 'text-gray-300 bg-gray-500/15 border-gray-500/30',
    waiting_for_confirmation: 'text-yellow-300 bg-yellow-500/15 border-yellow-500/30',
    ideal_entry: 'text-emerald-300 bg-emerald-500/15 border-emerald-500/40',
    late_chase: 'text-orange-300 bg-orange-500/15 border-orange-500/30',
    invalid_entry: 'text-red-300 bg-red-500/15 border-red-500/30',
    // legacy compatibility
    early: 'text-gray-300 bg-gray-500/15 border-gray-500/30',
    ideal: 'text-emerald-300 bg-emerald-500/15 border-emerald-500/40',
    late: 'text-red-300 bg-red-500/15 border-red-500/30',
  }
  const labels = {
    too_early: 'TOO EARLY',
    waiting_for_confirmation: 'WAITING',
    ideal_entry: 'IDEAL ENTRY',
    late_chase: 'LATE CHASE',
    invalid_entry: 'AVOID',
    early: 'EARLY',
    ideal: 'IDEAL',
    late: 'LATE',
  }
  const icons = {
    too_early: '⚪',
    waiting_for_confirmation: '🟡',
    ideal_entry: '🟢',
    late_chase: '🟠',
    invalid_entry: '🔴',
    early: '⚪',
    ideal: '🟢',
    late: '🔴',
  }
  const s = state?.value || state
  const sizing = size === 'lg'
    ? 'text-xs px-2.5 py-1'
    : 'text-[10px] px-1.5 py-0.5'
  return (
    <span className={`${sizing} rounded border font-bold ${colors[s] || colors.early} whitespace-nowrap`}>
      {icons[s]} {labels[s] || s?.toUpperCase()}
    </span>
  )
}

function CheckItem({ label, ok }) {
  return (
    <div className="flex items-center gap-1 text-xs">
      <span className={ok ? 'text-emerald-400' : 'text-red-400/60'}>
        {ok ? '✓' : '✗'}
      </span>
      <span className={ok ? 'text-gray-300' : 'text-gray-500'}>{label}</span>
    </div>
  )
}

// ── Candidate Row ───────────────────────────────────────────────────────────

// Map timing state → row-level container styling (decision priority highlight)
function rowDecisionStyle(timingState, isBestSetup) {
  const s = timingState?.value || timingState
  if (isBestSetup) {
    // 🔥 BEST SETUP — strongest glow
    return 'border-l-4 border-l-emerald-400 bg-emerald-500/10 shadow-[0_0_12px_rgba(16,185,129,0.25)] hover:bg-emerald-500/15'
  }
  if (s === 'ideal_entry' || s === 'ideal') {
    return 'border-l-4 border-l-emerald-500/70 bg-emerald-500/5 hover:bg-emerald-500/10'
  }
  if (s === 'invalid_entry' || s === 'late_chase' || s === 'late') {
    return 'border-l-4 border-l-red-500/40 opacity-60 hover:opacity-90 hover:bg-gray-800/50'
  }
  if (s === 'waiting_for_confirmation') {
    return 'border-l-4 border-l-yellow-500/40 hover:bg-gray-800/50'
  }
  // too_early / unknown
  return 'border-l-4 border-l-transparent hover:bg-gray-800/50'
}

function CandidateRow({ c, onSelect, onRefresh, onDeactivate, isBestSetup }) {
  const timingState = c.entry_timing?.timing_state || c.entry_quality
  const et = c.entry_timing || {}
  const score = et.entry_timing_score || 0
  const rr = et.risk_reward_ratio
  const zoneLow = et.entry_zone_low
  const zoneHigh = et.entry_zone_high
  const stop = et.stop_level
  const rowStyle = rowDecisionStyle(timingState, isBestSetup)

  return (
    <div
      className={`grid grid-cols-12 gap-2 items-center px-4 py-3 cursor-pointer border-b border-gray-800/50 transition-colors ${rowStyle}`}
      onClick={() => onSelect(c.ticker)}
    >
      {/* Ticker + Catalyst */}
      <div className="col-span-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-bold text-white text-sm">${c.ticker}</span>
          {isBestSetup && (
            <span className="text-[10px] px-1.5 py-0.5 rounded font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-400/50">
              🔥 BEST SETUP
            </span>
          )}
          <StateBadge state={c.state} />
        </div>
        <p className="text-[11px] text-gray-500 mt-0.5 truncate">{c.catalyst_headline || c.catalyst}</p>
      </div>

      {/* Price */}
      <div className="col-span-1">
        <span className={`text-sm font-bold ${(c.last_price || 0) < 5 ? 'text-yellow-400' : 'text-white'}`}>
          ${c.last_price?.toFixed ? c.last_price.toFixed(2) : '—'}
        </span>
        {(c.last_price || 0) < 1 && (
          <span className="text-[10px] text-yellow-400/80 block">Sub-penny</span>
        )}
      </div>

      {/* Probability */}
      <div className="col-span-2">
        <div className="flex items-center gap-2">
          <span className={`text-sm font-bold ${c.probability >= 70 ? 'text-emerald-400' : c.probability >= 50 ? 'text-yellow-400' : 'text-gray-400'}`}>
            {c.probability}%
          </span>
          <span className={`text-[10px] ${CONFIDENCE_COLORS[c.confidence]}`}>{c.confidence?.toUpperCase()}</span>
        </div>
        <ProbabilityBar value={c.probability} size="sm" />
      </div>

      {/* Trap Risk */}
      <div className="col-span-1">
        <span className={`text-xs font-medium ${c.trap_risk >= 65 ? 'text-red-400' : c.trap_risk >= 40 ? 'text-yellow-400' : 'text-gray-400'}`}>
          {c.trap_risk}%
        </span>
      </div>

      {/* Entry Timing — V17 (state = primary visual, zone/stop/RR below) */}
      <div className="col-span-3 space-y-1">
        <TimingStateBadge state={timingState} size="lg" />
        <div className="flex items-center gap-1.5">
          <div className="flex-1 h-1.5 bg-gray-700 rounded-full overflow-hidden max-w-[90px]">
            <div
              className={`h-1.5 rounded-full ${score >= 70 ? 'bg-emerald-500' : score >= 40 ? 'bg-yellow-500' : 'bg-red-500'}`}
              style={{ width: `${Math.min(score, 100)}%` }}
            />
          </div>
          <span className="text-[10px] text-gray-400 font-medium">{score}/100</span>
        </div>
        {(zoneLow != null && zoneHigh != null) && (
          <p className="text-[10px] text-gray-400">
            Zone <span className="text-white font-medium">${zoneLow.toFixed(2)}–${zoneHigh.toFixed(2)}</span>
          </p>
        )}
        <div className="flex gap-2 text-[10px]">
          {stop != null && (
            <span className="text-red-400">Stop ${stop.toFixed(2)}</span>
          )}
          <span className={rr != null ? (rr >= 2.0 ? 'text-emerald-400 font-medium' : 'text-yellow-400') : 'text-gray-500'}>
            R:R {rr != null ? `${rr.toFixed(1)}:1` : 'N/A'}
          </span>
        </div>
      </div>

      {/* VWAP + HL */}
      <div className="col-span-1 flex flex-col gap-0.5">
        <span className={`text-[11px] ${c.vwap_reclaimed ? 'text-emerald-400' : 'text-red-400/70'}`}>
          {c.vwap_reclaimed ? '✓ VWAP' : '✗ VWAP'}
        </span>
        <span className={`text-[11px] ${c.higher_low ? 'text-emerald-400' : 'text-gray-500'}`}>
          {c.higher_low ? '✓ HL' : '– HL'}
        </span>
      </div>

      {/* Quality + Alertable + ABCD */}
      <div className="col-span-1 space-y-0.5">
        <QualityDecisionBadge decision={c.quality_separator?.quality_decision} />
        {c.alertable ? (
          <span className="flex items-center gap-1 text-[11px] text-green-400"><Zap className="w-3 h-3" /> ALERT</span>
        ) : (
          <span className="text-[11px] text-gray-600">—</span>
        )}
        {c.abcd && c.abcd.abcd_state !== 'no_pattern' && (
          <span className={`text-[10px] font-medium ${
            c.abcd.abcd_state === 'continuation_ready' ? 'text-emerald-400' :
            c.abcd.abcd_state === 'retest_confirmed' ? 'text-blue-400' :
            c.abcd.abcd_state === 'failed_pattern' ? 'text-red-400' :
            'text-yellow-400'
          }`}>
            ABCD {c.abcd.abcd_phase}
          </span>
        )}
        {c.ml_prediction && c.ml_prediction.model_version && (
          <span className={`text-[10px] font-medium ${
            c.ml_prediction.is_live ? 'text-purple-400' : 'text-gray-500'
          }`}>
            <Brain className="w-3 h-3 inline mr-0.5" />
            ML {(c.ml_prediction.continuation_prob * 100).toFixed(0)}%
          </span>
        )}
      </div>

      {/* Actions */}
      <div className="col-span-1 flex gap-1 justify-end" onClick={(e) => e.stopPropagation()}>
        <button onClick={() => onRefresh(c.ticker)} className="p-1 rounded hover:bg-gray-700 text-gray-400 hover:text-white" title="Refresh">
          <RefreshCw className="w-3.5 h-3.5" />
        </button>
        <button onClick={() => onDeactivate(c.ticker)} className="p-1 rounded hover:bg-gray-700 text-gray-400 hover:text-red-400" title="Deactivate">
          <XCircle className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  )
}

// ── Detail Panel ────────────────────────────────────────────────────────────

function DetailPanel({ detail, onClose }) {
  if (!detail) return null
  const c = detail.candidate
  const m = c.momentum || {}
  const sl = c.second_leg || {}
  const trap = c.trap || {}
  const et = c.entry_timing || {}
  const fi = c.float_intel || {}
  const fv = c.failure_velocity || {}
  const tod = c.time_of_day || {}
  const hr = c.hard_rejection || {}
  const asym = c.asymmetric_scoring || {}

  return (
    <div className="fixed inset-y-0 right-0 w-[480px] bg-gray-900 border-l border-gray-700 z-40 overflow-y-auto shadow-2xl">
      <div className="sticky top-0 bg-gray-900 border-b border-gray-700 px-5 py-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-white">${c.ticker}</h2>
          <p className="text-xs text-gray-500 mt-0.5">{c.catalyst?.headline?.slice(0, 100)}</p>
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-white text-xl">&times;</button>
      </div>

      <div className="p-5 space-y-5">
        {/* Probability + State */}
        <div className="card">
          <div className="flex items-center justify-between mb-3">
            <div>
              <span className="text-3xl font-bold text-white">{c.final_probability}%</span>
              <span className={`ml-2 text-sm ${CONFIDENCE_COLORS[c.final_confidence]}`}>{c.final_confidence?.toUpperCase()}</span>
            </div>
            <StateBadge state={m.state} />
          </div>
          <ProbabilityBar value={c.final_probability} />
          {c.alertable && (
            <div className="mt-2 flex items-center gap-2 text-emerald-400 text-xs">
              <Zap className="w-4 h-4" /> Alertable — meets all criteria
            </div>
          )}
          {c.rejected && (
            <div className="mt-2 text-red-400 text-xs">
              <AlertTriangle className="w-3 h-3 inline mr-1" />
              Rejected: {(c.rejection_reasons || []).join(', ')}
            </div>
          )}
        </div>

        {/* Hard Rejection */}
        {hr && hr.triggered && (
          <div className="card border-red-500/30">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-red-400 flex items-center gap-1">
                <AlertTriangle className="w-4 h-4" /> Hard Rejection
              </h3>
              <span className="text-[10px] px-2 py-0.5 rounded bg-red-500/20 text-red-400 border border-red-500/30 font-bold">BLOCKED</span>
            </div>
            <div className="space-y-2">
              {hr.rejection_reasons?.map((reason, i) => (
                <p key={i} className="text-[11px] text-red-300 font-medium">{reason}</p>
              ))}
            </div>
            <p className="mt-3 text-[10px] text-red-400/70">Candidate blocked before scoring. No alert emitted.</p>
          </div>
        )}

        {/* Asymmetric Scoring */}
        {asym && (asym.penalties?.length > 0 || asym.boosts?.length > 0) && (
          <div className="card">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-gray-200">Asymmetric Scoring</h3>
              <span className={`text-xs font-bold ${asym.final_adjustment < 0 ? 'text-red-400' : asym.final_adjustment > 0 ? 'text-emerald-400' : 'text-gray-400'}`}>
                {asym.final_adjustment > 0 ? '+' : ''}{asym.final_adjustment} pts
              </span>
            </div>

            {asym.penalties?.length > 0 && (
              <div className="mb-3">
                <span className="text-[10px] text-red-400 font-semibold uppercase tracking-wide">Penalties</span>
                <ul className="mt-1 space-y-1">
                  {asym.penalties.map((p, i) => (
                    <li key={i} className="flex items-center justify-between text-xs">
                      <span className="text-gray-400">{p.name.replace(/_/g, ' ')}</span>
                      <span className="text-red-400 font-medium">{p.value} pts</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {asym.boosts?.length > 0 && (
              <div>
                <span className="text-[10px] text-emerald-400 font-semibold uppercase tracking-wide">Boosts</span>
                <ul className="mt-1 space-y-1">
                  {asym.boosts.map((b, i) => (
                    <li key={i} className="flex items-center justify-between text-xs">
                      <span className="text-gray-400">{b.name.replace(/_/g, ' ')}</span>
                      <span className="text-emerald-400 font-medium">+{b.value} pts</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="mt-3 pt-2 border-t border-gray-700 grid grid-cols-2 gap-2 text-[10px]">
              <div><span className="text-gray-500">Base:</span> <span className="text-white">{asym.base_probability}%</span></div>
              <div><span className="text-gray-500">Final:</span> <span className="text-white">{asym.final_probability}%</span></div>
              <div><span className="text-gray-500">Penalty Sum:</span> <span className="text-red-400">{asym.raw_penalty_sum}</span></div>
              <div><span className="text-gray-500">Boost Sum:</span> <span className="text-emerald-400">{asym.raw_boost_sum}</span></div>
            </div>
          </div>
        )}

        {/* Quality Separator */}
        {c.quality_separator && (
          <div className="card">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-gray-200">Quality Separator</h3>
              <QualityDecisionBadge decision={c.quality_separator.quality_decision} />
            </div>
            <div className="grid grid-cols-3 gap-2 text-xs mb-3">
              <div>
                <span className="text-gray-500 block">Quality Score</span>
                <span className={`font-bold ${c.quality_separator.quality_separator_score >= 65 ? 'text-emerald-400' : c.quality_separator.quality_separator_score >= 45 ? 'text-yellow-400' : 'text-red-400'}`}>
                  {c.quality_separator.quality_separator_score}
                </span>
              </div>
              <div>
                <span className="text-gray-500 block">Winner Sim</span>
                <span className="font-bold text-emerald-400">{c.quality_separator.winner_similarity_score}%</span>
              </div>
              <div>
                <span className="text-gray-500 block">Loser Sim</span>
                <span className="font-bold text-red-400">{c.quality_separator.loser_similarity_score}%</span>
              </div>
            </div>
            {c.quality_separator.quality_reasons?.length > 0 && (
              <div className="mb-2">
                <span className="text-gray-500 text-xs">Reasons:</span>
                <ul className="list-disc list-inside text-xs text-emerald-300 mt-1">
                  {c.quality_separator.quality_reasons.slice(0, 5).map((r, i) => <li key={i}>{r}</li>)}
                </ul>
              </div>
            )}
            {c.quality_separator.quality_warnings?.length > 0 && (
              <div>
                <span className="text-gray-500 text-xs">Warnings:</span>
                <ul className="list-disc list-inside text-xs text-red-300 mt-1">
                  {c.quality_separator.quality_warnings.slice(0, 5).map((w, i) => <li key={i}>{w}</li>)}
                </ul>
              </div>
            )}
            {c.quality_separator.quality_adjustment !== 0 && (
              <div className="mt-2 text-xs">
                <span className="text-gray-500">Adjustment: </span>
                <span className={c.quality_separator.quality_adjustment > 0 ? 'text-emerald-400' : 'text-red-400'}>
                  {c.quality_separator.quality_adjustment > 0 ? '+' : ''}{c.quality_separator.quality_adjustment} pts
                </span>
                <span className="text-gray-500"> (base {c.quality_separator.base_probability}% → final {c.quality_separator.final_probability_after_quality}%)</span>
              </div>
            )}
            {!c.quality_separator.data_sufficient && (
              <div className="mt-2 text-xs text-yellow-400">
                Insufficient data ({c.quality_separator.total_historical_outcomes} outcomes)
              </div>
            )}
          </div>
        )}

        {/* Momentum */}
        <div className="card">
          <h3 className="text-sm font-semibold text-gray-400 mb-2 flex items-center gap-1"><Activity className="w-4 h-4" /> Momentum</h3>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <MetricPill label="Price" value={`$${m.price?.toFixed(2) || '—'}`} />
            <MetricPill label="VWAP" value={`$${m.vwap?.toFixed(2) || '—'}`} color={m.vwap_reclaimed ? 'text-emerald-400' : 'text-red-400'} />
            <MetricPill label="HOD" value={`$${m.high_of_day?.toFixed(2) || '—'}`} />
            <MetricPill label="Post-Spike Low" value={`$${m.post_spike_low?.toFixed(2) || '—'}`} />
            <MetricPill label="Vol Persist" value={`${m.volume_persistence_pct?.toFixed(0) || 0}%`} />
            <MetricPill label="Consol Bars" value={m.consolidation_bars || 0} />
            <MetricPill label="Higher Low" value={m.higher_low_formed ? '✓' : '✗'} color={m.higher_low_formed ? 'text-emerald-400' : 'text-gray-500'} />
            <MetricPill label="Breakout" value={m.breakout_confirmed ? '✓' : '✗'} color={m.breakout_confirmed ? 'text-emerald-400' : 'text-gray-500'} />
          </div>
        </div>

        {/* ABCD Pattern Confirmation — V18 */}
        {c.abcd && c.abcd.abcd_state !== 'no_pattern' && (
          <div className="card border-l-2 border-l-blue-500/30">
            <h3 className="text-sm font-semibold text-gray-400 mb-2 flex items-center gap-1">
              <TrendingUp className="w-4 h-4" /> ABCD Pattern
            </h3>
            <div className="flex items-center gap-2 mb-2">
              <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${
                c.abcd.abcd_state === 'continuation_ready' || c.abcd.abcd_state === 'retest_confirmed'
                  ? 'bg-emerald-500/15 text-emerald-400'
                  : c.abcd.abcd_state === 'failed_pattern'
                    ? 'bg-red-500/15 text-red-400'
                    : 'bg-blue-500/15 text-blue-400'
              }`}>
                {c.abcd.abcd_phase}
              </span>
              <span className="text-xs text-gray-500">Phase {c.abcd.abcd_phase}</span>
              <span className={`text-xs font-bold ${c.abcd.abcd_score >= 70 ? 'text-emerald-400' : c.abcd.abcd_score >= 40 ? 'text-yellow-400' : 'text-gray-400'}`}>
                Score {c.abcd.abcd_score}/100
              </span>
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              {c.abcd.abcd_key_level && (
                <MetricPill label="Key Level" value={`$${c.abcd.abcd_key_level.toFixed(2)}`} />
              )}
              {c.abcd.abcd_retest_level && (
                <MetricPill label="Retest Lvl" value={`$${c.abcd.abcd_retest_level.toFixed(2)}`} />
              )}
              {c.abcd.abcd_invalidation_level && (
                <MetricPill label="Invalidation" value={`$${c.abcd.abcd_invalidation_level.toFixed(2)}`} color="text-red-400" />
              )}
            </div>
            {c.abcd.abcd_reasons?.length > 0 && (
              <div className="mt-2 space-y-1">
                {c.abcd.abcd_reasons.slice(0, 3).map((r, i) => (
                  <p key={i} className="text-[11px] text-emerald-400/80">+ {r}</p>
                ))}
              </div>
            )}
            {c.abcd.abcd_warnings?.length > 0 && (
              <div className="mt-1 space-y-1">
                {c.abcd.abcd_warnings.slice(0, 2).map((w, i) => (
                  <p key={i} className="text-[11px] text-yellow-400/80">⚠ {w}</p>
                ))}
              </div>
            )}
            <div className="mt-2 text-[11px] text-gray-500">
              {c.abcd.abcd_entry_valid
                ? <span className="text-emerald-400">Entry valid — ABCD confirmed</span>
                : <span className="text-yellow-400">Entry not yet valid — awaiting confirmation</span>
              }
            </div>
          </div>
        )}

        {/* ML Advisory — V19 */}
        {c.ml_prediction && c.ml_prediction.model_version && (
          <div className="card border-l-2 border-l-purple-500/30">
            <h3 className="text-sm font-semibold text-gray-400 mb-2 flex items-center gap-1">
              <Brain className="w-4 h-4" /> ML Advisory
              {!c.ml_prediction.is_live && (
                <span className="text-[10px] bg-yellow-500/15 text-yellow-400 px-1.5 py-0.5 rounded ml-1">Shadow</span>
              )}
              {c.ml_prediction.is_live && (
                <span className="text-[10px] bg-emerald-500/15 text-emerald-400 px-1.5 py-0.5 rounded ml-1">Live</span>
              )}
            </h3>
            <div className="grid grid-cols-2 gap-2 mb-2">
              <MetricPill
                label="Cont. Prob"
                value={`${(c.ml_prediction.continuation_prob * 100).toFixed(1)}%`}
                color={c.ml_prediction.continuation_prob >= 0.7 ? 'text-emerald-400' : c.ml_prediction.continuation_prob >= 0.4 ? 'text-yellow-400' : 'text-red-400'}
              />
              <MetricPill
                label="False Alert"
                value={`${(c.ml_prediction.false_alert_prob * 100).toFixed(1)}%`}
                color={c.ml_prediction.false_alert_prob <= 0.2 ? 'text-emerald-400' : c.ml_prediction.false_alert_prob <= 0.4 ? 'text-yellow-400' : 'text-red-400'}
              />
              <MetricPill label="Exp MFE" value={`${c.ml_prediction.expected_mfe?.toFixed(1)}%`} />
              <MetricPill label="Exp MAE" value={`${c.ml_prediction.expected_mae?.toFixed(1)}%`} />
              <MetricPill
                label="Risk-Adj"
                value={`${c.ml_prediction.risk_adjusted_score?.toFixed(1) ?? '0.0'}`}
                color={c.ml_prediction.risk_adjusted_score >= 2 ? 'text-emerald-400' : c.ml_prediction.risk_adjusted_score >= 1 ? 'text-yellow-400' : 'text-red-400'}
              />
              <MetricPill
                label="Size"
                value={c.ml_prediction.suggested_position_size || 'NONE'}
                color={c.ml_prediction.suggested_position_size === 'FULL' ? 'text-emerald-400' : c.ml_prediction.suggested_position_size === 'HALF' ? 'text-yellow-400' : 'text-gray-500'}
              />
            </div>
            <div className="flex items-center gap-2 text-[11px] text-gray-500 mb-1">
              <span>Confidence:</span>
              <span className={c.ml_prediction.confidence === 'HIGH' ? 'text-emerald-400' : c.ml_prediction.confidence === 'MEDIUM' ? 'text-yellow-400' : 'text-gray-400'}>
                {c.ml_prediction.confidence}
              </span>
              <span className="text-gray-600">| v{c.ml_prediction.model_version}</span>
            </div>
            {c.ml_prediction.top_shap?.length > 0 && (
              <div className="mt-1 space-y-1">
                <p className="text-[10px] text-gray-500 uppercase tracking-wider">Top Drivers</p>
                {c.ml_prediction.top_shap.map((s, i) => (
                  <div key={i} className="flex items-center justify-between text-[11px]">
                    <span className="text-gray-400">{s.feature}</span>
                    <span className={s.shap_value > 0 ? 'text-emerald-400' : 'text-red-400'}>
                      {s.shap_value > 0 ? '+' : ''}{s.shap_value.toFixed(3)}
                    </span>
                  </div>
                ))}
              </div>
            )}
            {c.ml_prediction.fallback_reason && (
              <p className="text-[11px] text-yellow-400 mt-1">Fallback: {c.ml_prediction.fallback_reason}</p>
            )}
          </div>
        )}

        {/* Second Leg Components */}
        <div className="card">
          <h3 className="text-sm font-semibold text-gray-400 mb-2 flex items-center gap-1"><Target className="w-4 h-4" /> Second Leg Components</h3>
          {sl.components && Object.entries(sl.components).map(([k, v]) => (
            <div key={k} className="flex items-center justify-between mb-1.5">
              <span className="text-xs text-gray-400 capitalize">{k.replace('_', ' ')}</span>
              <div className="flex items-center gap-2">
                <div className="w-24 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                  <div className={`h-1.5 rounded-full ${v >= 70 ? 'bg-emerald-500' : v >= 40 ? 'bg-yellow-500' : 'bg-red-500'}`} style={{ width: `${v}%` }} />
                </div>
                <span className="text-xs text-gray-300 w-8 text-right">{v?.toFixed(0)}</span>
              </div>
            </div>
          ))}
          {sl.reasons?.length > 0 && (
            <div className="mt-2 space-y-1">
              {sl.reasons.map((r, i) => <p key={i} className="text-[11px] text-emerald-400/80">+ {r}</p>)}
            </div>
          )}
          {sl.warnings?.length > 0 && (
            <div className="mt-1 space-y-1">
              {sl.warnings.map((w, i) => <p key={i} className="text-[11px] text-yellow-400/80">⚠ {w}</p>)}
            </div>
          )}
        </div>

        {/* Trap Detection */}
        <div className="card">
          <h3 className="text-sm font-semibold text-gray-400 mb-2 flex items-center gap-1"><Shield className="w-4 h-4" /> Trap Detection</h3>
          <div className="flex items-center gap-3 mb-2">
            <span className={`text-xl font-bold ${trap.trap_risk_score >= 65 ? 'text-red-400' : trap.trap_risk_score >= 40 ? 'text-yellow-400' : 'text-emerald-400'}`}>
              {trap.trap_risk_score?.toFixed(0)}%
            </span>
            {trap.is_trap && <span className="text-xs text-red-400 bg-red-500/10 px-2 py-0.5 rounded border border-red-500/30">TRAP DETECTED</span>}
          </div>
          <ProbabilityBar value={trap.trap_risk_score || 0} size="sm" />
          {trap.trap_types?.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {trap.trap_types.map((t, i) => <span key={i} className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/10 text-red-400 border border-red-500/20">{t}</span>)}
            </div>
          )}
          {trap.reasons?.map((r, i) => <p key={i} className="text-[11px] text-gray-400 mt-1">• {r}</p>)}
        </div>

        {/* Entry Timing — V17 enriched */}
        <div className="card">
          <h3 className="text-sm font-semibold text-gray-400 mb-2 flex items-center gap-1"><Target className="w-4 h-4" /> Entry Timing</h3>

          {/* State badge + score — visual hierarchy: state is LARGEST element */}
          <div className="flex items-center gap-3 mb-3 flex-wrap">
            <TimingStateBadge state={et.timing_state || et.quality} size="lg" />
            <span className="text-xs text-gray-400">Score:</span>
            <div className="w-24 h-1.5 bg-gray-700 rounded-full overflow-hidden">
              <div
                className={`h-1.5 rounded-full ${(et.entry_timing_score || 0) >= 70 ? 'bg-emerald-500' : (et.entry_timing_score || 0) >= 40 ? 'bg-yellow-500' : 'bg-red-500'}`}
                style={{ width: `${Math.min(et.entry_timing_score || 0, 100)}%` }}
              />
            </div>
            <span className="text-xs text-gray-300">{et.entry_timing_score || 0}/100</span>
          </div>

          {/* Entry zone + R:R */}
          {(et.entry_zone_low && et.entry_zone_high) && (
            <div className="grid grid-cols-2 gap-2 text-xs mb-2">
              <div>
                <span className="text-gray-500 block">Entry Zone</span>
                <span className="text-white font-medium">${et.entry_zone_low?.toFixed(2)} – ${et.entry_zone_high?.toFixed(2)}</span>
              </div>
              {et.ideal_entry_price && (
                <div>
                  <span className="text-gray-500 block">Ideal Price</span>
                  <span className="text-white font-medium">${et.ideal_entry_price?.toFixed(2)}</span>
                </div>
              )}
            </div>
          )}

          {/* Stop + Targets */}
          <div className="grid grid-cols-2 gap-2 text-xs mb-2">
            {et.stop_level && (
              <div>
                <span className="text-gray-500 block">Stop</span>
                <span className="text-red-400 font-medium">${et.stop_level?.toFixed(2)}</span>
              </div>
            )}
            <div>
              <span className="text-gray-500 block">R:R</span>
              <span className={`font-medium ${et.risk_reward_ratio != null ? (et.risk_reward_ratio >= 2.0 ? 'text-emerald-400' : 'text-yellow-400') : 'text-gray-500'}`}>
                {et.risk_reward_ratio != null ? `${et.risk_reward_ratio.toFixed(1)}:1` : 'N/A'}
              </span>
            </div>
            {et.target_1 && (
              <div>
                <span className="text-gray-500 block">Target 1</span>
                <span className="text-emerald-400 font-medium">${et.target_1?.toFixed(2)}</span>
              </div>
            )}
            {et.target_2 && (
              <div>
                <span className="text-gray-500 block">Target 2</span>
                <span className="text-emerald-400 font-medium">${et.target_2?.toFixed(2)}</span>
              </div>
            )}
            {et.stretch_target && (
              <div className="col-span-2">
                <span className="text-gray-500 block">Stretch Target</span>
                <span className="text-emerald-400/70 font-medium">${et.stretch_target?.toFixed(2)}</span>
              </div>
            )}
            {et.invalidation_level && (
              <div className="col-span-2">
                <span className="text-gray-500 block">Invalidation Level</span>
                <span className="text-red-400/70 font-medium">${et.invalidation_level?.toFixed(2)}</span>
              </div>
            )}
          </div>

          {/* Entry Checklist */}
          <div className="bg-gray-800/50 rounded p-2 mt-2 mb-2">
            <p className="text-[11px] text-gray-500 uppercase tracking-wider mb-1">Entry Checklist</p>
            <div className="grid grid-cols-2 gap-1 text-xs">
              <CheckItem label="VWAP Reclaimed" ok={m.vwap_reclaimed} />
              <CheckItem label="Higher Low" ok={m.higher_low_formed} />
              <CheckItem label="Breakout Confirmed" ok={m.breakout_confirmed} />
              <CheckItem label="Vol Persistent" ok={(m.volume_persistence_pct || 0) >= 50} />
              <CheckItem label="Trap Safe" ok={(trap.trap_risk_score || 0) < 65} />
              <CheckItem label="R:R ≥ 2.0" ok={(et.risk_reward_ratio || 0) >= 2.0} />
            </div>
          </div>

          {/* Warnings / Next condition */}
          {et.entry_warnings?.length > 0 && (
            <div className="mt-2 space-y-1">
              {et.entry_warnings.map((w, i) => <p key={i} className="text-[11px] text-red-400/80">⚠ {w}</p>)}
            </div>
          )}
          {et.next_entry_condition && (
            <p className="text-[11px] text-yellow-400/80 mt-1">⏳ {et.next_entry_condition}</p>
          )}
          {et.reasons?.map((r, i) => <p key={i} className="text-[11px] text-gray-400 mt-1">• {r}</p>)}
        </div>

        {/* Float + Time of Day + Failure Velocity */}
        <div className="grid grid-cols-2 gap-3">
          <div className="card">
            <h4 className="text-xs font-semibold text-gray-500 mb-1">Float</h4>
            <p className="text-sm text-white capitalize">{fi.float_category?.replace('_', ' ') || '—'}</p>
            <p className="text-[11px] text-gray-500">{fi.float_shares ? `${(fi.float_shares / 1e6).toFixed(1)}M` : 'Unknown'}</p>
            {fi.dilution_risk && <p className="text-[10px] text-red-400 mt-1">⚠ Dilution risk</p>}
          </div>
          <div className="card">
            <h4 className="text-xs font-semibold text-gray-500 mb-1">Session</h4>
            <p className="text-sm text-white capitalize">{tod.session || '—'}</p>
            <p className="text-[11px] text-gray-500">Adj: {tod.probability_adjustment > 0 ? '+' : ''}{tod.probability_adjustment}</p>
          </div>
        </div>

        {/* Failure Velocity */}
        <div className="card">
          <h3 className="text-sm font-semibold text-gray-400 mb-2">Failure Velocity</h3>
          <div className="flex items-center gap-2 mb-1">
            <span className={`text-sm font-bold ${fv.is_distribution ? 'text-red-400' : 'text-emerald-400'}`}>
              {fv.velocity_score?.toFixed(0)}%
            </span>
            <span className="text-xs text-gray-500">{fv.is_distribution ? 'Distribution' : 'Healthy'}</span>
          </div>
          <p className="text-[11px] text-gray-400">{fv.reason}</p>
        </div>

        {/* Risk Warning */}
        <div className="bg-yellow-500/5 border border-yellow-500/20 rounded-lg p-3">
          <p className="text-xs text-yellow-400 flex items-center gap-1">
            <AlertTriangle className="w-3.5 h-3.5" />
            High-risk momentum setup — manage position size carefully
          </p>
        </div>
      </div>
    </div>
  )
}

// ── Alert Card ──────────────────────────────────────────────────────────────

function AlertCard({ alert }) {
  const isEntry = alert.alert_type === 'ideal_entry' || alert.alert_type === 'entry'
  const isAvoid = alert.alert_type === 'late_chase' || alert.alert_type === 'invalid_entry' || alert.alert_type === 'avoid'
  const isWatch = alert.alert_type === 'too_early' || alert.alert_type === 'waiting_for_confirmation' || alert.alert_type === 'watch'

  const borderColor = isEntry ? 'border-emerald-500/20' : isAvoid ? 'border-red-500/20' : 'border-yellow-500/20'
  const bgColor = isEntry ? 'bg-emerald-500/5' : isAvoid ? 'bg-red-500/5' : 'bg-yellow-500/5'

  return (
    <div className={`card mb-2 border ${borderColor} ${bgColor}`}>
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <Zap className={`w-4 h-4 ${isEntry ? 'text-emerald-400' : isAvoid ? 'text-red-400' : 'text-yellow-400'}`} />
          <span className="font-bold text-white text-sm">${alert.ticker}</span>
          <TimingStateBadge state={alert.timing_state || alert.state} />
          {alert.timing_score > 0 && <span className="text-[10px] text-gray-400">{alert.timing_score}/100</span>}
        </div>
        <span className={`font-bold text-sm ${isEntry ? 'text-emerald-400' : isAvoid ? 'text-red-400' : 'text-yellow-400'}`}>
          {alert.probability}%
        </span>
      </div>

      {/* Entry zone */}
      {(alert.entry_zone_low && alert.entry_zone_high) && (
        <p className="text-xs text-gray-300">Entry Zone: <span className="text-white font-medium">${alert.entry_zone_low?.toFixed(2)} – ${alert.entry_zone_high?.toFixed(2)}</span></p>
      )}

      {/* Stop + R:R */}
      <div className="flex gap-3 text-xs mt-1">
        {alert.stop_level && (
          <span className="text-red-400">Stop: ${alert.stop_level?.toFixed(2)}</span>
        )}
        {alert.risk_reward_ratio && (
          <span className={`${alert.risk_reward_ratio >= 2.0 ? 'text-emerald-400' : 'text-yellow-400'}`}>
            R:R {alert.risk_reward_ratio?.toFixed(1)}:1
          </span>
        )}
      </div>

      {/* Targets */}
      {(alert.target_1 || alert.target_2) && (
        <p className="text-xs text-gray-400 mt-1">
          Targets: {alert.target_1 && `$${alert.target_1?.toFixed(2)}`}
          {alert.target_2 && ` → $${alert.target_2?.toFixed(2)}`}
          {alert.stretch_target && ` (Stretch $${alert.stretch_target?.toFixed(2)})`}
        </p>
      )}

      {/* Reasons */}
      {alert.reasons?.map((r, i) => <p key={i} className="text-[11px] text-emerald-400/80 mt-0.5">+ {r}</p>)}

      {/* Next condition / Warnings */}
      {alert.next_entry_condition && (
        <p className="text-[10px] text-yellow-400/70 mt-1">⏳ {alert.next_entry_condition}</p>
      )}
      {alert.warnings?.map((w, i) => <p key={`w-${i}`} className="text-[10px] text-red-400/70 mt-0.5">⚠ {w}</p>)}

      {alert.risk_warning && <p className="text-[10px] text-yellow-400/70 mt-1">⚠ {alert.risk_warning}</p>}
      <p className="text-[10px] text-gray-600 mt-1">{new Date(alert.created_at).toLocaleTimeString()}</p>
    </div>
  )
}

// ── Main Page ───────────────────────────────────────────────────────────────

export default function Agentic() {
  const [candidates, setCandidates] = useState([])
  const [alerts, setAlerts] = useState([])
  const [status, setStatus] = useState(null)
  const [learning, setLearning] = useState(null)
  const [missed, setMissed] = useState([])
  const [selectedTicker, setSelectedTicker] = useState(null)
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState('')
  const [stateFilter, setStateFilter] = useState('')
  const [pennyOnly, setPennyOnly] = useState(false)
  const [activePanel, setActivePanel] = useState('candidates') // candidates, alerts, learning, missed, preNews
  const [weightLoading, setWeightLoading] = useState(false)
  const [preNewsData, setPreNewsData] = useState([])
  const [preNewsLearningData, setPreNewsLearningData] = useState(null)
  const [preNewsScanning, setPreNewsScanning] = useState(false)
  const [preNewsEvalData, setPreNewsEvalData] = useState(null)
  const [preNewsEvalLoading, setPreNewsEvalLoading] = useState(false)
  const [preNewsEvalExportLoading, setPreNewsEvalExportLoading] = useState(false)
  const [preNewsEvalExportDates, setPreNewsEvalExportDates] = useState([])
  const [preNewsReportData, setPreNewsReportData] = useState(null)
  const [preNewsReportLoading, setPreNewsReportLoading] = useState(false)
  const [preNewsAnalyzeLoading, setPreNewsAnalyzeLoading] = useState(false)
  const [qualitySepData, setQualitySepData] = useState(null)
  const [mlStatus, setMlStatus] = useState(null)
  const [mlTraining, setMlTraining] = useState(false)
  const [mlApproving, setMlApproving] = useState(false)
  // V20 News Catalyst Impact Engine state
  const [newsImpactRows, setNewsImpactRows] = useState([])
  const [newsImpactDecisionFilter, setNewsImpactDecisionFilter] = useState('')
  const [newsImpactMinScore, setNewsImpactMinScore] = useState(0)
  const [newsImpactLoading, setNewsImpactLoading] = useState(false)
  const [newsImpactSelected, setNewsImpactSelected] = useState(null)
  const [newsImpactSelectedTicker, setNewsImpactSelectedTicker] = useState('')
  const [newsImpactStats, setNewsImpactStats] = useState(null)

  // ── V17 Derived: Sorted Candidates + Best Setup ──────────────────────
  // Filter (penny-only) + sort by timing state priority then score (desc).
  // Memoized to avoid recomputing on every render.
  const sortedCandidates = useMemo(() => {
    const filtered = candidates.filter(c => !pennyOnly || (c.last_price || 0) < 5)
    const copy = [...filtered]
    copy.sort((a, b) => {
      const sA = a.entry_timing?.timing_state?.value || a.entry_timing?.timing_state || a.entry_quality
      const sB = b.entry_timing?.timing_state?.value || b.entry_timing?.timing_state || b.entry_quality
      const pA = TIMING_STATE_PRIORITY[sA] ?? 99
      const pB = TIMING_STATE_PRIORITY[sB] ?? 99
      if (pA !== pB) return pA - pB
      const scoreA = a.entry_timing?.entry_timing_score || 0
      const scoreB = b.entry_timing?.entry_timing_score || 0
      return scoreB - scoreA
    })
    return copy
  }, [candidates, pennyOnly])

  // Best setup = top IDEAL_ENTRY candidate with highest score (first in sorted list if ideal)
  const bestSetupTicker = useMemo(() => {
    for (const c of sortedCandidates) {
      const s = c.entry_timing?.timing_state?.value || c.entry_timing?.timing_state || c.entry_quality
      if (s === 'ideal_entry' || s === 'ideal') {
        return c.ticker
      }
      // sorted list has IDEAL first; if first isn't ideal, nothing qualifies
      break
    }
    return null
  }, [sortedCandidates])

  // ── Data Fetching ─────────────────────────────────────────────────────

  const fetchStatus = useCallback(async () => {
    try {
      const data = await agenticStatus()
      setStatus(data)
    } catch (e) { /* silent */ }
  }, [])

  const fetchCandidates = useCallback(async () => {
    setLoading(true)
    try {
      const data = await agenticCandidates(true, 0, stateFilter)
      setCandidates(data.candidates || [])
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [stateFilter])

  const fetchAlerts = useCallback(async () => {
    try {
      const data = await agenticAlerts(30)
      setAlerts(data.alerts || [])
    } catch (e) { /* silent */ }
  }, [])

  const fetchLearning = useCallback(async () => {
    try {
      const data = await agenticLearningStats()
      setLearning(data)
    } catch (e) { /* silent */ }
  }, [])

  useEffect(() => {
    fetchStatus()
    fetchCandidates()
    fetchAlerts()
  }, [fetchStatus, fetchCandidates, fetchAlerts])

  // ── Actions ───────────────────────────────────────────────────────────

  const handleScan = async () => {
    setScanning(true)
    setError('')
    try {
      const data = await agenticScan()
      setCandidates(data.candidates || [])
      setAlerts((prev) => [...data.alerts, ...prev].slice(0, 100))
      fetchStatus()
    } catch (e) {
      setError(e.message)
    } finally {
      setScanning(false)
    }
  }

  const handleRefresh = async (ticker) => {
    try {
      await agenticRefreshCandidate(ticker)
      fetchCandidates()
    } catch (e) { /* silent */ }
  }

  const handleDeactivate = async (ticker) => {
    try {
      await agenticDeactivate(ticker)
      fetchCandidates()
      if (selectedTicker === ticker) {
        setSelectedTicker(null)
        setDetail(null)
      }
    } catch (e) { /* silent */ }
  }

  const handleSelect = async (ticker) => {
    setSelectedTicker(ticker)
    try {
      const data = await agenticCandidateDetail(ticker)
      setDetail(data)
    } catch (e) {
      setError(e.message)
    }
  }

  const handleMissed = async () => {
    try {
      const data = await agenticMissedOpportunities()
      setMissed(data.missed || [])
      setActivePanel('missed')
    } catch (e) {
      setError(e.message)
    }
  }

  const fetchPreNews = useCallback(async () => {
    try {
      const data = await preNewsAnomalies(0, true)
      setPreNewsData(data.anomalies || [])
    } catch (e) { /* silent */ }
  }, [])

  const handlePreNewsScan = async () => {
    setPreNewsScanning(true)
    try {
      const data = await preNewsScan()
      setPreNewsData(data.anomalies || [])
    } catch (e) {
      setError(e.message)
    } finally {
      setPreNewsScanning(false)
    }
  }

  const fetchPreNewsLearning = useCallback(async () => {
    try {
      const data = await preNewsLearning()
      setPreNewsLearningData(data)
    } catch (e) { /* silent */ }
  }, [])

  const fetchPreNewsEval = useCallback(async () => {
    setPreNewsEvalLoading(true)
    try {
      const data = await preNewsEvaluation()
      setPreNewsEvalData(data)
    } catch (e) { /* silent */ }
    finally { setPreNewsEvalLoading(false) }
  }, [])

  const handleExportToday = async () => {
    const today = new Date().toISOString().slice(0, 10)
    setPreNewsEvalExportLoading(true)
    try {
      const result = await preNewsExportEvaluation(today)
      if (result && result.csv_path) {
        setError(`Export complete: ${result.total_snapshots} snapshots → ${result.csv_path}`)
      }
    } catch (e) {
      setError('Export failed')
    } finally {
      setPreNewsEvalExportLoading(false)
      try {
        const list = await preNewsExportList()
        setPreNewsEvalExportDates(list.dates || [])
      } catch (e) { /* silent */ }
    }
  }

  const handleAnalyze = async () => {
    setPreNewsAnalyzeLoading(true)
    try {
      const result = await preNewsAnalyze()
      setError(`Analysis complete: ${result.usable_detections} usable detections, clean success ${result.clean_success_rate}%`)
      await handleFetchReport()
    } catch (e) {
      setError('Analysis failed')
    } finally {
      setPreNewsAnalyzeLoading(false)
    }
  }

  const handleFetchReport = async () => {
    setPreNewsReportLoading(true)
    try {
      const data = await preNewsReport()
      setPreNewsReportData(data)
    } catch (e) { /* silent */ }
    finally { setPreNewsReportLoading(false) }
  }

  const fetchQualitySep = useCallback(async () => {
    try {
      const data = await qualitySeparatorReport()
      setQualitySepData(data)
    } catch (e) { /* silent */ }
  }, [])

  const fetchMLStatus = useCallback(async () => {
    try {
      const data = await mlStatus()
      setMlStatus(data)
    } catch (e) { /* silent */ }
  }, [])

  // ── V20 News Catalyst Impact Engine ──────────────────────────────────
  const fetchNewsImpact = useCallback(async () => {
    setNewsImpactLoading(true)
    try {
      const data = await newsImpactCandidates(newsImpactMinScore, newsImpactDecisionFilter)
      setNewsImpactRows(data.candidates || [])
    } catch (e) {
      setError(e.message)
    } finally {
      setNewsImpactLoading(false)
    }
  }, [newsImpactMinScore, newsImpactDecisionFilter])

  const fetchNewsImpactStats = useCallback(async () => {
    try {
      const data = await newsImpactLearningSummary()
      setNewsImpactStats(data)
    } catch (e) { /* silent */ }
  }, [])

  const openNewsImpactDetail = useCallback(async (ticker) => {
    setNewsImpactSelectedTicker(ticker)
    try {
      const data = await newsImpactDetail(ticker)
      setNewsImpactSelected(data)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  const handleMLTrain = async () => {
    setMlTraining(true)
    try {
      const data = await mlTrain()
      setMlStatus(prev => ({ ...prev, current_version: data.version, current_approved: false }))
    } catch (e) {
      setError(e.message)
    } finally {
      setMlTraining(false)
    }
  }

  const handleMLApprove = async (version) => {
    setMlApproving(true)
    try {
      await mlApprove(version, 'manual')
      await fetchMLStatus()
    } catch (e) {
      setError(e.message)
    } finally {
      setMlApproving(false)
    }
  }

  const handleApplyWeights = async () => {
    setWeightLoading(true)
    try {
      const data = await agenticApplyWeights()
      setLearning(data)
      setError('')
    } catch (e) {
      setError(e.message)
    } finally {
      setWeightLoading(false)
    }
  }

  const handleRollbackWeights = async () => {
    setWeightLoading(true)
    try {
      const data = await agenticRollbackWeights()
      setLearning(data)
      setError('')
    } catch (e) {
      setError(e.message)
    } finally {
      setWeightLoading(false)
    }
  }

  // ── Render ────────────────────────────────────────────────────────────

  return (
    <div className="max-w-[1600px] mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-oracle-600/20 rounded-lg">
            <Zap className="w-6 h-6 text-oracle-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white">Agentic Catalyst Momentum</h1>
            <p className="text-sm text-gray-500">Discover → Classify → Time → Alert</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {status && (
            <div className="text-xs text-gray-500 mr-4">
              {status.active_candidates} active · {status.total_alerts} alerts
            </div>
          )}
          <button
            onClick={handleScan}
            disabled={scanning}
            className="flex items-center gap-2 px-4 py-2 bg-oracle-600 hover:bg-oracle-700 text-white rounded-lg text-sm font-medium disabled:opacity-50 transition-colors"
          >
            {scanning ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
            {scanning ? 'Scanning…' : 'Run Scan'}
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-sm text-red-400">
          {error}
          <button onClick={() => setError('')} className="ml-2 text-red-300 hover:text-white">&times;</button>
        </div>
      )}

      {/* Tab Bar */}
      <div className="flex gap-1 mb-4 bg-gray-800/50 p-1 rounded-lg w-fit">
        {[
          { key: 'candidates', label: 'Candidates', icon: Eye, count: candidates.length },
          { key: 'alerts', label: 'Alerts', icon: Zap, count: alerts.length },
          { key: 'newsImpact', label: 'News Impact', icon: Newspaper, count: newsImpactRows.length },
          { key: 'preNews', label: 'Pre-News', icon: Volume2, count: preNewsData.length },
          { key: 'preNewsEval', label: 'Eval', icon: Activity, count: preNewsEvalData?.filtered_count },
          { key: 'learning', label: 'Learning', icon: Brain },
          { key: 'mlAdvisory', label: 'ML', icon: Brain },
          { key: 'qualitySep', label: 'Quality', icon: Shield },
          { key: 'missed', label: 'Missed', icon: AlertTriangle, count: missed.length },
        ].map(({ key, label, icon: Icon, count }) => (
          <button
            key={key}
            onClick={() => { setActivePanel(key); if (key === 'learning') fetchLearning(); if (key === 'missed') handleMissed(); if (key === 'preNews') { fetchPreNews(); fetchPreNewsLearning(); } if (key === 'preNewsEval') { fetchPreNewsEval(); } if (key === 'qualitySep') fetchQualitySep(); if (key === 'mlAdvisory') fetchMLStatus(); if (key === 'newsImpact') { fetchNewsImpact(); fetchNewsImpactStats(); } }}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition-colors ${
              activePanel === key ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-white'
            }`}
          >
            <Icon className="w-3.5 h-3.5" />
            {label}
            {count !== undefined && <span className="text-[10px] ml-1 opacity-60">({count})</span>}
          </button>
        ))}
      </div>

      <div className="flex gap-4">
        {/* Main Panel */}
        <div className="flex-1 min-w-0">

          {/* Candidates Table */}
          {activePanel === 'candidates' && (
            <div className="card p-0 overflow-hidden">
              {/* State Filters */}
              <div className="px-4 py-2 border-b border-gray-800 flex items-center gap-2 flex-wrap">
                <span className="text-xs text-gray-500">Filter:</span>
                {['', 'consolidation', 'second_leg_forming', 'continuation_confirmed', 'spike_pullback', 'failed'].map((s) => (
                  <button
                    key={s}
                    onClick={() => setStateFilter(s)}
                    className={`text-[11px] px-2 py-0.5 rounded transition-colors ${
                      stateFilter === s ? 'bg-oracle-500/20 text-oracle-400 border border-oracle-500/40' : 'text-gray-500 hover:text-white'
                    }`}
                  >
                    {s === '' ? 'All' : STATE_LABELS[s] || s}
                  </button>
                ))}
                <div className="w-px h-3 bg-gray-700 mx-1" />
                <button
                  onClick={() => setPennyOnly(v => !v)}
                  className={`text-[11px] px-2 py-0.5 rounded transition-colors border ${
                    pennyOnly ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/40' : 'text-gray-500 hover:text-white border-transparent'
                  }`}
                >
                  Penny Stocks (&lt;$5)
                </button>
              </div>

              {/* Header */}
              <div className="grid grid-cols-12 gap-2 px-4 py-2 border-b border-gray-800 text-[11px] text-gray-500 uppercase tracking-wider">
                <div className="col-span-2">Ticker / Catalyst</div>
                <div className="col-span-1">Price</div>
                <div className="col-span-2">Probability</div>
                <div className="col-span-1">Trap</div>
                <div className="col-span-3">Entry Timing / Zone / R:R</div>
                <div className="col-span-1">Signals</div>
                <div className="col-span-1">Quality</div>
                <div className="col-span-1 text-right">Actions</div>
              </div>

              {loading ? (
                <div className="px-4 py-8 text-center text-gray-500 text-sm">Loading candidates…</div>
              ) : sortedCandidates.length === 0 ? (
                <div className="px-4 py-8 text-center text-gray-500 text-sm">
                  No candidates found. Click <span className="text-oracle-400">Run Scan</span> to discover.
                </div>
              ) : (
                sortedCandidates.map((c, idx) => (
                  <CandidateRow
                    key={`${c.id || c.ticker}-${idx}`}
                    c={c}
                    onSelect={handleSelect}
                    onRefresh={handleRefresh}
                    onDeactivate={handleDeactivate}
                    isBestSetup={bestSetupTicker === c.ticker}
                  />
                ))
              )}
            </div>
          )}

          {/* Alerts Panel — V17 grouped by type */}
          {activePanel === 'alerts' && (
            <div>
              {alerts.length === 0 ? (
                <div className="card text-center text-gray-500 text-sm py-8">No alerts yet. Run a scan to generate candidates.</div>
              ) : (
                <div className="space-y-4">
                  {(() => {
                    const entryAlerts = alerts.filter(a => a.alert_type === 'ideal_entry' || a.alert_type === 'entry')
                    const watchAlerts = alerts.filter(a => a.alert_type === 'too_early' || a.alert_type === 'waiting_for_confirmation' || a.alert_type === 'watch')
                    const avoidAlerts = alerts.filter(a => a.alert_type === 'late_chase' || a.alert_type === 'invalid_entry' || a.alert_type === 'avoid')
                    return (
                      <>
                        {entryAlerts.length > 0 && (
                          <div>
                            <div className="flex items-center gap-2 mb-2">
                              <span className="text-emerald-400 text-base font-bold">🎯 ENTRY</span>
                              <span className="text-emerald-500/60 text-xs">({entryAlerts.length}) — ACT NOW</span>
                            </div>
                            <div className="space-y-2">
                              {entryAlerts.map((a, i) => <AlertCard key={a.id || `e-${i}`} alert={a} />)}
                            </div>
                          </div>
                        )}
                        {watchAlerts.length > 0 && (
                          <div>
                            <div className="flex items-center gap-2 mb-2 mt-4">
                              <span className="text-yellow-400 text-base font-bold">👁 WATCH</span>
                              <span className="text-yellow-500/60 text-xs">({watchAlerts.length}) — wait for confirmation</span>
                            </div>
                            <div className="space-y-2">
                              {watchAlerts.map((a, i) => <AlertCard key={a.id || `w-${i}`} alert={a} />)}
                            </div>
                          </div>
                        )}
                        {avoidAlerts.length > 0 && (
                          <div>
                            <div className="flex items-center gap-2 mb-2 mt-4">
                              <span className="text-red-400 text-base font-bold">🚫 AVOID</span>
                              <span className="text-red-500/60 text-xs">({avoidAlerts.length}) — do not chase</span>
                            </div>
                            <div className="space-y-2">
                              {avoidAlerts.map((a, i) => <AlertCard key={a.id || `a-${i}`} alert={a} />)}
                            </div>
                          </div>
                        )}
                      </>
                    )
                  })()}
                </div>
              )}
            </div>
          )}

          {/* V20 News Catalyst Impact Panel */}
          {activePanel === 'newsImpact' && (
            <div className="space-y-3">
              <div className="card">
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <h3 className="text-sm font-semibold text-gray-300 flex items-center gap-2">
                    <Newspaper className="w-4 h-4 text-orange-400" /> News Catalyst Impact Engine
                    <span className="text-[10px] font-normal text-gray-500">V20</span>
                  </h3>
                  <div className="flex items-center gap-2">
                    <select
                      value={newsImpactDecisionFilter}
                      onChange={(e) => setNewsImpactDecisionFilter(e.target.value)}
                      className="bg-gray-800 border border-gray-700 text-gray-200 text-xs rounded px-2 py-1"
                    >
                      <option value="">All decisions</option>
                      <option value="EXPLOSIVE">Explosive</option>
                      <option value="HIGH_IMPACT">High Impact</option>
                      <option value="TRADEABLE">Tradeable</option>
                      <option value="WATCH">Watch</option>
                      <option value="DANGEROUS_TRAP">Dangerous Trap</option>
                      <option value="IGNORE">Ignore</option>
                    </select>
                    <select
                      value={newsImpactMinScore}
                      onChange={(e) => setNewsImpactMinScore(Number(e.target.value))}
                      className="bg-gray-800 border border-gray-700 text-gray-200 text-xs rounded px-2 py-1"
                    >
                      <option value={0}>Any score</option>
                      <option value={50}>≥ 50</option>
                      <option value={70}>≥ 70</option>
                      <option value={85}>≥ 85</option>
                    </select>
                    <button
                      onClick={fetchNewsImpact}
                      disabled={newsImpactLoading}
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-orange-600 hover:bg-orange-500 disabled:opacity-50 text-white text-xs font-medium rounded"
                    >
                      {newsImpactLoading ? <RefreshCw className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                      Refresh
                    </button>
                  </div>
                </div>
                {newsImpactStats && (
                  <div className="mt-3 grid grid-cols-3 gap-2">
                    <div className="bg-gray-800/50 rounded p-2 text-center">
                      <p className="text-lg font-bold text-white">{newsImpactStats.total_outcomes ?? 0}</p>
                      <p className="text-[10px] text-gray-500">Outcomes Tracked</p>
                    </div>
                    <div className="bg-gray-800/50 rounded p-2 text-center">
                      <p className="text-lg font-bold text-emerald-400">{newsImpactStats.completed_outcomes ?? 0}</p>
                      <p className="text-[10px] text-gray-500">Completed</p>
                    </div>
                    <div className="bg-gray-800/50 rounded p-2 text-center">
                      <p className={`text-lg font-bold ${newsImpactStats.ready_for_calibration ? 'text-emerald-400' : 'text-yellow-400'}`}>
                        {newsImpactStats.ready_for_calibration ? 'YES' : `${newsImpactStats.completed_outcomes ?? 0}/${newsImpactStats.min_required ?? 100}`}
                      </p>
                      <p className="text-[10px] text-gray-500">Calibration Ready</p>
                    </div>
                  </div>
                )}
              </div>

              {newsImpactLoading && newsImpactRows.length === 0 ? (
                <div className="card text-center text-gray-500 text-sm py-8">Loading news impact evaluations…</div>
              ) : newsImpactRows.length === 0 ? (
                <div className="card text-center text-gray-500 text-sm py-8">
                  No active candidates have a news impact evaluation yet. Click <span className="text-oracle-400">Run Scan</span> to populate.
                </div>
              ) : (
                <div className="space-y-2">
                  {newsImpactRows.map((row) => {
                    const decision = row.news_decision
                    const decisionColor = decision === 'EXPLOSIVE' ? 'bg-purple-500/15 text-purple-300 border-purple-500/40'
                      : decision === 'HIGH_IMPACT' ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40'
                      : decision === 'TRADEABLE' ? 'bg-blue-500/15 text-blue-300 border-blue-500/40'
                      : decision === 'WATCH' ? 'bg-yellow-500/15 text-yellow-300 border-yellow-500/40'
                      : decision === 'DANGEROUS_TRAP' ? 'bg-red-500/15 text-red-300 border-red-500/40'
                      : 'bg-gray-700/40 text-gray-400 border-gray-600/40'
                    const m = row.estimated_move_range || {}
                    const isBearish = (m.bearish_move_pct || 0) < 0 && !(m.bullish_move_pct > 0)
                    const moveLabel = isBearish
                      ? `${m.conservative_move_pct?.toFixed?.(0) ?? 0}% / ${m.bearish_move_pct?.toFixed?.(0) ?? 0}%`
                      : `+${m.conservative_move_pct?.toFixed?.(0) ?? 0}% / +${m.bullish_move_pct?.toFixed?.(0) ?? 0}% / +${m.extreme_squeeze_pct?.toFixed?.(0) ?? 0}%`
                    return (
                      <div
                        key={row.ticker}
                        onClick={() => openNewsImpactDetail(row.ticker)}
                        className={`card cursor-pointer hover:border-orange-500/40 transition-colors ${newsImpactSelectedTicker === row.ticker ? 'border-orange-500/60' : ''}`}
                      >
                        <div className="flex items-center justify-between gap-2 flex-wrap mb-2">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-base font-bold text-white">{row.ticker}</span>
                            <span className={`text-[10px] font-medium px-2 py-0.5 rounded border ${decisionColor}`}>
                              {decision.replace('_', ' ')}
                            </span>
                            {row.trap_warning && (
                              <span className="text-[10px] font-medium px-2 py-0.5 rounded bg-red-500/20 text-red-300 border border-red-500/40 flex items-center gap-1">
                                <AlertTriangle className="w-3 h-3" /> Trap
                              </span>
                            )}
                            {row.is_dilution && (
                              <span className="text-[10px] font-medium px-2 py-0.5 rounded bg-orange-500/15 text-orange-300 border border-orange-500/40">Dilution</span>
                            )}
                            {row.is_parabolic && (
                              <span className="text-[10px] font-medium px-2 py-0.5 rounded bg-yellow-500/15 text-yellow-300 border border-yellow-500/40">Parabolic</span>
                            )}
                            {row.pre_news_accumulation_detected && (
                              <span className="text-[10px] font-medium px-2 py-0.5 rounded bg-purple-500/15 text-purple-300 border border-purple-500/40">Pre-News</span>
                            )}
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="text-xs text-gray-400">{row.catalyst_type}</span>
                            <span className={`text-sm font-bold ${row.news_impact_score >= 80 ? 'text-emerald-400' : row.news_impact_score >= 60 ? 'text-yellow-400' : 'text-gray-400'}`}>
                              {row.news_impact_score}
                            </span>
                          </div>
                        </div>
                        <p className="text-xs text-gray-300 mb-2 line-clamp-2">{row.headline}</p>
                        <div className="flex flex-wrap items-center gap-3 text-[11px] text-gray-500">
                          <span><Flame className="w-3 h-3 inline text-orange-400 mr-0.5" />Move: <span className="text-gray-300">{moveLabel}</span></span>
                          {row.rvol_at_detection > 0 && <span>RVOL {row.rvol_at_detection.toFixed(1)}x</span>}
                          {row.float_shares_at_detection && <span>Float {(row.float_shares_at_detection/1e6).toFixed(1)}M</span>}
                          {row.market_cap_at_detection && <span>Cap ${(row.market_cap_at_detection/1e6).toFixed(0)}M</span>}
                          <span className="text-orange-400">→ {row.oracle_action.replace('_', ' ')}</span>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}

              {/* Detail panel */}
              {newsImpactSelected && (
                <div className="card border-orange-500/40">
                  <div className="flex items-center justify-between mb-3">
                    <h4 className="text-sm font-semibold text-orange-300 flex items-center gap-2">
                      <Newspaper className="w-4 h-4" /> {newsImpactSelected.ticker} — Detail
                    </h4>
                    <button
                      onClick={() => { setNewsImpactSelected(null); setNewsImpactSelectedTicker('') }}
                      className="text-gray-500 hover:text-white text-xs"
                    >Close</button>
                  </div>
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                    <div className="space-y-2">
                      <div>
                        <p className="text-[10px] uppercase tracking-wider text-gray-500">Summary</p>
                        <p className="text-xs text-gray-200">{newsImpactSelected.summary}</p>
                      </div>
                      <div>
                        <p className="text-[10px] uppercase tracking-wider text-gray-500">Why it matters</p>
                        <p className="text-xs text-gray-300">{newsImpactSelected.why_it_matters}</p>
                      </div>
                      <div>
                        <p className="text-[10px] uppercase tracking-wider text-emerald-400">Bull Case</p>
                        <p className="text-xs text-gray-300">{newsImpactSelected.bull_case}</p>
                      </div>
                      <div>
                        <p className="text-[10px] uppercase tracking-wider text-red-400">Bear Case</p>
                        <p className="text-xs text-gray-300">{newsImpactSelected.bear_case}</p>
                      </div>
                    </div>
                    <div className="space-y-2">
                      {newsImpactSelected.impact_reasons?.length > 0 && (
                        <div>
                          <p className="text-[10px] uppercase tracking-wider text-emerald-400">Impact Reasons</p>
                          <ul className="text-xs text-gray-300 space-y-0.5">
                            {newsImpactSelected.impact_reasons.map((r, i) => <li key={i}>• {r}</li>)}
                          </ul>
                        </div>
                      )}
                      {newsImpactSelected.impact_warnings?.length > 0 && (
                        <div>
                          <p className="text-[10px] uppercase tracking-wider text-yellow-400">Impact Warnings</p>
                          <ul className="text-xs text-gray-300 space-y-0.5">
                            {newsImpactSelected.impact_warnings.map((w, i) => <li key={i}>• {w}</li>)}
                          </ul>
                        </div>
                      )}
                      {newsImpactSelected.key_risks?.length > 0 && (
                        <div>
                          <p className="text-[10px] uppercase tracking-wider text-red-400">Key Risks</p>
                          <ul className="text-xs text-gray-300 space-y-0.5">
                            {newsImpactSelected.key_risks.map((r, i) => <li key={i}>• {r}</li>)}
                          </ul>
                        </div>
                      )}
                      {newsImpactSelected.related_pre_news && (
                        <div className="bg-purple-500/10 border border-purple-500/30 rounded p-2">
                          <p className="text-[10px] uppercase tracking-wider text-purple-300">Pre-News Linkage</p>
                          <p className="text-xs text-gray-300">
                            Suspicion {newsImpactSelected.related_pre_news.suspicion_score?.toFixed?.(0) ?? '—'} ·
                            RVOL {newsImpactSelected.related_pre_news.rvol?.toFixed?.(1) ?? '—'}x ·
                            {newsImpactSelected.related_pre_news.anomaly_type} ·
                            state {newsImpactSelected.related_pre_news.state}
                          </p>
                        </div>
                      )}
                      {newsImpactSelected.historical_outcomes?.length > 0 && (
                        <div className="bg-gray-800/40 rounded p-2">
                          <p className="text-[10px] uppercase tracking-wider text-gray-400">Historical for {newsImpactSelected.catalyst_type}</p>
                          {newsImpactSelected.historical_outcomes.map((h, i) => (
                            <p key={i} className="text-xs text-gray-300">
                              n={h.sample_size} · avg {h.avg_move_pct}% · win {h.win_rate}% · trap {h.trap_rate}%
                            </p>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                  {newsImpactSelected.estimated_move_range && (
                    <div className="mt-3 pt-3 border-t border-gray-800 flex flex-wrap items-center gap-3 text-xs">
                      <span className="text-gray-500 uppercase tracking-wider text-[10px]">Estimated Move</span>
                      <span className="text-gray-300">cons {newsImpactSelected.estimated_move_range.conservative_move_pct?.toFixed?.(1)}%</span>
                      <span className="text-emerald-300">bull {newsImpactSelected.estimated_move_range.bullish_move_pct?.toFixed?.(1)}%</span>
                      <span className="text-purple-300">extreme {newsImpactSelected.estimated_move_range.extreme_squeeze_pct?.toFixed?.(1)}%</span>
                      {newsImpactSelected.estimated_move_range.bearish_move_pct < 0 && (
                        <span className="text-red-300">bearish {newsImpactSelected.estimated_move_range.bearish_move_pct?.toFixed?.(1)}%</span>
                      )}
                      <span className="text-gray-500 italic">{newsImpactSelected.estimated_move_range.rationale}</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Learning Panel */}
          {activePanel === 'learning' && (
            <div className="card">
              <h3 className="text-sm font-semibold text-gray-400 mb-4 flex items-center gap-2"><Brain className="w-4 h-4" /> Self-Learning Engine</h3>
              {learning && learning.stats ? (
                <div className="space-y-4">
                  <div className="grid grid-cols-4 gap-4">
                    <div className="bg-gray-800/50 rounded-lg p-3 text-center">
                      <p className="text-2xl font-bold text-white">{learning.stats.total}</p>
                      <p className="text-xs text-gray-500">Total Outcomes</p>
                    </div>
                    <div className="bg-gray-800/50 rounded-lg p-3 text-center">
                      <p className="text-2xl font-bold text-emerald-400">{learning.stats.win_rate}%</p>
                      <p className="text-xs text-gray-500">Win Rate</p>
                    </div>
                    <div className="bg-gray-800/50 rounded-lg p-3 text-center">
                      <p className="text-2xl font-bold text-green-400">{learning.stats.avg_mfe_pct}%</p>
                      <p className="text-xs text-gray-500">Avg MFE</p>
                    </div>
                    <div className="bg-gray-800/50 rounded-lg p-3 text-center">
                      <p className="text-2xl font-bold text-red-400">{learning.stats.avg_mae_pct}%</p>
                      <p className="text-xs text-gray-500">Avg MAE</p>
                    </div>
                  </div>
                  {!learning.stats.sample_size_ok && (
                    <p className="text-xs text-yellow-400 bg-yellow-500/10 px-3 py-2 rounded">
                      Need {20 - (learning.stats.total || 0)} more outcomes before weight adjustment is available
                    </p>
                  )}
                  <div>
                    <h4 className="text-xs text-gray-500 font-semibold mb-2">Current Weights (v{learning.current_weights.version})</h4>
                    <div className="grid grid-cols-2 gap-2">
                      {Object.entries(learning.current_weights).filter(([k]) => k.endsWith('_w')).map(([k, v]) => (
                        <div key={k} className="flex items-center justify-between text-xs">
                          <span className="text-gray-400 capitalize">{k.replace('_w', '').replace(/_/g, ' ')}</span>
                          <span className="text-white font-medium">{(v * 100).toFixed(0)}%</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* ── Learning Insights ─────────────────────────────── */}
                  {learning.insights && learning.insights.total_samples > 0 && (
                    <div className="space-y-4 border-t border-gray-700 pt-4">
                      <h4 className="text-xs text-gray-400 font-semibold flex items-center gap-2">
                        <Lightbulb className="w-3 h-3" /> Learning Insights
                      </h4>

                      {/* Warnings */}
                      {learning.insights.warnings && learning.insights.warnings.length > 0 && (
                        <div className="space-y-2">
                          {learning.insights.warnings.map((w, i) => (
                            <div key={`warn-${i}`} className="flex items-start gap-2 bg-yellow-500/10 text-yellow-400 text-xs px-3 py-2 rounded">
                              <AlertCircle className="w-3 h-3 mt-0.5 shrink-0" />
                              <span>{w}</span>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Best Conditions */}
                      {learning.insights.best_conditions && learning.insights.best_conditions.length > 0 && (
                        <div>
                          <h5 className="text-xs text-emerald-400 font-semibold mb-2 flex items-center gap-1">
                            <TrendingUp className="w-3 h-3" /> Best Performing Conditions
                          </h5>
                          <div className="space-y-1.5">
                            {learning.insights.best_conditions.slice(0, 5).map((c, i) => (
                              <div key={`best-${i}`} className="flex items-center justify-between bg-emerald-500/10 rounded px-3 py-2">
                                <div className="text-xs">
                                  <span className="text-gray-300 capitalize">{c.type.replace(/_/g, ' ')}:</span>
                                  <span className="text-white font-medium ml-1">{c.name.replace(/_/g, ' ')}</span>
                                </div>
                                <div className="flex items-center gap-2">
                                  <span className="text-emerald-400 text-xs font-bold">{c.win_rate}% WR</span>
                                  <span className="text-gray-500 text-[10px]">n={c.count}</span>
                                  <span className={`text-[10px] px-1.5 py-0.5 rounded ${c.confidence === 'HIGH' ? 'bg-emerald-500/20 text-emerald-400' : c.confidence === 'MEDIUM' ? 'bg-yellow-500/20 text-yellow-400' : 'bg-gray-500/20 text-gray-400'}`}>
                                    {c.confidence}
                                  </span>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Worst Conditions */}
                      {learning.insights.worst_conditions && learning.insights.worst_conditions.length > 0 && (
                        <div>
                          <h5 className="text-xs text-red-400 font-semibold mb-2 flex items-center gap-1">
                            <TrendingDown className="w-3 h-3" /> Conditions to Avoid
                          </h5>
                          <div className="space-y-1.5">
                            {learning.insights.worst_conditions.slice(0, 5).map((c, i) => (
                              <div key={`worst-${i}`} className="flex items-center justify-between bg-red-500/10 rounded px-3 py-2">
                                <div className="text-xs">
                                  <span className="text-gray-300 capitalize">{c.type.replace(/_/g, ' ')}:</span>
                                  <span className="text-white font-medium ml-1">{c.name.replace(/_/g, ' ')}</span>
                                </div>
                                <div className="flex items-center gap-2">
                                  <span className="text-red-400 text-xs font-bold">{c.win_rate}% WR</span>
                                  <span className="text-gray-500 text-[10px]">n={c.count}</span>
                                  <span className={`text-[10px] px-1.5 py-0.5 rounded ${c.confidence === 'HIGH' ? 'bg-emerald-500/20 text-emerald-400' : c.confidence === 'MEDIUM' ? 'bg-yellow-500/20 text-yellow-400' : 'bg-gray-500/20 text-gray-400'}`}>
                                    {c.confidence}
                                  </span>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Threshold Recommendations */}
                      {learning.insights.threshold_recommendations && learning.insights.threshold_recommendations.length > 0 && (
                        <div>
                          <h5 className="text-xs text-blue-400 font-semibold mb-2 flex items-center gap-1">
                            <CheckCircle2 className="w-3 h-3" /> Recommended Adjustments
                          </h5>
                          <div className="space-y-2">
                            {learning.insights.threshold_recommendations.map((rec, i) => (
                              <div key={`rec-${i}`} className="bg-gray-800/50 rounded p-3 space-y-1.5">
                                <div className="flex items-center justify-between">
                                  <span className="text-xs text-white font-semibold capitalize">{rec.feature.replace(/_/g, ' ')}</span>
                                  <span className={`text-[10px] px-2 py-0.5 rounded font-semibold ${rec.confidence === 'HIGH' ? 'bg-emerald-500/20 text-emerald-400' : rec.confidence === 'MEDIUM' ? 'bg-yellow-500/20 text-yellow-400' : 'bg-gray-500/20 text-gray-400'}`}>
                                    {rec.confidence} CONFIDENCE
                                  </span>
                                </div>
                                <div className="flex items-center gap-2 text-[11px]">
                                  <span className="text-gray-500">Current:</span>
                                  <span className="text-gray-300">{rec.current_threshold}</span>
                                  <span className="text-gray-600">→</span>
                                  <span className="text-blue-400 font-medium">{rec.proposed_threshold}</span>
                                </div>
                                <p className="text-[11px] text-gray-400 leading-relaxed">{rec.evidence}</p>
                                <p className="text-[11px] text-emerald-400">{rec.expected_impact}</p>
                                <p className="text-[10px] text-gray-500 italic">{rec.rationale}</p>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {learning.stats.sample_size_ok && (
                    <div className="flex gap-2">
                      <button
                        onClick={handleApplyWeights}
                        disabled={weightLoading}
                        className="flex-1 bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-700 text-white text-xs font-semibold py-2 px-3 rounded transition"
                      >
                        {weightLoading ? 'Applying…' : 'Apply Suggested Weights'}
                      </button>
                      {learning.current_weights.version > 1 && (
                        <button
                          onClick={handleRollbackWeights}
                          disabled={weightLoading}
                          className="bg-gray-700 hover:bg-gray-600 disabled:bg-gray-800 text-gray-300 text-xs font-semibold py-2 px-3 rounded transition"
                        >
                          Rollback
                        </button>
                      )}
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-gray-500 text-sm">Loading learning data…</p>
              )}
            </div>
          )}

          {/* ML Advisory Panel */}
          {activePanel === 'mlAdvisory' && (
            <div className="card">
              <h3 className="text-sm font-semibold text-gray-400 mb-4 flex items-center gap-2">
                <Brain className="w-4 h-4" /> ML Advisory Engine
              </h3>
              {mlStatus ? (
                <div className="space-y-4">
                  <div className="grid grid-cols-3 gap-4">
                    <div className="bg-gray-800/50 rounded-lg p-3 text-center">
                      <p className="text-lg font-bold text-white">{mlStatus.current_version || 'None'}</p>
                      <p className="text-xs text-gray-500">Current Version</p>
                    </div>
                    <div className="bg-gray-800/50 rounded-lg p-3 text-center">
                      <p className={`text-lg font-bold ${mlStatus.current_is_live ? 'text-emerald-400' : 'text-yellow-400'}`}>
                        {mlStatus.current_is_live ? 'LIVE' : 'SHADOW'}
                      </p>
                      <p className="text-xs text-gray-500">Status</p>
                    </div>
                    <div className="bg-gray-800/50 rounded-lg p-3 text-center">
                      <p className="text-lg font-bold text-white">{mlStatus.total_versions || 0}</p>
                      <p className="text-xs text-gray-500">Total Versions</p>
                    </div>
                  </div>

                  <div className="flex gap-2">
                    <button
                      onClick={handleMLTrain}
                      disabled={mlTraining}
                      className="flex items-center gap-1.5 px-3 py-2 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white rounded text-xs font-medium transition-colors"
                    >
                      {mlTraining ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Brain className="w-3 h-3" />}
                      {mlTraining ? 'Training…' : 'Train Model'}
                    </button>
                    {mlStatus.versions?.length > 0 && !mlStatus.current_is_live && (
                      <button
                        onClick={() => handleMLApprove(mlStatus.versions[0].version)}
                        disabled={mlApproving}
                        className="flex items-center gap-1.5 px-3 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded text-xs font-medium transition-colors"
                      >
                        {mlApproving ? <RefreshCw className="w-3 h-3 animate-spin" /> : <CheckCircle2 className="w-3 h-3" />}
                        Approve Latest
                      </button>
                    )}
                  </div>

                  {mlStatus.versions?.length > 0 && (
                    <div>
                      <h4 className="text-xs text-gray-500 font-semibold mb-2">Recent Versions</h4>
                      <div className="space-y-1">
                        {mlStatus.versions.map((v) => (
                          <div key={v.version} className="flex items-center justify-between text-xs bg-gray-800/30 rounded px-3 py-2">
                            <div className="flex items-center gap-2">
                              <span className="font-mono text-gray-300">{v.version}</span>
                              {v.is_live && <span className="text-[10px] bg-emerald-500/15 text-emerald-400 px-1.5 py-0.5 rounded">LIVE</span>}
                              {v.approved && !v.is_live && <span className="text-[10px] bg-blue-500/15 text-blue-400 px-1.5 py-0.5 rounded">APPROVED</span>}
                            </div>
                            <div className="flex items-center gap-3 text-gray-500">
                              <span>AUC: {v.auc_roc?.toFixed(3) || '—'}</span>
                              <span>{v.created_at?.split('T')[0]}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="space-y-3">
                  <p className="text-gray-500 text-sm">No ML model trained yet.</p>
                  <button
                    onClick={handleMLTrain}
                    disabled={mlTraining}
                    className="flex items-center gap-1.5 px-3 py-2 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white rounded text-xs font-medium transition-colors"
                  >
                    {mlTraining ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Brain className="w-3 h-3" />}
                    {mlTraining ? 'Training…' : 'Train Model'}
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Pre-News Volume Anomaly Panel */}
          {activePanel === 'preNews' && (
            <div>
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-gray-300 flex items-center gap-2">
                  <Volume2 className="w-4 h-4 text-purple-400" /> Pre-News Volume Anomalies
                </h3>
                <button
                  onClick={handlePreNewsScan}
                  disabled={preNewsScanning}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white rounded text-xs font-medium transition-colors"
                >
                  {preNewsScanning ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Search className="w-3 h-3" />}
                  {preNewsScanning ? 'Scanning…' : 'Scan Now'}
                </button>
              </div>

              {preNewsData.length === 0 ? (
                <div className="card text-center text-gray-500 text-sm py-8">No pre-news anomalies detected. Click Scan Now to run.</div>
              ) : (
                <div className="space-y-2">
                  {preNewsData.map((a, i) => {
                    const scoreColor = a.suspicion_score >= 75 ? 'text-red-400' : a.suspicion_score >= 60 ? 'text-orange-400' : a.suspicion_score >= 45 ? 'text-yellow-400' : 'text-gray-400'
                    const levelColor = a.classification === 'extreme' ? 'bg-red-500/10 border-red-500/30 text-red-400'
                      : a.classification === 'high' ? 'bg-orange-500/10 border-orange-500/30 text-orange-400'
                      : a.classification === 'watch' ? 'bg-yellow-500/10 border-yellow-500/30 text-yellow-400'
                      : 'bg-gray-500/10 border-gray-500/30 text-gray-400'
                    return (
                      <div key={`pn-${a.ticker}-${i}`} className="card">
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-3">
                            <span className="font-bold text-white text-sm">{a.ticker}</span>
                            <span className="text-xs text-gray-400">${a.price?.toFixed(2)}</span>
                            <span className={`text-[11px] px-2 py-0.5 rounded border ${levelColor}`}>
                              {a.classification?.toUpperCase()}
                            </span>
                            {a.alert_quality && (
                              <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                                a.alert_quality === 'early' ? 'bg-emerald-500/15 text-emerald-400'
                                  : a.alert_quality === 'caution' ? 'bg-yellow-500/15 text-yellow-400'
                                  : a.alert_quality === 'late' ? 'bg-orange-500/15 text-orange-400'
                                  : a.alert_quality === 'trap_risk' ? 'bg-red-500/15 text-red-400'
                                  : 'bg-gray-500/15 text-gray-400'
                              }`}>
                                {a.alert_quality?.toUpperCase()}
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-2">
                            {a.candidate_type && a.candidate_type !== 'general' && (
                              <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                                a.candidate_type === 'quiet_accumulation' ? 'bg-teal-500/15 text-teal-400'
                                  : a.candidate_type === 'early_breakout' ? 'bg-cyan-500/15 text-cyan-400'
                                  : a.candidate_type === 'late_chase' ? 'bg-orange-500/15 text-orange-400'
                                  : a.candidate_type === 'trap_risk' ? 'bg-red-500/15 text-red-400'
                                  : 'bg-gray-500/15 text-gray-400'
                              }`}>
                                {a.candidate_type?.replace(/_/g, ' ')?.toUpperCase()}
                              </span>
                            )}
                            <span className={`text-lg font-bold ${scoreColor}`}>{a.suspicion_score?.toFixed(0)}</span>
                          </div>
                        </div>
                        <div className="grid grid-cols-3 md:grid-cols-6 gap-3 text-xs mb-2">
                          <div>
                            <div className="text-gray-500">RVOL</div>
                            <div className={`font-semibold ${(a.rvol || 0) >= 5 ? 'text-red-400' : (a.rvol || 0) >= 3 ? 'text-orange-400' : 'text-white'}`}>
                              {a.rvol?.toFixed(1)}x
                            </div>
                          </div>
                          <div>
                            <div className="text-gray-500">ToD RVOL</div>
                            <div className={`font-semibold ${(a.time_of_day_rvol || 0) >= 5 ? 'text-red-400' : (a.time_of_day_rvol || 0) >= 3 ? 'text-orange-400' : 'text-white'}`}>
                              {a.time_of_day_rvol != null ? `${a.time_of_day_rvol.toFixed(1)}x` : '—'}
                            </div>
                          </div>
                          <div>
                            <div className="text-gray-500">Vol Accel</div>
                            <div className={`font-semibold ${(a.volume_acceleration || 0) > 0.5 ? 'text-emerald-400' : 'text-white'}`}>
                              {a.volume_acceleration > 0 ? '+' : ''}{(a.volume_acceleration * 100)?.toFixed(0)}%
                            </div>
                          </div>
                          <div>
                            <div className="text-gray-500">VWAP Dist</div>
                            <div className={`font-semibold ${
                              (a.vwap_distance_pct || 0) > 15 ? 'text-red-400'
                                : (a.vwap_distance_pct || 0) > 8 ? 'text-yellow-400'
                                : (a.vwap_distance_pct || 0) >= 0 ? 'text-emerald-400'
                                : 'text-gray-400'
                            }`}>
                              {a.vwap_distance_pct != null ? `${a.vwap_distance_pct > 0 ? '+' : ''}${a.vwap_distance_pct.toFixed(1)}%` : '—'}
                            </div>
                          </div>
                          <div>
                            <div className="text-gray-500">Absorption</div>
                            <div className={`font-semibold ${
                              (a.absorption_quality_score || 0) >= 70 ? 'text-emerald-400'
                                : (a.absorption_quality_score || 0) >= 50 ? 'text-cyan-400'
                                : (a.absorption_quality_score || 0) >= 30 ? 'text-yellow-400'
                                : 'text-red-400'
                            }`}>
                              {a.absorption_quality_score != null ? `${a.absorption_quality_score.toFixed(0)}/100` : '—'}
                            </div>
                          </div>
                          <div>
                            <div className="text-gray-500">News</div>
                            <div className={`font-semibold capitalize ${
                              a.news_status === 'no_news_found' || a.news_status === 'no_public_news_found_in_sources' ? 'text-purple-400'
                              : a.news_status === 'news_lag_confirmed' || a.news_status === 'news_appeared_after_detection' ? 'text-emerald-400'
                              : a.news_status === 'news_already_visible' || a.news_status === 'public_catalyst_already_visible' ? 'text-cyan-400'
                              : a.news_status === 'old_catalyst_present' ? 'text-blue-400'
                              : 'text-gray-300'
                            }`}>{a.news_status?.replace(/_/g, ' ')}</div>
                          </div>
                        </div>
                        {/* V3.1 Tape Read */}
                        {a.tape_read && (
                          <div className="mt-1 mb-1 px-2 py-1 rounded bg-gray-800/40 border border-gray-700/50">
                            <div className="text-[10px] text-gray-500 uppercase tracking-wide mb-0.5">Tape Read</div>
                            <div className="text-[11px] text-gray-300">{a.tape_read}</div>
                          </div>
                        )}
                        {/* Headline (if news was matched) */}
                        {a.first_news_headline && (
                          <div className="mt-1 mb-1 px-2 py-1 rounded bg-cyan-500/5 border border-cyan-500/20">
                            <div className="text-[10px] text-cyan-400/70 uppercase tracking-wide mb-0.5">
                              Matched Headline
                              {a.time_gap_minutes != null && (
                                <span className="ml-1 text-gray-500 normal-case">
                                  · {a.time_gap_minutes > 0
                                    ? `news ${Math.abs(a.time_gap_minutes).toFixed(0)}m after anomaly`
                                    : `anomaly ${Math.abs(a.time_gap_minutes).toFixed(0)}m after news`}
                                </span>
                              )}
                            </div>
                            <div className="text-[11px] text-gray-200 line-clamp-2">{a.first_news_headline}</div>
                          </div>
                        )}
                        {/* High-price tracking (pre vs post news confirmation) */}
                        {(a.high_price_pre_news != null || a.high_price_post_news != null) && (
                          <div className="grid grid-cols-2 gap-2 text-xs mt-1 mb-1">
                            <div className="px-2 py-1 rounded bg-gray-800/40 border border-gray-700/50">
                              <div className="text-[10px] text-gray-500 uppercase">High · Pre-News</div>
                              <div className="font-semibold text-gray-200">
                                {a.high_price_pre_news != null ? `$${a.high_price_pre_news.toFixed(2)}` : '—'}
                              </div>
                            </div>
                            <div className="px-2 py-1 rounded bg-emerald-500/5 border border-emerald-500/20">
                              <div className="text-[10px] text-emerald-400/70 uppercase">High · Post-News</div>
                              <div className="font-semibold text-emerald-300">
                                {a.high_price_post_news != null ? `$${a.high_price_post_news.toFixed(2)}` : '—'}
                              </div>
                            </div>
                          </div>
                        )}
                        {/* V3 Quality Tags */}
                        <div className="flex flex-wrap items-center gap-1.5 text-[10px] mt-1.5 mb-1.5">
                          {a.wyckoff_stage && a.wyckoff_stage !== 'unknown' && (
                            <span className="px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-400">
                              {a.wyckoff_stage.replace(/_/g, ' ')}
                            </span>
                          )}
                          {a.latest_5candle_summary && (
                            <span className={`px-1.5 py-0.5 rounded font-medium ${
                              a.latest_5candle_summary === 'accumulation' ? 'bg-emerald-500/10 text-emerald-400'
                                : a.latest_5candle_summary === 'breakout' ? 'bg-cyan-500/10 text-cyan-400'
                                : a.latest_5candle_summary === 'rejection' ? 'bg-orange-500/10 text-orange-400'
                                : a.latest_5candle_summary === 'distribution' ? 'bg-red-500/10 text-red-400'
                                : a.latest_5candle_summary === 'failed_spike' ? 'bg-red-500/10 text-red-400'
                                : 'bg-gray-700/40 text-gray-400'
                            }`}>
                              5c: {a.latest_5candle_summary}
                            </span>
                          )}
                          {a.catalyst_age_bucket && a.catalyst_age_bucket !== 'unknown' && (
                            <span className="px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400">
                              catalyst {a.catalyst_age_bucket.replace(/_/g, ' ')}
                            </span>
                          )}
                          {a.catalyst_relevance_score > 0 && (
                            <span className="px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400">
                              relevance {a.catalyst_relevance_score?.toFixed(0)}
                            </span>
                          )}
                          {a.float_pressure_score >= 70 && (
                            <span className="px-1.5 py-0.5 rounded bg-pink-500/10 text-pink-400">
                              float rotation {a.float_pressure_score?.toFixed(0)}
                            </span>
                          )}
                          {a.alert_suppression_reasons?.length > 0 && (
                            <span className="px-1.5 py-0.5 rounded bg-red-500/10 text-red-400">
                              suppressed ({a.alert_suppression_reasons.length})
                            </span>
                          )}
                        </div>

                        {/* V2 Scoring Block — informed-positioning signals */}
                        {(a.smart_money_score !== undefined) && (
                          <div className="mt-1.5 p-2 rounded bg-gray-800/40 border border-gray-700/50">
                            <div className="flex items-center justify-between mb-1.5">
                              <div className="flex items-center gap-2">
                                <span className="text-[10px] text-gray-500 uppercase tracking-wide">Smart Money</span>
                                <span className={`text-sm font-bold ${a.smart_money_score >= 75 ? 'text-emerald-400' : a.smart_money_score >= 55 ? 'text-cyan-400' : 'text-gray-400'}`}>
                                  {a.smart_money_score?.toFixed(0)}/100
                                </span>
                              </div>
                              <div className="flex items-center gap-1">
                                {a.timing_stage && (
                                  <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                                    a.timing_stage === 'early' ? 'bg-emerald-500/15 text-emerald-400'
                                      : a.timing_stage === 'developing' ? 'bg-cyan-500/15 text-cyan-400'
                                      : a.timing_stage === 'late' ? 'bg-orange-500/15 text-orange-400'
                                      : 'bg-red-500/15 text-red-400'
                                  }`}>
                                    {a.timing_stage}
                                  </span>
                                )}
                                {a.late_detection_flag && (
                                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/20 text-red-400 font-medium">LATE</span>
                                )}
                              </div>
                            </div>

                            {/* Pressure bars */}
                            <div className="grid grid-cols-2 gap-2 mb-1.5">
                              <div>
                                <div className="flex items-center justify-between text-[10px] mb-0.5">
                                  <span className="text-gray-500">Buy Pressure</span>
                                  <span className="text-gray-300 font-medium">{a.buy_pressure_score?.toFixed(0)}</span>
                                </div>
                                <div className="h-1 bg-gray-700/50 rounded overflow-hidden">
                                  <div className={`h-full ${a.buy_pressure_score >= 65 ? 'bg-emerald-500' : a.buy_pressure_score >= 40 ? 'bg-cyan-500' : 'bg-gray-500'}`} style={{ width: `${Math.min(100, a.buy_pressure_score || 0)}%` }} />
                                </div>
                              </div>
                              <div>
                                <div className="flex items-center justify-between text-[10px] mb-0.5">
                                  <span className="text-gray-500">Float Pressure</span>
                                  <span className="text-gray-300 font-medium">{a.float_pressure_score?.toFixed(0)}</span>
                                </div>
                                <div className="h-1 bg-gray-700/50 rounded overflow-hidden">
                                  <div className={`h-full ${a.float_pressure_score >= 70 ? 'bg-purple-500' : a.float_pressure_score >= 40 ? 'bg-cyan-500' : 'bg-gray-500'}`} style={{ width: `${Math.min(100, a.float_pressure_score || 0)}%` }} />
                                </div>
                              </div>
                            </div>

                            {/* V2 info strip: move type + accel trend + offering risk */}
                            <div className="flex flex-wrap items-center gap-1.5 text-[10px]">
                              {a.move_type_prediction && a.move_type_prediction !== 'unknown' && (
                                <span className={`px-1.5 py-0.5 rounded font-medium ${
                                  a.move_type_prediction === 'pump_and_dump' ? 'bg-red-500/15 text-red-400'
                                    : a.move_type_prediction === 'news_breakout' ? 'bg-purple-500/15 text-purple-400'
                                    : a.move_type_prediction === 'low_float_squeeze' ? 'bg-pink-500/15 text-pink-400'
                                    : a.move_type_prediction === 'momentum_continuation' ? 'bg-cyan-500/15 text-cyan-400'
                                    : 'bg-gray-500/15 text-gray-400'
                                }`}>
                                  {a.move_type_prediction.replace(/_/g, ' ')}
                                </span>
                              )}
                              {a.accel_trend && a.accel_trend !== 'stable' && (
                                <span className={`px-1.5 py-0.5 rounded ${a.accel_trend === 'accelerating' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-orange-500/10 text-orange-400'}`}>
                                  {a.accel_trend}
                                </span>
                              )}
                              {a.mtf_alignment_score >= 75 && (
                                <span className="px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400">MTF aligned</span>
                              )}
                              {a.offering_risk_score >= 50 && (
                                <span className="px-1.5 py-0.5 rounded bg-red-500/15 text-red-400 font-medium">
                                  ⚠ offering risk {a.offering_risk_score?.toFixed(0)}
                                </span>
                              )}
                              {/* Pattern memory similarity (only show if pattern memory is active) */}
                              {(a.winner_similarity_score !== 50 || a.loser_similarity_score !== 50) && a.winner_similarity_score > a.loser_similarity_score + 10 && (
                                <span className="px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400">✨ winner pattern {a.winner_similarity_score?.toFixed(0)}%</span>
                              )}
                              {(a.winner_similarity_score !== 50 || a.loser_similarity_score !== 50) && a.loser_similarity_score > a.winner_similarity_score + 10 && (
                                <span className="px-1.5 py-0.5 rounded bg-red-500/10 text-red-400">⚠ loser pattern {a.loser_similarity_score?.toFixed(0)}%</span>
                              )}
                              {a.confidence_decay_factor !== undefined && a.confidence_decay_factor < 0.95 && (
                                <span className="px-1.5 py-0.5 rounded bg-gray-500/15 text-gray-400">decay {(a.confidence_decay_factor * 100).toFixed(0)}%</span>
                              )}
                              {a.discovery_source && a.discovery_source !== 'unknown' && (
                                <span className="px-1.5 py-0.5 rounded bg-gray-700/40 text-gray-500">via {a.discovery_source.replace(/_/g, ' ')}</span>
                              )}
                            </div>
                          </div>
                        )}

                        <div className="flex items-center gap-2 text-[11px] text-gray-500 mb-1 mt-1.5">
                          <span className="capitalize">{a.anomaly_type?.replace(/_/g, ' ')}</span>
                          <span>·</span>
                          <span>{a.state?.replace(/_/g, ' ')}</span>
                          <span>·</span>
                          <span>{new Date(a.detected_at).toLocaleTimeString()}</span>
                          {a.session && <><span>·</span><span>{a.session}</span></>}
                        </div>
                        {a.next_condition_needed && (
                          <p className="text-[11px] text-blue-400 mt-1">→ {a.next_condition_needed}</p>
                        )}

                        {/* Why flagged — compact */}
                        {a.reasons?.length > 0 && (
                          <div className="mt-1.5">
                            <div className="flex flex-wrap gap-1">
                              {a.reasons.slice(0, 2).map((r, ri) => (
                                <span key={`r-${ri}`} className="text-[10px] px-1.5 py-0.5 rounded bg-gray-700/60 text-gray-300">
                                  {r}
                                </span>
                              ))}
                              {a.reasons.length > 2 && (
                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-700/40 text-gray-400">
                                  +{a.reasons.length - 2} more
                                </span>
                              )}
                            </div>
                          </div>
                        )}

                        {/* Risk notes */}
                        {a.risk_notes?.length > 0 && (
                          <div className="mt-1.5 space-y-0.5">
                            {a.risk_notes.map((rn, ri) => (
                              <p key={`rn-${ri}`} className="text-[10px] text-red-400/80">⚠ {rn}</p>
                            ))}
                          </div>
                        )}

                        {/* StockTwits social signal */}
                        {a.stocktwits_trending && (
                          <div className="mt-1.5 flex items-center gap-1.5">
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-500/10 text-green-400 border border-green-500/20">
                              Trending on StockTwits #{a.stocktwits_rank}
                            </span>
                            {a.stocktwits_sentiment_bullish_pct !== null && (
                              <span className={`text-[10px] ${a.stocktwits_sentiment_bullish_pct >= 70 ? 'text-green-400' : a.stocktwits_sentiment_bullish_pct >= 40 ? 'text-yellow-400' : 'text-red-400'}`}>
                                {a.stocktwits_sentiment_bullish_pct.toFixed(0)}% bullish
                              </span>
                            )}
                          </div>
                        )}
                        {a.stocktwits_message_volume && (
                          <p className="text-[10px] text-gray-500 mt-0.5">ST msg vol: {a.stocktwits_message_volume}</p>
                        )}

                        {/* Data quality warning */}
                        {a.data_quality && a.data_quality !== 'full' && (
                          <p className="text-[10px] text-orange-400/70 mt-1">Data quality: {a.data_quality}</p>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}

              {/* Pre-News Learning Summary */}
              {preNewsLearningData && preNewsLearningData.stats && (
                <div className="card mt-4">
                  <h4 className="text-xs text-gray-500 font-semibold mb-2 flex items-center gap-1">
                    <Brain className="w-3 h-3" /> Pre-News Learning
                  </h4>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs mb-3">
                    <div><div className="text-gray-500">Total Outcomes</div><div className="text-white font-bold">{preNewsLearningData.stats.total_outcomes}</div></div>
                    <div><div className="text-gray-500">News Conversion</div><div className="text-emerald-400 font-bold">{preNewsLearningData.stats.news_conversion_rate}%</div></div>
                    <div><div className="text-gray-500">Real Move Rate</div><div className="text-white font-bold">{preNewsLearningData.stats.real_move_rate}%</div></div>
                    <div><div className="text-gray-500">Pump Rate</div><div className="text-red-400 font-bold">{preNewsLearningData.stats.pump_rate}%</div></div>
                  </div>
                  {preNewsLearningData.recommendations?.length > 0 && (
                    <div className="space-y-1">
                      {preNewsLearningData.recommendations.map((r, i) => (
                        <p key={`pnr-${i}`} className="text-[11px] text-yellow-400/80">→ {r}</p>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Missed Opportunities Panel */}
          {activePanel === 'missed' && (
            <div>
              {missed.length === 0 ? (
                <div className="card text-center text-gray-500 text-sm py-8">No big movers found today, or scan hasn't run yet.</div>
              ) : (
                missed.map((m, i) => (
                  <div key={i} className="card mb-2">
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-bold text-white">${m.ticker}</span>
                      <span className={`text-sm font-bold ${m.move_pct >= 100 ? 'text-green-400' : m.move_pct >= 50 ? 'text-emerald-400' : 'text-yellow-400'}`}>
                        +{m.move_pct?.toFixed(0)}%
                      </span>
                    </div>
                    <div className="flex gap-3 text-xs mb-1">
                      <span className="text-gray-400">High: ${m.high_price?.toFixed(2)}</span>
                      <span className="text-gray-400">Low: ${m.low_price?.toFixed(2)}</span>
                      <span className="text-gray-400">Vol: {(m.volume / 1e6).toFixed(1)}M</span>
                    </div>
                    <span className={`text-[11px] px-2 py-0.5 rounded border ${
                      m.classification === 'not_discovered' ? 'text-red-400 border-red-500/30 bg-red-500/10'
                        : m.classification === 'rejected_wrong' ? 'text-orange-400 border-orange-500/30 bg-orange-500/10'
                        : m.classification === 'correctly_avoided' ? 'text-green-400 border-green-500/30 bg-green-500/10'
                        : 'text-yellow-400 border-yellow-500/30 bg-yellow-500/10'
                    }`}>
                      {m.classification?.replace(/_/g, ' ').toUpperCase()}
                    </span>
                    {m.lessons?.map((l, j) => <p key={j} className="text-[11px] text-gray-500 mt-1">→ {l}</p>)}
                  </div>
                ))
              )}
            </div>
          )}

          {/* Pre-News Evaluation Panel */}
          {activePanel === 'preNewsEval' && (
            <div className="card">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-semibold text-gray-300 flex items-center gap-2">
                  <Activity className="w-4 h-4 text-purple-400" /> Pre-News Evaluation
                </h3>
                <div className="flex items-center gap-2">
                  <button
                    onClick={handleExportToday}
                    disabled={preNewsEvalExportLoading}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded text-xs font-medium transition-colors"
                  >
                    {preNewsEvalExportLoading ? <RefreshCw className="w-3 h-3 animate-spin" /> : <TrendingDown className="w-3 h-3" />}
                    Export Today CSV
                  </button>
                  <button
                    onClick={fetchPreNewsEval}
                    disabled={preNewsEvalLoading}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white rounded text-xs font-medium transition-colors"
                  >
                    {preNewsEvalLoading ? <RefreshCw className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                    Refresh
                  </button>
                </div>
              </div>

              {preNewsEvalData ? (
                <div className="space-y-4 text-xs">
                  {/* Summary Stats */}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <div className="p-2 rounded bg-gray-800/40 border border-gray-700/50">
                      <div className="text-[10px] text-gray-500 uppercase">Total Detections</div>
                      <div className="text-white font-bold text-lg">{preNewsEvalData.total_detections || 0}</div>
                    </div>
                    <div className="p-2 rounded bg-gray-800/40 border border-gray-700/50">
                      <div className="text-[10px] text-gray-500 uppercase">Completed</div>
                      <div className="text-emerald-400 font-bold text-lg">{preNewsEvalData.completed_detections || 0}</div>
                    </div>
                    <div className="p-2 rounded bg-gray-800/40 border border-gray-700/50">
                      <div className="text-[10px] text-gray-500 uppercase">Clean Winners</div>
                      <div className="text-green-400 font-bold text-lg">{preNewsEvalData.clean_winner_rate != null ? `${preNewsEvalData.clean_winner_rate}%` : '—'}</div>
                    </div>
                    <div className="p-2 rounded bg-gray-800/40 border border-gray-700/50">
                      <div className="text-[10px] text-gray-500 uppercase">Avg Efficiency</div>
                      <div className="text-blue-400 font-bold text-lg">{preNewsEvalData.avg_efficiency != null ? preNewsEvalData.avg_efficiency : '—'}</div>
                    </div>
                  </div>

                  {/* Best / Worst Tables */}
                  {preNewsEvalData.best_early_detections?.length > 0 && (
                    <div>
                      <h4 className="text-gray-300 font-semibold mb-2 flex items-center gap-1"><CheckCircle2 className="w-3 h-3 text-green-400" /> Best Early Detections</h4>
                      <div className="space-y-1 max-h-48 overflow-y-auto">
                        {preNewsEvalData.best_early_detections.map((s, i) => (
                          <div key={i} className="flex justify-between items-center p-2 bg-gray-800/30 rounded">
                            <div className="flex items-center gap-2">
                              <span className="font-bold text-white">{s.ticker}</span>
                              <span className="text-gray-500">{s.alert_quality}</span>
                              <span className="text-gray-500">{s.anomaly_type}</span>
                            </div>
                            <div className="flex items-center gap-3">
                              <span className="text-emerald-400">+{s.max_move_1h_pct}%</span>
                              <span className="text-gray-500">eff {s.efficiency_ratio}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {preNewsEvalData.worst_false_positives?.length > 0 && (
                    <div>
                      <h4 className="text-gray-300 font-semibold mb-2 flex items-center gap-1"><XCircle className="w-3 h-3 text-red-400" /> Worst False Positives</h4>
                      <div className="space-y-1 max-h-48 overflow-y-auto">
                        {preNewsEvalData.worst_false_positives.map((s, i) => (
                          <div key={i} className="flex justify-between items-center p-2 bg-gray-800/30 rounded">
                            <div className="flex items-center gap-2">
                              <span className="font-bold text-white">{s.ticker}</span>
                              <span className="text-gray-500">score {s.suspicion_score}</span>
                            </div>
                            <div className="flex items-center gap-3">
                              <span className="text-red-400">{s.final_outcome_label.replace(/_/g, ' ')}</span>
                              <span className="text-gray-500">dd {s.drawdown_before_max_move_pct}%</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {preNewsEvalData.best_quiet_accumulation_winners?.length > 0 && (
                    <div>
                      <h4 className="text-gray-300 font-semibold mb-2 flex items-center gap-1"><TrendingUp className="w-3 h-3 text-emerald-400" /> Quiet Accumulation Winners</h4>
                      <div className="space-y-1 max-h-48 overflow-y-auto">
                        {preNewsEvalData.best_quiet_accumulation_winners.map((s, i) => (
                          <div key={i} className="flex justify-between items-center p-2 bg-gray-800/30 rounded">
                            <div className="flex items-center gap-2">
                              <span className="font-bold text-white">{s.ticker}</span>
                              <span className="text-gray-500">absorb {s.absorption_quality_score}</span>
                            </div>
                            <div className="flex items-center gap-3">
                              <span className="text-emerald-400">+{s.max_move_1h_pct}%</span>
                              <span className="text-gray-500">eff {s.efficiency_ratio}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {preNewsEvalData.suppressed_that_worked?.length > 0 && (
                    <div>
                      <h4 className="text-gray-300 font-semibold mb-2 flex items-center gap-1"><AlertCircle className="w-3 h-3 text-yellow-400" /> Suppressed But Worked</h4>
                      <div className="space-y-1 max-h-48 overflow-y-auto">
                        {preNewsEvalData.suppressed_that_worked.map((s, i) => (
                          <div key={i} className="flex justify-between items-center p-2 bg-gray-800/30 rounded">
                            <div className="flex items-center gap-2">
                              <span className="font-bold text-white">{s.ticker}</span>
                              <span className="text-gray-500">score {s.suspicion_score}</span>
                            </div>
                            <div className="flex items-center gap-3">
                              <span className="text-emerald-400">+{s.max_move_1h_pct}%</span>
                              <span className="text-gray-500">eff {s.efficiency_ratio}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Calibration Recommendations */}
                  {preNewsEvalData.calibration_recommendations?.length > 0 && (
                    <div>
                      <h4 className="text-gray-300 font-semibold mb-2 flex items-center gap-1"><Lightbulb className="w-3 h-3 text-yellow-400" /> Calibration Recommendations</h4>
                      <div className="space-y-2">
                        {preNewsEvalData.calibration_recommendations.map((rec, i) => (
                          <div key={i} className="p-2 rounded bg-yellow-500/5 border border-yellow-500/20">
                            <div className="flex items-center gap-2 mb-1">
                              <span className="text-[10px] px-1.5 py-0.5 rounded border text-yellow-400 border-yellow-500/30 bg-yellow-500/10 uppercase">{rec.recommendation_type}</span>
                              <span className="text-gray-400">{rec.affected_bucket}</span>
                              <span className="text-[10px] text-gray-500">{rec.confidence_level} confidence</span>
                            </div>
                            <p className="text-gray-300 text-[11px]">{rec.current_observation}</p>
                            <p className="text-emerald-400 text-[11px]">→ {rec.suggested_change}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Success Rate Report */}
                  <div className="mt-6 pt-4 border-t border-gray-700/50">
                    <div className="flex items-center justify-between mb-3">
                      <h4 className="text-gray-300 font-semibold flex items-center gap-1"><Brain className="w-3 h-3 text-purple-400" /> Success Rate Report</h4>
                      <div className="flex items-center gap-2">
                        <button
                          onClick={handleAnalyze}
                          disabled={preNewsAnalyzeLoading}
                          className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded text-xs font-medium transition-colors"
                        >
                          {preNewsAnalyzeLoading ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Activity className="w-3 h-3" />}
                          Run Analysis
                        </button>
                        <button
                          onClick={handleFetchReport}
                          disabled={preNewsReportLoading}
                          className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-700 hover:bg-gray-600 disabled:opacity-50 text-white rounded text-xs font-medium transition-colors"
                        >
                          {preNewsReportLoading ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Eye className="w-3 h-3" />}
                          View Report
                        </button>
                      </div>
                    </div>

                    {preNewsReportData ? (
                      <div className="space-y-3">
                        {/* Executive Summary */}
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                          <div className="p-2 rounded bg-gray-800/40 border border-gray-700/50">
                            <div className="text-[10px] text-gray-500 uppercase">Total Detections</div>
                            <div className="text-white font-bold">{preNewsReportData.data_quality?.total_detections || 0}</div>
                          </div>
                          <div className="p-2 rounded bg-gray-800/40 border border-gray-700/50">
                            <div className="text-[10px] text-gray-500 uppercase">Usable</div>
                            <div className="text-emerald-400 font-bold">{preNewsReportData.data_quality?.usable_for_success_rate || 0}</div>
                          </div>
                          <div className="p-2 rounded bg-gray-800/40 border border-gray-700/50">
                            <div className="text-[10px] text-gray-500 uppercase">Clean Success</div>
                            <div className="text-blue-400 font-bold">{preNewsReportData.overall_metrics?.clean_success_rate || '—'}%</div>
                          </div>
                          <div className="p-2 rounded bg-gray-800/40 border border-gray-700/50">
                            <div className="text-[10px] text-gray-500 uppercase">Avg 1h Move</div>
                            <div className="text-purple-400 font-bold">{preNewsReportData.overall_metrics?.avg_max_move_1h_pct || '—'}%</div>
                          </div>
                        </div>

                        {/* Verdict */}
                        <div className="p-2 rounded bg-gray-800/30 border border-gray-700/40">
                          <div className="text-[10px] text-gray-500 uppercase mb-1">Verdict</div>
                          <div className="text-gray-300 text-[11px]">
                            {preNewsReportData.overall_metrics?.total_usable < 20
                              ? 'NOT ENOUGH DATA. Collect more sessions before drawing conclusions.'
                              : (preNewsReportData.overall_metrics?.clean_success_rate || 0) >= 40
                                ? 'STRONG EVIDENCE. Detector is finding high-quality pre-news setups with controlled drawdown.'
                                : (preNewsReportData.overall_metrics?.clean_success_rate || 0) >= 25
                                  ? 'MODERATE EVIDENCE. Detector shows promise but needs refinement. Review false positives and late signals.'
                                  : 'WEAK EVIDENCE. High failure rate. Threshold tuning and suppression review strongly recommended.'}
                          </div>
                        </div>

                        {/* Top buckets */}
                        {preNewsReportData.buckets?.alert_quality?.length > 0 && (
                          <div>
                            <div className="text-[10px] text-gray-500 uppercase mb-1">Alert Quality Breakdown</div>
                            <div className="space-y-1">
                              {preNewsReportData.buckets.alert_quality.map((b, i) => (
                                <div key={i} className="flex justify-between items-center p-1.5 bg-gray-800/20 rounded text-[11px]">
                                  <div className="flex items-center gap-2">
                                    <span className="font-medium text-gray-300 capitalize">{b.bucket}</span>
                                    <span className="text-gray-500">n={b.count} conf={b.confidence_level}</span>
                                  </div>
                                  <div className="flex items-center gap-3">
                                    <span className={b.clean_success_rate >= 40 ? 'text-emerald-400' : b.clean_success_rate >= 20 ? 'text-yellow-400' : 'text-red-400'}>
                                      clean {b.clean_success_rate}%
                                    </span>
                                    <span className="text-gray-500">avg {b.avg_max_move_1h_pct}%</span>
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Recommendations */}
                        {preNewsReportData.recommendations?.length > 0 && (
                          <div>
                            <div className="text-[10px] text-gray-500 uppercase mb-1">Top Recommendations</div>
                            <div className="space-y-1">
                              {preNewsReportData.recommendations.slice(0, 5).map((rec, i) => (
                                <div key={i} className="p-1.5 rounded bg-yellow-500/5 border border-yellow-500/10 text-[11px]">
                                  <span className="text-yellow-400 font-medium">[{rec.recommendation_type}]</span>{' '}
                                  <span className="text-gray-400">{rec.affected_bucket}</span>{' '}
                                  <span className="text-gray-500">→ {rec.suggested_change}</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Baseline Comparison */}
                        {preNewsReportData.baseline_comparison?.comparisons?.length > 0 && (
                          <div className="mt-4 pt-3 border-t border-gray-700/30">
                            <div className="text-[10px] text-gray-500 uppercase mb-2">Detector vs Baselines</div>
                            <div className="overflow-x-auto">
                              <table className="w-full text-[10px]">
                                <thead>
                                  <tr className="text-gray-500 border-b border-gray-700/40">
                                    <th className="text-left py-1 pr-2">Baseline</th>
                                    <th className="text-right py-1 px-1">n</th>
                                    <th className="text-right py-1 px-1">Clean SR</th>
                                    <th className="text-right py-1 px-1">Avg 1h</th>
                                    <th className="text-right py-1 px-1">Avg 2h</th>
                                    <th className="text-right py-1 px-1">DD</th>
                                    <th className="text-right py-1 px-1">Eff</th>
                                    <th className="text-right py-1 px-1">VWAP</th>
                                    <th className="text-right py-1 px-1">Trap</th>
                                    <th className="text-left py-1 pl-2">Verdict</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {preNewsReportData.baseline_comparison.comparisons.map((comp, i) => {
                                    const verdict = preNewsReportData.baseline_comparison.verdicts?.[comp.baseline_type] || 'UNKNOWN'
                                    const verdictColor = verdict.includes('DETECTOR_WINS') ? 'text-emerald-400' : verdict.includes('DETECTOR_BEATS') ? 'text-yellow-400' : verdict.includes('BASELINE_WINS') ? 'text-red-400' : 'text-gray-400'
                                    return (
                                      <tr key={i} className="border-b border-gray-800/40">
                                        <td className="py-1 pr-2 text-gray-300 font-medium">{comp.baseline_type.replace('_BASELINE', '').replace(/_/g, ' ')}</td>
                                        <td className="text-right py-1 px-1 text-gray-500">{comp.usable}</td>
                                        <td className="text-right py-1 px-1">
                                          <span className="text-gray-400">D {comp.detector_clean_success_rate}%</span>
                                          <span className="text-gray-600 mx-0.5">/</span>
                                          <span className={comp.baseline_clean_success_rate > comp.detector_clean_success_rate ? 'text-red-400' : 'text-gray-500'}>B {comp.baseline_clean_success_rate}%</span>
                                        </td>
                                        <td className="text-right py-1 px-1 text-gray-500">{comp.baseline_avg_1h_move}%</td>
                                        <td className="text-right py-1 px-1 text-gray-500">{comp.baseline_avg_2h_move}%</td>
                                        <td className="text-right py-1 px-1 text-gray-500">{comp.baseline_avg_drawdown}%</td>
                                        <td className="text-right py-1 px-1 text-gray-500">{comp.baseline_avg_efficiency}</td>
                                        <td className="text-right py-1 px-1 text-gray-500">{comp.baseline_vwap_hold_rate}%</td>
                                        <td className="text-right py-1 px-1 text-gray-500">{comp.baseline_trap_rate}%</td>
                                        <td className="text-left py-1 pl-2 font-medium ${verdictColor}">{verdict.replace(/_/g, ' ')}</td>
                                      </tr>
                                    )
                                  })}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="text-gray-500 text-xs">No report loaded. Click Run Analysis or View Report.</div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="text-gray-500 text-sm">No evaluation data yet. Run scans to generate detection snapshots.</div>
              )}
            </div>
          )}

          {/* Quality Separator Panel */}
          {activePanel === 'qualitySep' && (
            <div className="card">
              <h3 className="text-sm font-semibold text-gray-400 mb-4 flex items-center gap-2"><Shield className="w-4 h-4" /> Winner vs Loser Separator</h3>
              {qualitySepData ? (
                <div className="space-y-4 text-xs">
                  <div className="flex items-center gap-2 mb-2">
                    <span className={`text-[11px] px-2 py-0.5 rounded border ${qualitySepData.profiles?.status === 'ready' ? 'text-green-400 border-green-500/30 bg-green-500/10' : 'text-yellow-400 border-yellow-500/30 bg-yellow-500/10'}`}>
                      {qualitySepData.profiles?.status === 'ready' ? 'PROFILES READY' : 'INSUFFICIENT DATA'}
                    </span>
                    <span className="text-gray-500">{qualitySepData.profiles?.total_outcomes || 0} historical outcomes</span>
                  </div>

                  {qualitySepData.feature_divergence?.status === 'ready' && (
                    <div>
                      <h4 className="text-gray-300 font-semibold mb-2">Feature Divergence (Winners vs Losers)</h4>
                      <div className="space-y-1">
                        {qualitySepData.feature_divergence.features?.slice(0, 8).map((f, i) => (
                          <div key={i} className="flex justify-between items-center p-1.5 bg-gray-800/30 rounded">
                            <span className="text-gray-400">{f.feature}</span>
                            <span className="text-emerald-400 font-mono">{f.difference?.toFixed(2) || f.divergence?.toFixed(3)}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {qualitySepData.profiles?.status !== 'ready' && (
                    <div className="text-yellow-400">
                      Need at least 100 historical outcomes to build winner/loser profiles.
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-gray-500 text-sm">Loading quality separator data…</div>
              )}
            </div>
          )}
        </div>

        {/* Detail Sidebar (only when candidate selected) */}
        {detail && <DetailPanel detail={detail} onClose={() => { setDetail(null); setSelectedTicker(null); }} />}
      </div>
    </div>
  )
}
