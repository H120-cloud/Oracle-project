import { useEffect, useRef, useState } from 'react'
import {
  secCandidates,
  secDilutionRisk,
  secStructuralTraps,
  secCleanWatchlist,
  secSerialDiluters,
  secStats,
  secScanNow,
} from '../api_strategic'

export default function SECIntelligence() {
  const [tab, setTab] = useState('all')
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState([])
  const [stats, setStats] = useState(null)
  const [scanTickers, setScanTickers] = useState('')
  const [scanResult, setScanResult] = useState(null)

  // Latest-wins guard: rapid tab switches fire overlapping requests, so only
  // the most recent one is allowed to write state. Bumped on unmount too, so a
  // late response can't setState after the component is gone.
  const reqIdRef = useRef(0)
  useEffect(() => () => { reqIdRef.current += 1 }, [])

  const load = async (tabKey) => {
    const reqId = ++reqIdRef.current
    setLoading(true)
    try {
      let result = []
      if (tabKey === 'all') result = await secCandidates({ limit: 200 })
      else if (tabKey === 'dilution') result = await secDilutionRisk(100)
      else if (tabKey === 'traps') result = await secStructuralTraps(100)
      else if (tabKey === 'clean') result = await secCleanWatchlist(100)
      else if (tabKey === 'serial') result = await secSerialDiluters(100)
      if (reqId !== reqIdRef.current) return
      setData(Array.isArray(result) ? result : [])
    } catch (e) {
      if (reqId !== reqIdRef.current) return
      console.error(e)
    } finally {
      if (reqId === reqIdRef.current) setLoading(false)
    }
  }

  useEffect(() => { load(tab) }, [tab])
  useEffect(() => {
    secStats().then(setStats).catch(console.error)
  }, [])

  const handleScan = async () => {
    const tickers = scanTickers.split(/[,\s]+/).filter(Boolean)
    if (!tickers.length) return
    setLoading(true)
    try {
      const res = await secScanNow(tickers)
      setScanResult(res)
      load(tab)
      secStats().then(setStats)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  const pill = (label, key) => (
    <button
      key={key}
      onClick={() => setTab(key)}
      className={`px-3 py-1.5 rounded-md text-sm font-medium transition ${
        tab === key
          ? 'bg-oracle-600 text-white'
          : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
      }`}
    >
      {label}
    </button>
  )

  const scoreColor = (v) => {
    if (v >= 70) return 'text-red-400'
    if (v >= 40) return 'text-yellow-400'
    return 'text-green-400'
  }

  const scoreBg = (v) => {
    if (v >= 70) return 'bg-red-500/10 border-red-500/20'
    if (v >= 40) return 'bg-yellow-500/10 border-yellow-500/20'
    return 'bg-green-500/10 border-green-500/20'
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">SEC Filing Intelligence</h1>
          <p className="text-sm text-gray-400 mt-1">
            Dilution risk, toxic financing, structural traps, balance sheet health.
          </p>
        </div>
        {stats && (
          <div className="text-right text-xs text-gray-400 space-y-0.5">
            <p>Candidates: <span className="text-white font-semibold">{stats.candidates_tracked}</span></p>
            <p>Outcomes: <span className="text-white font-semibold">{stats.outcomes_resolved}/{stats.outcomes_total}</span></p>
            <p>Accuracy: <span className="text-white font-semibold">{Number.isFinite(stats.structural_accuracy) ? (stats.structural_accuracy * 100).toFixed(1) : '0.0'}%</span></p>
          </div>
        )}
      </div>

      {/* Scan bar */}
      <div className="flex gap-2 items-stretch">
        <input
          className="flex-1 bg-gray-800 border border-gray-700 rounded-md px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-oracle-500"
          placeholder="Scan tickers (comma or space separated): e.g. AAPL, TSLA, GME..."
          value={scanTickers}
          onChange={(e) => setScanTickers(e.target.value)}
        />
        <button
          onClick={handleScan}
          disabled={loading}
          className="bg-oracle-600 hover:bg-oracle-500 text-white text-sm font-medium px-4 py-2 rounded-md transition disabled:opacity-50"
        >
          Scan Now
        </button>
      </div>
      {scanResult && (
        <div className="text-sm text-gray-300 bg-gray-800 border border-gray-700 rounded-md px-3 py-2">
          Scanned <span className="text-white font-semibold">{scanResult.scanned}</span> tickers.
        </div>
      )}

      {/* Tabs */}
      <div className="flex flex-wrap gap-2">
        {pill('All', 'all')}
        {pill('Dilution Risk', 'dilution')}
        {pill('Structural Traps', 'traps')}
        {pill('Clean Watchlist', 'clean')}
        {pill('Serial Diluters', 'serial')}
      </div>

      {/* Grid */}
      {loading && (
        <div className="text-sm text-gray-400">Loading SEC intelligence...</div>
      )}
      {!loading && data.length === 0 && (
        <div className="text-sm text-gray-500">No candidates yet. Use Scan Now to analyze tickers.</div>
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {data.map((c) => {
          const action = (c.oracle_action || '').replace('_', ' ').toUpperCase()
          const behavior = (c.dilution_behavior || '').replace('_', ' ').toUpperCase()
          return (
            <div
              key={c.ticker}
              className={`rounded-lg border p-4 space-y-3 ${scoreBg(c.structural_trap_risk_score)}`}
            >
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-lg font-bold text-white">{c.ticker}</div>
                  <div className="text-xs text-gray-400">{c.company_name || '—'}</div>
                </div>
                <div className="text-right">
                  <div className={`text-xs font-semibold ${scoreColor(c.structural_trap_risk_score)}`}>
                    {action}
                  </div>
                  <div className="text-[10px] text-gray-500 mt-0.5">{behavior}</div>
                </div>
              </div>

              {/* Score row */}
              <div className="grid grid-cols-3 gap-2 text-xs">
                <ScoreItem label="Dilution Prob" value={c.dilution_probability_score} />
                <ScoreItem label="Toxic Fin" value={c.toxic_financing_score} />
                <ScoreItem label="Warrant" value={c.warrant_overhang_score} />
                <ScoreItem label="Cash Runway" value={c.cash_runway_score} invert />
                <ScoreItem label="Survival" value={c.survival_risk_score} />
                <ScoreItem label="Balance" value={c.balance_sheet_quality_score} invert />
                <ScoreItem label="Offering" value={c.offering_risk_score} />
                <ScoreItem label="RS Risk" value={c.reverse_split_risk_score} />
                <ScoreItem label="Trap Risk" value={c.structural_trap_risk_score} />
              </div>

              {/* Flags */}
              <div className="flex flex-wrap gap-1.5">
                {c.atm_active && <Flag text="ATM" type="bad" />}
                {c.going_concern_active && <Flag text="Going Concern" type="bad" />}
                {c.offerings_last_12mo >= 2 && (
                  <Flag text={`${c.offerings_last_12mo} offerings/12mo`} type="warn" />
                )}
                {c.reverse_splits_last_36mo > 0 && (
                  <Flag text={`${c.reverse_splits_last_36mo} RS/36mo`} type="bad" />
                )}
                {c.share_growth_pct_12mo > 50 && (
                  <Flag text={`${c.share_growth_pct_12mo}% share growth`} type="warn" />
                )}
                {!c.atm_active && c.dilution_probability_score < 30 && (
                  <Flag text="No active dilution" type="good" />
                )}
              </div>

              {/* Summary */}
              <div className="text-xs text-gray-300 leading-relaxed">
                {c.why_it_matters}
              </div>
              <div className="text-[10px] text-gray-500">
                Updated {new Date(c.last_updated).toLocaleString()}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function ScoreItem({ label, value, invert = false }) {
  const color = invert
    ? value >= 70 ? 'text-green-400' : value >= 40 ? 'text-yellow-400' : 'text-red-400'
    : value >= 70 ? 'text-red-400' : value >= 40 ? 'text-yellow-400' : 'text-green-400'
  return (
    <div className="bg-gray-950/40 rounded px-2 py-1.5 text-center">
      <div className="text-gray-500">{label}</div>
      <div className={`font-bold ${color}`}>{Number.isFinite(value) ? value.toFixed(0) : '—'}</div>
    </div>
  )
}

function Flag({ text, type }) {
  const map = {
    bad: 'bg-red-500/15 text-red-400 border-red-500/25',
    warn: 'bg-yellow-500/15 text-yellow-400 border-yellow-500/25',
    good: 'bg-green-500/15 text-green-400 border-green-500/25',
  }
  return (
    <span className={`text-[10px] font-medium border rounded px-1.5 py-0.5 ${map[type] || map.warn}`}>
      {text}
    </span>
  )
}
