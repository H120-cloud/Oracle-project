import { useState, useEffect, useCallback } from 'react'
import {
  Search, TrendingUp, TrendingDown, Target, Shield, Zap,
  Activity, AlertTriangle, CheckCircle, XCircle, Clock,
  BarChart2, Eye, Crosshair, Brain, RefreshCw, Play, Flame,
} from 'lucide-react'
import {
  analyzeIntelligence, getMarketContext, getActiveTrades,
  getLearningWeights, startTradeTracking, getLiveQuote,
} from '../api'

const DECISION_COLORS = {
  ENTER: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/50',
  WAIT: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/50',
  AVOID: 'bg-red-500/20 text-red-400 border-red-500/50',
}

const PRIORITY_COLORS = {
  HIGH: 'bg-emerald-500/20 text-emerald-400',
  MEDIUM: 'bg-yellow-500/20 text-yellow-400',
  REJECT: 'bg-red-500/20 text-red-400',
}

function MarketContextPanel({ ctx }) {
  if (!ctx) return null
  const condColor = ctx.condition === 'BULL_MARKET' ? 'text-emerald-400'
    : ctx.condition === 'BEAR_MARKET' ? 'text-red-400' : 'text-yellow-400'

  return (
    <div className="card mb-6">
      <div className="card-header text-sm flex items-center gap-2">
        <Activity className="w-4 h-4 text-blue-400" /> Market Context
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-3">
        <div>
          <div className="text-xs text-gray-500">Condition</div>
          <div className={`font-bold ${condColor}`}>{ctx.condition?.replace('_', ' ')}</div>
        </div>
        <div>
          <div className="text-xs text-gray-500">Confidence</div>
          <div className="text-white">{ctx.condition_confidence?.toFixed(0)}%</div>
        </div>
        <div>
          <div className="text-xs text-gray-500">SPY</div>
          <div className="text-white">${ctx.spy_price?.toFixed(2)}
            <span className={`text-xs ml-1 ${ctx.spy_change_1d >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              {ctx.spy_change_1d >= 0 ? '+' : ''}{ctx.spy_change_1d?.toFixed(2)}%
            </span>
          </div>
        </div>
        <div>
          <div className="text-xs text-gray-500">QQQ</div>
          <div className="text-white">${ctx.qqq_price?.toFixed(2)}
            <span className={`text-xs ml-1 ${ctx.qqq_change_1d >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              {ctx.qqq_change_1d >= 0 ? '+' : ''}{ctx.qqq_change_1d?.toFixed(2)}%
            </span>
          </div>
        </div>
        <div>
          <div className="text-xs text-gray-500">Momentum</div>
          <div className={ctx.market_momentum > 0 ? 'text-emerald-400' : 'text-red-400'}>
            {ctx.market_momentum?.toFixed(1)}
          </div>
        </div>
        <div>
          <div className="text-xs text-gray-500">Aggressive OK</div>
          <div className={ctx.allow_aggressive ? 'text-emerald-400' : 'text-red-400'}>
            {ctx.allow_aggressive ? 'Yes' : 'No'}
          </div>
        </div>
        <div>
          <div className="text-xs text-gray-500">Conf. Modifier</div>
          <div className="text-white">{ctx.confidence_modifier?.toFixed(2)}x</div>
        </div>
        <div>
          <div className="text-xs text-gray-500">Size Modifier</div>
          <div className="text-white">{ctx.position_size_modifier?.toFixed(2)}x</div>
        </div>
      </div>
    </div>
  )
}

function LiveQuotePanel({ quote, ticker }) {
  if (!quote || !quote.price) return null
  const isUp = quote.change >= 0
  const pre = quote.premarket || {}
  const ah = quote.afterhours || {}
  const hasPre = pre.volume > 0 || pre.gap_pct !== 0
  const hasAH = ah.volume > 0

  return (
    <div className="card mb-4 border border-gray-700">
      <div className="flex justify-between items-start mb-3">
        <div>
          <div className="text-xs text-gray-500 uppercase tracking-wider">Live Market Data</div>
          <h3 className="text-xl font-bold text-white">{ticker}</h3>
        </div>
        <div className="text-right">
          <div className="text-3xl font-bold text-white">${quote.price?.toFixed(2)}</div>
          <div className={`text-sm font-semibold ${isUp ? 'text-emerald-400' : 'text-red-400'}`}>
            {isUp ? '+' : ''}{quote.change?.toFixed(2)} ({isUp ? '+' : ''}{quote.change_pct?.toFixed(2)}%)
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs mb-3">
        <div>
          <div className="text-gray-500">Open</div>
          <div className="text-white font-semibold">${quote.open?.toFixed(2)}</div>
        </div>
        <div>
          <div className="text-gray-500">Prev Close</div>
          <div className="text-white font-semibold">${quote.previous_close?.toFixed(2)}</div>
        </div>
        <div>
          <div className="text-gray-500">Day High</div>
          <div className="text-emerald-400 font-semibold">${quote.day_high?.toFixed(2)}</div>
        </div>
        <div>
          <div className="text-gray-500">Day Low</div>
          <div className="text-red-400 font-semibold">${quote.day_low?.toFixed(2)}</div>
        </div>
      </div>

      {(hasPre || hasAH) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 border-t border-gray-700 pt-3">
          {hasPre && (
            <div className="bg-blue-500/5 border border-blue-500/20 rounded-lg p-2">
              <div className="text-xs text-blue-400 font-semibold mb-1 flex items-center gap-1">
                <Clock className="w-3 h-3" /> Pre-Market
              </div>
              <div className="grid grid-cols-3 gap-2 text-xs">
                <div>
                  <div className="text-gray-500">Gap</div>
                  <div className={`font-bold ${pre.gap_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {pre.gap_pct >= 0 ? '+' : ''}{pre.gap_pct?.toFixed(2)}%
                  </div>
                </div>
                <div>
                  <div className="text-gray-500">High</div>
                  <div className="text-white">${pre.high?.toFixed(2)}</div>
                </div>
                <div>
                  <div className="text-gray-500">Volume</div>
                  <div className="text-white">{pre.volume?.toLocaleString()}</div>
                </div>
              </div>
            </div>
          )}
          {hasAH && (
            <div className="bg-purple-500/5 border border-purple-500/20 rounded-lg p-2">
              <div className="text-xs text-purple-400 font-semibold mb-1 flex items-center gap-1">
                <Clock className="w-3 h-3" /> After Hours
              </div>
              <div className="grid grid-cols-3 gap-2 text-xs">
                <div>
                  <div className="text-gray-500">High</div>
                  <div className="text-white">${ah.high?.toFixed(2)}</div>
                </div>
                <div>
                  <div className="text-gray-500">Low</div>
                  <div className="text-white">${ah.low?.toFixed(2)}</div>
                </div>
                <div>
                  <div className="text-gray-500">Volume</div>
                  <div className="text-white">{ah.volume?.toLocaleString()}</div>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function IntelligenceCard({ intel, onTrack }) {
  if (!intel) return null

  const decisionClass = DECISION_COLORS[intel.trade_decision] || DECISION_COLORS.AVOID
  const prioClass = PRIORITY_COLORS[intel.watchlist_priority] || PRIORITY_COLORS.REJECT

  return (
    <div className="card border border-gray-700">
      {/* Header */}
      <div className="flex justify-between items-start mb-3">
        <div>
          <h3 className="text-xl font-bold text-white">{intel.ticker}</h3>
          <div className="flex items-center gap-2 mt-1">
            <span className={`text-xs px-2 py-0.5 rounded border ${decisionClass}`}>
              {intel.trade_decision}
            </span>
            <span className={`text-xs px-2 py-0.5 rounded ${prioClass}`}>
              WL: {intel.watchlist_priority}
            </span>
          </div>
        </div>
        <div className="text-right">
          <div className="text-2xl font-bold text-white">
            {intel.bullish_probability?.toFixed(0)}%
            <span className="text-xs text-gray-500 ml-1">bull</span>
          </div>
          <div className="text-sm text-red-400">
            {intel.bearish_probability?.toFixed(0)}% bear
          </div>
        </div>
      </div>

      {/* Probability Bar */}
      <div className="w-full h-2 bg-gray-700 rounded-full mb-4 overflow-hidden">
        <div
          className="h-full bg-gradient-to-r from-emerald-500 to-emerald-400 rounded-full"
          style={{ width: `${intel.bullish_probability}%` }}
        />
      </div>

      {/* Grid */}
      <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs mb-3">
        <div className="flex justify-between">
          <span className="text-gray-500">Setup</span>
          <span className="text-white">{intel.setup_type?.replace('_', ' ')}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Playbook</span>
          <span className="text-oracle-400">{intel.playbook?.replace('_', ' ')}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Entry Quality</span>
          <span className={intel.entry_quality === 'CONFIRMED' ? 'text-emerald-400' : intel.entry_quality === 'EARLY' ? 'text-yellow-400' : 'text-red-400'}>
            {intel.entry_quality}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Timing</span>
          <span className={intel.entry_timing === 'IDEAL' ? 'text-emerald-400' : intel.entry_timing === 'EARLY' ? 'text-yellow-400' : 'text-red-400'}>
            {intel.entry_timing}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Catalyst</span>
          <span className="text-white">{intel.catalyst_tier} ({intel.catalyst_score?.toFixed(0)})</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Freshness</span>
          <span className={intel.freshness_label === 'BREAKING' ? 'text-red-400 font-bold' : intel.freshness_label === 'FRESH' ? 'text-yellow-400' : 'text-gray-400'}>
            {intel.freshness_label}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Reaction</span>
          <span className="text-white">{intel.reaction_state}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">MTF Align</span>
          <span className="text-white">{intel.mtf_alignment} ({intel.mtf_alignment_score?.toFixed(0)}%)</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Trend Bias</span>
          <span className={intel.trend_bias?.includes('BULLISH') ? 'text-emerald-400' : intel.trend_bias?.includes('BEARISH') ? 'text-red-400' : 'text-gray-400'}>
            {intel.trend_bias}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Reversal</span>
          <span className={intel.reversal_stage !== 'NONE' ? 'text-red-400' : 'text-gray-400'}>
            {intel.reversal_stage}
          </span>
        </div>
      </div>

      {/* V7: Momentum & Structure Intelligence */}
      {(intel.momentum_state || intel.structure_status || intel.breakout_quality || intel.early_bearish_warning) && (
        <div className="bg-gray-800/30 rounded p-2 mb-3">
          <div className="text-xs text-gray-500 mb-2 flex items-center gap-1">
            <TrendingUp className="w-3 h-3" /> V7 Momentum & Structure
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            {/* Momentum State */}
            {intel.momentum_state && (
              <div className="flex justify-between">
                <span className="text-gray-500">Momentum</span>
                <span className={
                  intel.momentum_state === 'accelerating_up' ? 'text-emerald-400' :
                  intel.momentum_state === 'slowing_down' ? 'text-blue-400' :
                  intel.momentum_state === 'accelerating_down' ? 'text-red-400' :
                  'text-gray-400'
                }>
                  {intel.momentum_state.replace(/_/g, ' ')}
                </span>
              </div>
            )}

            {/* Structure Status */}
            {intel.structure_status && (
              <div className="flex justify-between">
                <span className="text-gray-500">Structure</span>
                <span className={intel.structure_status === 'intact' ? 'text-emerald-400' : 'text-red-400'}>
                  {intel.structure_status}
                </span>
              </div>
            )}

            {/* Breakout Quality */}
            {intel.breakout_quality && intel.breakout_quality !== 'none' && (
              <div className="flex justify-between">
                <span className="text-gray-500">Breakout</span>
                <span className={
                  intel.breakout_quality === 'confirmed' ? 'text-emerald-400' :
                  intel.breakout_quality === 'weak' ? 'text-yellow-400' :
                  'text-red-400'
                }>
                  {intel.breakout_quality}
                </span>
              </div>
            )}

            {/* Follow-Through */}
            {intel.follow_through_confirmed != null && (
              <div className="flex justify-between">
                <span className="text-gray-500">Follow-Through</span>
                <span className={intel.follow_through_confirmed ? 'text-emerald-400' : 'text-red-400'}>
                  {intel.follow_through_confirmed ? 'Confirmed' : 'Missing'}
                </span>
              </div>
            )}

            {/* Dip Quality */}
            {intel.dip_quality_score != null && (
              <div className="flex justify-between">
                <span className="text-gray-500">Dip Quality</span>
                <span className={
                  intel.dip_quality_score >= 70 ? 'text-emerald-400' :
                  intel.dip_quality_score >= 50 ? 'text-yellow-400' :
                  'text-red-400'
                }>
                  {intel.dip_quality_score.toFixed(0)}/100
                </span>
              </div>
            )}

            {/* Target Type */}
            {intel.target_type && intel.target_type !== 'fixed_r' && (
              <div className="flex justify-between">
                <span className="text-gray-500">Target Type</span>
                <span className="text-blue-400">
                  {intel.target_type.replace(/_/g, ' ')}
                </span>
              </div>
            )}
          </div>

          {/* V8: Higher Timeframe Analysis */}
          {intel.htf_bias && (
            <div className="mt-2 bg-gray-500/10 border border-gray-500/30 rounded px-2 py-1">
              <div className="text-[10px] text-gray-400 font-semibold mb-1">Higher Timeframe Analysis</div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                <div className="flex justify-between">
                  <span className="text-gray-500">HTF Bias</span>
                  <span className={
                    intel.htf_bias === 'BULLISH' ? 'text-emerald-400' :
                    intel.htf_bias === 'BEARISH' ? 'text-red-400' :
                    'text-yellow-400'
                  }>
                    {intel.htf_bias} ({intel.htf_strength_score?.toFixed(0) ?? '?'}/100)
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">Alignment</span>
                  <span className={
                    intel.alignment_status === 'ALIGNED' ? 'text-emerald-400' :
                    intel.alignment_status === 'COUNTER_TREND' ? 'text-red-400' :
                    'text-gray-400'
                  }>
                    {intel.alignment_status?.replace(/_/g, ' ') ?? 'Unknown'}
                  </span>
                </div>
                {intel.trade_type === 'COUNTER_TREND_REVERSAL' && (
                  <div className="col-span-2 text-orange-400 text-[10px]">
                    ⚠️ Counter-Trend Reversal Setup
                  </div>
                )}
                {intel.htf_rsi && (
                  <div className="flex justify-between">
                    <span className="text-gray-500">HTF RSI</span>
                    <span className="text-white">{intel.htf_rsi.toFixed(1)}</span>
                  </div>
                )}
                {intel.htf_adx && (
                  <div className="flex justify-between">
                    <span className="text-gray-500">HTF ADX</span>
                    <span className={intel.htf_adx > 25 ? 'text-emerald-400' : 'text-gray-400'}>
                      {intel.htf_adx.toFixed(1)} {intel.htf_adx > 25 ? '(trending)' : '(weak)'}
                    </span>
                  </div>
                )}
              </div>
              {/* V8: HTF Blocked Warning */}
              {intel.htf_blocked && (
                <div className="mt-2 bg-red-500/10 border border-red-500/30 rounded px-2 py-1">
                  <div className="text-[10px] text-red-400 flex items-center gap-1">
                    <TrendingDown className="w-3 h-3" />
                    <span className="font-semibold">HTF FILTER BLOCKED</span>
                  </div>
                  {intel.htf_alignment_reason && (
                    <div className="text-[10px] text-red-400/80 mt-0.5">
                      {intel.htf_alignment_reason}
                    </div>
                  )}
                </div>
              )}
              
              {/* V8: Show reason even when not blocked (for context) */}
              {!intel.htf_blocked && intel.htf_alignment_reason && (
                <div className="text-[10px] text-gray-500 mt-1 italic">
                  {intel.htf_alignment_reason}
                </div>
              )}
            </div>
          )}
          
          {/* V8: Missing HTF Data Warning */}
          {!intel.htf_bias && (
            <div className="mt-2 bg-gray-500/10 border border-gray-500/30 rounded px-2 py-1">
              <div className="text-[10px] text-gray-400 flex items-center gap-1">
                <AlertTriangle className="w-3 h-3" />
                HTF data not available. Analysis requires daily bar history.
              </div>
            </div>
          )}

          {/* Early Bearish Warning */}
          {intel.early_bearish_warning && (
            <div className="mt-2 bg-orange-500/10 border border-orange-500/30 rounded px-2 py-1">
              <div className="text-[10px] text-orange-400 flex items-center gap-1">
                <AlertTriangle className="w-3 h-3" />
                Early Topping Warning — {intel.early_bearish_confidence?.toFixed(0) ?? '?'}% confidence
              </div>
              {intel.multiple_resistance_rejections > 0 && (
                <div className="text-[10px] text-gray-500 mt-0.5">
                  • {intel.multiple_resistance_rejections} resistance rejections
                </div>
              )}
              {intel.decreasing_volume_on_rises && (
                <div className="text-[10px] text-gray-500">
                  • Decreasing volume on rises
                </div>
              )}
              {intel.increasing_upper_wicks && (
                <div className="text-[10px] text-gray-500">
                  • Increasing upper wicks near highs
                </div>
              )}
              {intel.momentum_slowed_near_highs && (
                <div className="text-[10px] text-gray-500">
                  • Momentum slowing near resistance
                </div>
              )}
            </div>
          )}

          {/* Falling Knife Warning */}
          {intel.is_falling_knife && (
            <div className="mt-2 bg-red-500/10 border border-red-500/30 rounded px-2 py-1">
              <div className="text-[10px] text-red-400 flex items-center gap-1">
                <Flame className="w-3 h-3" />
                FALLING KNIFE — Entry blocked
              </div>
              {intel.structure_reject_reason && (
                <div className="text-[10px] text-gray-500 mt-0.5">
                  Reason: {intel.structure_reject_reason}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Targets */}
      {intel.target_price_1 > 0 && (
        <div className="bg-gray-800/50 rounded p-2 mb-3">
          <div className="text-xs text-gray-500 mb-1 flex items-center gap-1">
            <Target className="w-3 h-3" /> Price Targets
          </div>
          <div className="grid grid-cols-4 gap-2 text-xs">
            <div>
              <div className="text-gray-500">T1</div>
              <div className="text-emerald-400 font-bold">${intel.target_price_1?.toFixed(2)}</div>
            </div>
            <div>
              <div className="text-gray-500">T2</div>
              <div className="text-emerald-400">${intel.target_price_2?.toFixed(2)}</div>
            </div>
            <div>
              <div className="text-gray-500">Stop</div>
              <div className="text-red-400">${intel.stop_loss?.toFixed(2)}</div>
            </div>
            <div>
              <div className="text-gray-500">R:R</div>
              <div className={intel.reward_risk_ratio >= 3 ? 'text-emerald-400 font-bold' : intel.reward_risk_ratio >= 2 ? 'text-yellow-400' : 'text-red-400'}>
                {intel.reward_risk_ratio?.toFixed(1)}:1
              </div>
            </div>
          </div>
          <div className="text-xs text-gray-500 mt-1">
            Move: <span className={intel.predicted_move_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}>
              {intel.predicted_move_pct >= 0 ? '+' : ''}{intel.predicted_move_pct?.toFixed(1)}%
            </span> | Confidence: {intel.prediction_confidence?.toFixed(0)}%
          </div>

          {/* Start Tracking Button */}
          {onTrack && intel.trade_decision === 'ENTER' && (
            <button
              onClick={() => onTrack(intel)}
              className="mt-2 w-full bg-oracle-500/20 hover:bg-oracle-500/30 text-oracle-400 text-xs py-1.5 rounded flex items-center justify-center gap-1 transition-colors"
            >
              <Play className="w-3 h-3" /> Start Tracking Trade
            </button>
          )}
        </div>
      )}

      {/* Playbook Rules */}
      {intel.playbook !== 'NO_PLAYBOOK' && intel.playbook_entry_rules?.length > 0 && (
        <div className="bg-gray-800/30 rounded p-2 mb-3">
          <div className="text-xs text-gray-500 mb-1 flex items-center gap-1">
            <Brain className="w-3 h-3" /> Playbook: {intel.playbook?.replace('_', ' ')}
            <span className="text-oracle-400 ml-1">({intel.playbook_match_score?.toFixed(0)}% match)</span>
          </div>
          <div className="text-[10px] space-y-0.5">
            {intel.playbook_entry_rules?.map((r, i) => (
              <div key={i} className="text-gray-400">→ {r}</div>
            ))}
          </div>
        </div>
      )}

      {/* Decision Reasons */}
      {intel.decision_reasons?.length > 0 && (
        <div className="space-y-1">
          {intel.decision_reasons.map((r, i) => (
            <div key={i} className={`text-[11px] px-2 py-1 rounded ${
              r.includes('BLOCKED') ? 'bg-red-500/10 text-red-400' :
              r.includes('WARNING') ? 'bg-yellow-500/10 text-yellow-400' :
              r.includes('CONFIRMED') || r.includes('BONUS') ? 'bg-emerald-500/10 text-emerald-400' :
              'bg-gray-800/50 text-gray-400'
            }`}>
              {r}
            </div>
          ))}
        </div>
      )}

      {/* Watchlist reason */}
      {intel.watchlist_reason && (
        <div className="text-[10px] text-gray-500 mt-2 border-t border-gray-800 pt-2">
          WL: {intel.watchlist_reason}
        </div>
      )}
    </div>
  )
}

export default function IntelligencePage() {
  const [ticker, setTicker] = useState('')
  const [intel, setIntel] = useState(null)
  const [liveQuote, setLiveQuote] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [marketCtx, setMarketCtx] = useState(null)
  const [ctxLoading, setCtxLoading] = useState(false)
  const [tracking, setTracking] = useState(false)
  const [trackError, setTrackError] = useState('')
  const [trackSuccess, setTrackSuccess] = useState('')

  const loadMarketContext = useCallback(async (refresh = false) => {
    setCtxLoading(true)
    try {
      const data = await getMarketContext(refresh)
      setMarketCtx(data)
    } catch (err) {
      console.error('Market context error:', err)
    } finally {
      setCtxLoading(false)
    }
  }, [])

  useEffect(() => {
    loadMarketContext()
  }, [loadMarketContext])

  // Check for ?analyze=TICKER query param and auto-analyze
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const analyzeTicker = params.get('analyze')
    if (analyzeTicker) {
      setTicker(analyzeTicker.toUpperCase())
      // Small delay to ensure state is set
      setTimeout(() => {
        handleAnalyzeForTicker(analyzeTicker.toUpperCase())
      }, 100)
      // Clear the query param
      window.history.replaceState({}, document.title, '/intelligence')
    }
  }, [])

  const handleAnalyzeForTicker = async (t) => {
    if (!t) return
    setLoading(true)
    setError('')
    setTrackError('')
    setTrackSuccess('')
    setIntel(null)
    setLiveQuote(null)
    try {
      // Fetch live quote fast (1-2s) while intelligence runs (slower)
      const [quoteData, intelData] = await Promise.allSettled([
        getLiveQuote(t),
        analyzeIntelligence(t),
      ])
      if (quoteData.status === 'fulfilled') setLiveQuote(quoteData.value)
      if (intelData.status === 'fulfilled') setIntel(intelData.value)
      else if (intelData.status === 'rejected') setError(intelData.reason?.message || 'Intelligence analysis failed')
    } catch (err) {
      setError(err.message || 'Analysis failed')
    } finally {
      setLoading(false)
    }
  }

  const handleAnalyze = async () => {
    if (!ticker.trim()) return
    const t = ticker.trim().toUpperCase()
    handleAnalyzeForTicker(t)
  }

  const handleTrack = async (intelData) => {
    setTracking(true)
    setTrackError('')
    setTrackSuccess('')
    try {
      await startTradeTracking({
        ticker: intelData.ticker,
        entry_price: intelData.current_price || 0,
        target_1: intelData.target_price_1,
        target_2: intelData.target_price_2,
        stop_loss: intelData.stop_loss,
        direction: intelData.predicted_direction || 'bullish',
      })
      setTrackSuccess(`Now tracking ${intelData.ticker}. View on Active Trades page.`)
    } catch (err) {
      setTrackError(err.message || 'Failed to start tracking')
    } finally {
      setTracking(false)
    }
  }

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="flex items-center gap-3 mb-6">
        <Brain className="w-7 h-7 text-oracle-400" />
        <div>
          <h1 className="text-2xl font-bold text-white">Market Intelligence</h1>
          <p className="text-sm text-gray-500">Full analysis: news + context + structure + probability + targets + playbook</p>
        </div>
      </div>

      {/* Market Context */}
      <div className="flex items-center gap-2 mb-2">
        <button
          onClick={() => loadMarketContext(true)}
          className="text-xs text-gray-500 hover:text-oracle-400 flex items-center gap-1"
          disabled={ctxLoading}
        >
          <RefreshCw className={`w-3 h-3 ${ctxLoading ? 'animate-spin' : ''}`} /> Refresh Market
        </button>
      </div>
      <MarketContextPanel ctx={marketCtx} />

      {/* Search */}
      <div className="flex gap-3 mb-6">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
          <input
            type="text"
            value={ticker}
            onChange={e => setTicker(e.target.value.toUpperCase())}
            onKeyDown={e => e.key === 'Enter' && handleAnalyze()}
            placeholder="Enter ticker (e.g. AAPL, TSLA, NVDA)"
            className="w-full pl-10 pr-4 py-3 bg-gray-800 border border-gray-700 rounded-lg text-white placeholder:text-gray-500 focus:ring-2 focus:ring-oracle-500"
          />
        </div>
        <button
          onClick={handleAnalyze}
          disabled={loading || !ticker.trim()}
          className="btn-primary px-6 flex items-center gap-2"
        >
          {loading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Crosshair className="w-4 h-4" />}
          Analyze
        </button>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/50 rounded-lg p-3 mb-4 text-red-400 text-sm">
          {error}
        </div>
      )}

      {loading && (
        <div className="text-center py-12">
          <RefreshCw className="w-8 h-8 text-oracle-400 animate-spin mx-auto mb-2" />
          <p className="text-gray-500">Running full intelligence analysis...</p>
          <p className="text-xs text-gray-600 mt-1">News + Market Context + Multi-TF + Liquidity + Probability + Targets + Entry + Playbook</p>
        </div>
      )}

      {trackError && (
        <div className="bg-red-500/10 border border-red-500/50 rounded-lg p-3 mb-4 text-red-400 text-sm">
          {trackError}
        </div>
      )}

      {trackSuccess && (
        <div className="bg-emerald-500/10 border border-emerald-500/50 rounded-lg p-3 mb-4 text-emerald-400 text-sm">
          {trackSuccess}
        </div>
      )}

      {liveQuote && !loading && <LiveQuotePanel quote={liveQuote} ticker={ticker.trim().toUpperCase()} />}
      {intel && !loading && <IntelligenceCard intel={intel} onTrack={handleTrack} />}
    </div>
  )
}
