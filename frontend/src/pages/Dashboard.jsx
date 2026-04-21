import { useState, useEffect, useCallback } from 'react'
import {
  RefreshCw, TrendingUp, TrendingDown, Shield, Target,
  AlertTriangle, Eye, Zap, ArrowUpRight, ArrowDownRight,
  CheckCircle, XCircle, Flame,
} from 'lucide-react'
import { getSignals, getHealth, recordOutcome, addToWatchlist, discoverTrading212 } from '../api'

const ACTION_BADGE = {
  BUY: { cls: 'badge-buy', icon: ArrowUpRight },
  WATCH: { cls: 'badge-watch', icon: Eye },
  AVOID: { cls: 'badge-avoid', icon: AlertTriangle },
  NO_VALID_SETUP: { cls: 'badge-neutral', icon: null },
}

const GRADE_COLORS = {
  A: 'text-emerald-400',
  B: 'text-green-400',
  C: 'text-yellow-400',
  D: 'text-orange-400',
  F: 'text-red-400',
}

function SignalCard({ signal }) {
  const badge = ACTION_BADGE[signal.action] || ACTION_BADGE.NO_VALID_SETUP
  const BadgeIcon = badge.icon

  return (
    <div className="card hover:border-gray-700 transition-colors">
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="text-lg font-bold text-white">{signal.ticker}</h3>
          <p className="text-xs text-gray-500">{signal.classification}</p>
        </div>
        <span className={badge.cls}>
          {BadgeIcon && <BadgeIcon className="w-3 h-3 inline mr-1" />}
          {signal.action}
        </span>
      </div>

      <div className="grid grid-cols-3 gap-3 mb-3">
        <div>
          <div className="stat-label">Entry</div>
          <div className="text-sm font-semibold text-white">
            ${signal.entry_price?.toFixed(2) ?? '—'}
          </div>
        </div>
        <div>
          <div className="stat-label">Stop</div>
          <div className="text-sm font-semibold text-red-400">
            ${signal.stop_price?.toFixed(2) ?? '—'}
          </div>
        </div>
        <div>
          <div className="stat-label">Target</div>
          <div className="text-sm font-semibold text-emerald-400">
            ${signal.target_prices?.[0]?.toFixed(2) ?? '—'}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-2 text-center">
        <div>
          <div className="stat-label">Risk</div>
          <div className="text-sm font-bold text-white">{signal.risk_score ?? '—'}/10</div>
        </div>
        <div>
          <div className="stat-label">Grade</div>
          <div className={`text-sm font-bold ${GRADE_COLORS[signal.setup_grade] || 'text-gray-400'}`}>
            {signal.setup_grade ?? '—'}
          </div>
        </div>
        <div>
          <div className="stat-label">Conf</div>
          <div className="text-sm font-bold text-white">{signal.confidence?.toFixed(0) ?? '—'}%</div>
        </div>
        <div>
          <div className="stat-label">Stage</div>
          <div className="text-sm font-bold text-white">{signal.stage ?? '—'}</div>
        </div>
      </div>

      {signal.order_flow && (
        <div className="mt-3 pt-3 border-t border-gray-800 flex items-center gap-2 text-xs">
          <Zap className="w-3.5 h-3.5 text-oracle-400" />
          <span className="text-gray-400">Flow:</span>
          <span className={
            signal.order_flow.signal === 'bullish' ? 'text-emerald-400' :
            signal.order_flow.signal === 'bearish' ? 'text-red-400' : 'text-gray-400'
          }>
            {signal.order_flow.signal} (imb: {signal.order_flow.bid_ask_imbalance})
          </span>
        </div>
      )}

      {/* V7: Momentum & Structure Intelligence */}
      <div className="mt-2 flex flex-wrap gap-1.5">
        {/* Momentum State Badge */}
        {signal.momentum_state && signal.momentum_state !== 'neutral' && (
          <span className={`text-[10px] px-1.5 py-0.5 rounded ${
            signal.momentum_state === 'accelerating_up' ? 'bg-emerald-500/20 text-emerald-400' :
            signal.momentum_state === 'slowing_down' ? 'bg-blue-500/20 text-blue-400' :
            signal.momentum_state === 'accelerating_down' ? 'bg-red-500/20 text-red-400' :
            'bg-gray-700 text-gray-400'
          }`}>
            {signal.momentum_state.replace(/_/g, ' ')}
          </span>
        )}

        {/* Structure Status Badge */}
        {signal.structure_status && (
          <span className={`text-[10px] px-1.5 py-0.5 rounded ${
            signal.structure_status === 'intact' ? 'bg-emerald-500/20 text-emerald-400' :
            signal.structure_status === 'broken' ? 'bg-red-500/20 text-red-400' :
            'bg-gray-700 text-gray-400'
          }`}>
            Structure: {signal.structure_status}
          </span>
        )}

        {/* Breakout Quality Badge */}
        {signal.breakout_quality && signal.breakout_quality !== 'none' && (
          <span className={`text-[10px] px-1.5 py-0.5 rounded ${
            signal.breakout_quality === 'confirmed' ? 'bg-emerald-500/20 text-emerald-400' :
            signal.breakout_quality === 'weak' ? 'bg-yellow-500/20 text-yellow-400' :
            signal.breakout_quality === 'fake' ? 'bg-red-500/20 text-red-400' :
            'bg-gray-700 text-gray-400'
          }`}>
            Breakout: {signal.breakout_quality}
          </span>
        )}

        {/* Follow-Through Confirmation */}
        {signal.follow_through_confirmed && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400">
            ✓ Follow-through
          </span>
        )}

        {/* Dip Quality Score */}
        {signal.dip_quality_score != null && (
          <span className={`text-[10px] px-1.5 py-0.5 rounded ${
            signal.dip_quality_score >= 70 ? 'bg-emerald-500/20 text-emerald-400' :
            signal.dip_quality_score >= 50 ? 'bg-yellow-500/20 text-yellow-400' :
            'bg-red-500/20 text-red-400'
          }`}>
            Quality: {signal.dip_quality_score.toFixed(0)}
          </span>
        )}

        {/* Target Type */}
        {signal.target_type && signal.target_type !== 'fixed_r' && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400">
            {signal.target_type.replace(/_/g, ' ')}
          </span>
        )}

        {/* V8: HTF Bias Badge with Component Breakdown */}
        {signal.htf_bias && (
          <div className="relative group">
            <span className={`text-[10px] px-1.5 py-0.5 rounded cursor-help ${
              signal.htf_bias === 'BULLISH' ? 'bg-emerald-500/20 text-emerald-400' :
              signal.htf_bias === 'BEARISH' ? 'bg-red-500/20 text-red-400' :
              'bg-yellow-500/20 text-yellow-400'
            }`}>
              HTF: {signal.htf_bias} ({signal.htf_strength_score?.toFixed(0) ?? '?'})
            </span>
            {/* V8: Component Score Tooltip */}
            <div className="absolute left-0 bottom-full mb-1 hidden group-hover:block w-56 bg-gray-800 border border-gray-700 rounded-lg p-2 shadow-lg z-10">
              <div className="text-[10px] font-medium text-gray-300 mb-1">HTF Component Scores</div>
              <div className="space-y-0.5 text-[9px]">
                <div className="flex justify-between">
                  <span className="text-gray-400">Structure</span>
                  <span className={signal.htf_structure_score >= 60 ? 'text-emerald-400' : signal.htf_structure_score <= 40 ? 'text-red-400' : 'text-yellow-400'}>
                    {signal.htf_structure_score?.toFixed(0) ?? '?'}/100
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">EMA Align</span>
                  <span className={signal.htf_ema_score >= 60 ? 'text-emerald-400' : signal.htf_ema_score <= 40 ? 'text-red-400' : 'text-yellow-400'}>
                    {signal.htf_ema_score?.toFixed(0) ?? '?'}/100
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Momentum</span>
                  <span className={signal.htf_momentum_score >= 60 ? 'text-emerald-400' : signal.htf_momentum_score <= 40 ? 'text-red-400' : 'text-yellow-400'}>
                    {signal.htf_momentum_score?.toFixed(0) ?? '?'}/100
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">ADX Strength</span>
                  <span className={signal.htf_adx_score >= 60 ? 'text-emerald-400' : signal.htf_adx_score <= 40 ? 'text-red-400' : 'text-yellow-400'}>
                    {signal.htf_adx_score?.toFixed(0) ?? '?'}/100
                  </span>
                </div>
                <div className="border-t border-gray-700 pt-0.5 mt-0.5">
                  <div className="flex justify-between font-medium">
                    <span className="text-gray-300">Composite</span>
                    <span className={signal.htf_strength_score >= 70 ? 'text-emerald-400' : signal.htf_strength_score >= 40 ? 'text-yellow-400' : 'text-red-400'}>
                      {signal.htf_strength_score?.toFixed(0) ?? '?'}/100
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* V8: Alignment Status */}
        {signal.alignment_status && (
          <span className={`text-[10px] px-1.5 py-0.5 rounded ${
            signal.alignment_status === 'ALIGNED' ? 'bg-emerald-500/20 text-emerald-400' :
            signal.alignment_status === 'COUNTER_TREND' ? 'bg-red-500/20 text-red-400' :
            'bg-gray-500/20 text-gray-400'
          }`}>
            {signal.alignment_status.replace(/_/g, ' ')}
          </span>
        )}

        {/* V8: Trade Type (Counter-Trend Warning) */}
        {signal.trade_type === 'COUNTER_TREND_REVERSAL' && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-orange-500/20 text-orange-400">
            ⚠️ Counter-Trend
          </span>
        )}
      </div>

      {/* V8: HTF Blocked Warning */}
      {signal.htf_blocked && (
        <div className="mt-2 bg-red-500/10 border border-red-500/30 rounded px-2 py-1">
          <div className="text-[10px] text-red-400 flex items-center gap-1">
            <TrendingDown className="w-3 h-3" />
            HTF FILTER BLOCKED: {signal.htf_alignment_reason}
          </div>
        </div>
      )}

      {/* V7: Falling Knife Warning */}
      {signal.is_falling_knife && (
        <div className="mt-2 bg-red-500/10 border border-red-500/30 rounded px-2 py-1">
          <div className="text-[10px] text-red-400 flex items-center gap-1">
            <Flame className="w-3 h-3" />
            FALLING KNIFE — Entry blocked
          </div>
        </div>
      )}

      {/* V7: Early Bearish Warning */}
      {signal.early_bearish_warning && (
        <div className="mt-2 bg-orange-500/10 border border-orange-500/30 rounded px-2 py-1">
          <div className="text-[10px] text-orange-400 flex items-center gap-1">
            <AlertTriangle className="w-3 h-3" />
            Early Topping Warning ({signal.early_bearish_confidence?.toFixed(0) ?? '?'}% confidence)
          </div>
        </div>
      )}

      {signal.reason?.length > 0 && (
        <div className="mt-2 text-xs text-gray-500 space-y-0.5">
          {signal.reason.map((r, i) => (
            <div key={i}>• {r}</div>
          ))}
        </div>
      )}

      {/* Add to Watchlist */}
      <div className="mt-2 pt-2 border-t border-gray-800">
        <button
          onClick={async () => {
            try {
              await addToWatchlist({
                ticker: signal.ticker,
                source: 'scanner',
                watch_reason: `${signal.action} — ${signal.classification}`,
                tags: signal.action === 'BUY' ? ['dip_candidate'] : ['momentum'],
                priority: signal.setup_grade === 'A' ? 'high' : signal.setup_grade === 'B' ? 'medium' : 'low',
              })
              alert(`Added ${signal.ticker} to watchlist`)
            } catch (err) {
              alert(err.message)
            }
          }}
          className="flex items-center gap-1 px-2 py-1 text-xs bg-oracle-600/20 text-oracle-300 rounded hover:bg-oracle-600/30 transition-colors w-full justify-center"
        >
          <Eye className="w-3 h-3" />
          Add to Watchlist
        </button>
      </div>

      {/* Outcome buttons */}
      {(signal.action === 'BUY' || signal.action === 'WATCH') && !signal.recorded && (
        <div className="mt-3 pt-3 border-t border-gray-800 flex items-center gap-2">
          <span className="text-xs text-gray-500">Outcome:</span>
          <button
            onClick={async () => {
              try {
                const pnl = signal.target_prices?.[0] && signal.entry_price
                  ? ((signal.target_prices[0] - signal.entry_price) / signal.entry_price * 100)
                  : 5;
                const id = signal.id || `${signal.ticker}-${Date.now()}`;
                await recordOutcome(id, 'win', pnl);
                signal.recorded = true;
                alert(`✅ Recorded WIN for ${signal.ticker}`);
              } catch (err) {
                console.error('Failed to record outcome:', err);
                alert('Failed to record outcome: ' + err.message);
              }
            }}
            className="flex items-center gap-1 px-2 py-1 text-xs bg-emerald-900/50 text-emerald-400 rounded hover:bg-emerald-900 transition-colors"
          >
            <CheckCircle className="w-3 h-3" />
            Win
          </button>
          <button
            onClick={async () => {
              try {
                const pnl = signal.stop_price && signal.entry_price
                  ? ((signal.stop_price - signal.entry_price) / signal.entry_price * 100)
                  : -5;
                const id = signal.id || `${signal.ticker}-${Date.now()}`;
                await recordOutcome(id, 'loss', pnl);
                signal.recorded = true;
                alert(`❌ Recorded LOSS for ${signal.ticker}`);
              } catch (err) {
                console.error('Failed to record outcome:', err);
                alert('Failed to record outcome: ' + err.message);
              }
            }}
            className="flex items-center gap-1 px-2 py-1 text-xs bg-red-900/50 text-red-400 rounded hover:bg-red-900 transition-colors"
          >
            <XCircle className="w-3 h-3" />
            Loss
          </button>
        </div>
      )}
    </div>
  )
}

export default function Dashboard() {
  const [signals, setSignals] = useState([])
  const [loading, setLoading] = useState(false)
  const [lastUpdate, setLastUpdate] = useState(null)
  const [health, setHealth] = useState(null)
  const [scanType, setScanType] = useState('professional')
  const [t212Tickers, setT212Tickers] = useState([])
  const [hasScanned, setHasScanned] = useState(false)
  const [error, setError] = useState('')
  
  // V8: Auto-refresh state
  const [autoRefresh, setAutoRefresh] = useState(false)
  const [secondsUntilRefresh, setSecondsUntilRefresh] = useState(60)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError('')
    console.log('Refresh clicked, scanType:', scanType)
    try {
      // Handle Trading 212 discovery separately
      if (scanType === 'trading212') {
        console.log('Fetching Trading 212 movers...')
        const result = await discoverTrading212('movers', 15)
        console.log('Trading 212 result:', result)
        setT212Tickers(result.tickers || [])
        setSignals([]) // Clear regular signals
        setHasScanned(true)
        // Don't show error - backend now has fallback tickers
      } else {
        const [sigData, hData] = await Promise.all([
          getSignals(scanType),
          getHealth(),
        ])
        setSignals(sigData.signals || [])
        setHealth(hData)
        setT212Tickers([]) // Clear T212 tickers when doing regular scan
      }
      setLastUpdate(new Date())
    } catch (err) {
      console.error('Failed to fetch:', err, err.stack)
      setError(err.message || 'Failed to fetch data')
    } finally {
      setLoading(false)
    }
  }, [scanType])

  // Only fetch health on mount, not signals
  useEffect(() => {
    getHealth().then(setHealth).catch((err) => {
      console.error('Failed to fetch health:', err, err.stack)
    })
  }, [])

  // V8: Auto-refresh countdown timer
  useEffect(() => {
    if (!autoRefresh) return
    
    const timer = setInterval(() => {
      setSecondsUntilRefresh(prev => {
        if (prev <= 1) {
          // Time to refresh
          if (!loading && hasScanned) {
            refresh()
          }
          return 60
        }
        return prev - 1
      })
    }, 1000)
    
    return () => clearInterval(timer)
  }, [autoRefresh, loading, hasScanned, refresh])

  const buyCount = signals.filter(s => s.action === 'BUY').length
  const watchCount = signals.filter(s => s.action === 'WATCH').length
  const avgConf = signals.length
    ? (signals.reduce((s, x) => s + (x.confidence || 0), 0) / signals.length).toFixed(0)
    : 0

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold text-white">Signal Dashboard</h2>
          <p className="text-sm text-gray-500">
            {lastUpdate ? `Last updated ${lastUpdate.toLocaleTimeString()}` : 'Loading...'}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <select
            value={scanType}
            onChange={(e) => setScanType(e.target.value)}
            disabled={loading}
            className="bg-gray-800 border border-gray-700 text-white rounded px-3 py-2 text-sm focus:outline-none focus:border-oracle-500 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <option value="volume">Top Volume</option>
            <option value="rvol">Top RVOL</option>
            <option value="gainers">Top Gainers</option>
            <option value="finviz">Finviz Top Gainers</option>
            <option value="finviz-under2">Finviz Under $2</option>
            <option value="trading212">🔥 Trading 212 Movers</option>
            <option value="professional">Professional (Default)</option>
            <option value="professional-discovery">Professional (Discovery)</option>
            <option value="professional-all">Professional (All Sources)</option>
            <option value="professional-penny">Professional (Penny Stocks)</option>
            <option value="htf-prefer-bullish">HTF: Prefer Bullish</option>
            <option value="htf-only-bullish">HTF: Only Bullish</option>
            <option value="htf-include-reversals">HTF: Include Reversals</option>
          </select>
          {/* V8: Auto-refresh toggle */}
          <label className="flex items-center gap-2 text-xs text-gray-400 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => {
                setAutoRefresh(e.target.checked)
                if (e.target.checked) setSecondsUntilRefresh(60)
              }}
              className="w-3.5 h-3.5 rounded border-gray-600 bg-gray-700 text-oracle-500 focus:ring-oracle-500"
            />
            <span className={autoRefresh ? 'text-oracle-400' : ''}>
              Auto {autoRefresh && `(${secondsUntilRefresh}s)`}
            </span>
          </label>
          <button onClick={refresh} disabled={loading} className="btn-primary flex items-center gap-2">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* Error display */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/50 rounded-lg p-3 mb-4 text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Stats row */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        <div className="card">
          <div className="stat-label">Total Signals</div>
          <div className="stat-value">{signals.length}</div>
        </div>
        <div className="card">
          <div className="stat-label">BUY Signals</div>
          <div className="stat-value text-emerald-400">{buyCount}</div>
        </div>
        <div className="card">
          <div className="stat-label">WATCH</div>
          <div className="stat-value text-amber-400">{watchCount}</div>
        </div>
        <div className="card">
          <div className="stat-label">Avg Confidence</div>
          <div className="stat-value">{avgConf}%</div>
        </div>
      </div>

      {/* Loading spinner */}
      {loading && (
        <div className="card text-center py-16">
          <div className="relative mx-auto mb-4">
            <div className="w-16 h-16 border-4 border-oracle-500/30 border-t-oracle-500 rounded-full animate-spin mx-auto"></div>
            <div className="absolute inset-0 flex items-center justify-center">
              <RefreshCw className="w-6 h-6 text-oracle-500 animate-spin" />
            </div>
          </div>
          <h3 className="text-lg font-semibold text-white mb-2">
            {scanType === 'trading212' ? 'Fetching Trading 212 Movers...' : 'Scanning Market Data...'}
          </h3>
          <p className="text-sm text-gray-500">
            {scanType === 'trading212' ? 'Discovering top movers from Trading 212' :
              scanType === 'finviz' ? 'Analyzing Finviz gainers' : 
              scanType === 'professional-penny' ? 'Scanning penny stocks' : 
              scanType === 'htf-prefer-bullish' ? 'HTF Scan: Preferring bullish HTF alignment' :
              scanType === 'htf-only-bullish' ? 'HTF Scan: Only bullish HTF candidates' :
              scanType === 'htf-include-reversals' ? 'HTF Scan: Including reversal candidates' :
              'Analyzing market data'}...
          </p>
          <p className="text-xs text-gray-600 mt-2">
            Running: Volume Profile → Regime Detection → ICT Analysis → Signal Generation
          </p>
        </div>
      )}

      {/* Trading 212 Movers Display */}
      {t212Tickers.length > 0 && (
        <div className="card mb-4 border-red-500/20">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <Flame className="w-4 h-4 text-red-400" />
              <span className="text-sm font-medium text-white">Trading 212 Movers</span>
              <span className="text-xs text-gray-500">({t212Tickers.length} tickers)</span>
            </div>
            <button
              onClick={() => setT212Tickers([])}
              className="text-xs text-gray-500 hover:text-white"
            >
              Clear
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            {t212Tickers.map(ticker => (
              <a
                key={ticker}
                href={`/intelligence?analyze=${ticker}`}
                onClick={(e) => {
                  e.preventDefault();
                  // Navigate to intelligence and analyze
                  window.location.href = `/intelligence?analyze=${ticker}`;
                }}
                className="bg-gray-800 hover:bg-oracle-500/20 text-gray-300 hover:text-white px-3 py-1 rounded text-sm transition-colors"
              >
                {ticker}
              </a>
            ))}
          </div>
          <p className="text-xs text-gray-500 mt-2">
            Click any ticker to analyze with Intelligence Engine
          </p>
        </div>
      )}

      {/* Clear results button */}
      {signals.length > 0 && !loading && (
        <div className="flex justify-end mb-4">
          <button
            onClick={() => { setSignals([]); setHasScanned(false); }}
            className="text-sm text-gray-500 hover:text-white transition-colors flex items-center gap-1"
          >
            <XCircle className="w-4 h-4" />
            Clear Results
          </button>
        </div>
      )}

      {/* Signal cards */}
      {signals.length === 0 && !loading && !hasScanned && (
        <div className="card text-center py-12 text-gray-500">
          <Target className="w-12 h-12 mx-auto mb-3 opacity-30" />
          <p>No signals generated. Click Refresh to scan.</p>
        </div>
      )}
      
      {signals.length === 0 && !loading && hasScanned && (
        <div className="card text-center py-12 text-gray-500">
          <Target className="w-12 h-12 mx-auto mb-3 opacity-30" />
          <p>Scan complete. No trading signals found.</p>
          <p className="text-sm mt-2">Try a different scan type or check back later.</p>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {signals.map((sig, i) => (
          <SignalCard key={sig.id || i} signal={sig} />
        ))}
      </div>
    </div>
  )
}
