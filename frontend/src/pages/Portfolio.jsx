import { useState, useEffect, useCallback } from 'react'
import { 
  Briefcase, 
  TrendingUp, 
  TrendingDown, 
  RefreshCw,
  Target,
  BarChart3,
} from 'lucide-react'

const API = ''
const REFRESH_INTERVAL = 30 * 1000 // 30 seconds (matches paper trading price loop)

function PositionCard({ position, onClose }) {
  const pnlPct = position.unrealized_pnl_pct || 0
  const isProfitable = pnlPct >= 0

  return (
    <div className="card hover:border-gray-600 transition-all relative">
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <div className={`p-2 rounded-lg ${isProfitable ? 'bg-emerald-500/10' : 'bg-red-500/10'}`}>
            {isProfitable ? <TrendingUp className="w-5 h-5 text-emerald-400" /> : <TrendingDown className="w-5 h-5 text-red-400" />}
          </div>
          <div>
            <h3 className="text-xl font-bold text-white">{position.ticker}</h3>
            <p className="text-xs text-gray-500">{position.qty} shares • Grade {position.grade || '?'}</p>
          </div>
        </div>
        <div className="text-right">
          <div className={`text-lg font-bold ${isProfitable ? 'text-emerald-400' : 'text-red-400'}`}>
            {isProfitable ? '+' : ''}{pnlPct.toFixed(2)}%
          </div>
          <p className="text-xs text-gray-500">{isProfitable ? '+' : ''}${(position.unrealized_pnl || 0).toFixed(2)}</p>
        </div>
      </div>

      {/* Price Grid */}
      <div className="grid grid-cols-3 gap-2 mb-3 p-2 bg-gray-900/50 rounded-lg text-xs">
        <div><span className="text-gray-500">Entry</span><div className="text-white font-semibold">${position.entry_price?.toFixed(2)}</div></div>
        <div><span className="text-gray-500">Current</span><div className="text-white font-semibold">${position.current_price?.toFixed(2)}</div></div>
        <div><span className="text-gray-500">Stop</span><div className="text-red-400 font-semibold">${position.stop_price?.toFixed(2)}</div></div>
      </div>

      {/* Trailing Stop Status */}
      <div className="flex flex-wrap gap-1.5 mb-3">
        {position.moved_to_breakeven && (
          <span className="px-2 py-0.5 rounded text-xs bg-yellow-900/40 text-yellow-400">Breakeven</span>
        )}
        {position.trailing_active && (
          <span className="px-2 py-0.5 rounded text-xs bg-purple-900/40 text-purple-400">Trailing Active</span>
        )}
        {position.highest_price_reached > position.entry_price && (
          <span className="px-2 py-0.5 rounded text-xs bg-blue-900/40 text-blue-400">
            High: ${position.highest_price_reached?.toFixed(2)}
          </span>
        )}
        {position.htf_bias && (
          <span className={`px-2 py-0.5 rounded text-xs ${
            position.htf_bias === 'BULLISH' ? 'bg-green-900/40 text-green-400' :
            position.htf_bias === 'BEARISH' ? 'bg-red-900/40 text-red-400' :
            'bg-gray-700/40 text-gray-400'}`}>{position.htf_bias}</span>
        )}
      </div>

      {/* Target */}
      {position.targets && position.targets.length > 0 && (
        <div className="text-xs text-gray-500 mb-3">
          <Target className="w-3 h-3 inline mr-1" />
          Target: ${position.targets[0]?.toFixed(2)}
        </div>
      )}

      {/* Close Button */}
      {onClose && (
        <button
          onClick={() => onClose(position.ticker, position.current_price)}
          className="w-full mt-2 px-3 py-1.5 bg-red-900/30 hover:bg-red-900/50 text-red-400 text-xs rounded transition-colors"
        >
          Close Position
        </button>
      )}
    </div>
  )
}

export default function Portfolio() {
  const [positions, setPositions] = useState([])
  const [trades, setTrades] = useState([])
  const [perf, setPerf] = useState(null)
  const [loading, setLoading] = useState(false)
  const [lastUpdate, setLastUpdate] = useState(null)
  const [tab, setTab] = useState('open')

  const fetchAll = useCallback(async () => {
    setLoading(true)
    try {
      const [p, t, pf] = await Promise.all([
        fetch(`${API}/api/v1/paper/positions`).then(r=>r.json()).catch(()=>({positions:[]})),
        fetch(`${API}/api/v1/paper/trades?limit=200`).then(r=>r.json()).catch(()=>({trades:[]})),
        fetch(`${API}/api/v1/paper/performance`).then(r=>r.json()).catch(()=>null),
      ])
      setPositions(p.positions||[])
      setTrades(t.trades||[])
      setPerf(pf)
      setLastUpdate(new Date())
    } catch(e) { console.error(e) }
    setLoading(false)
  }, [])

  useEffect(() => {
    fetchAll()
    const iv = setInterval(fetchAll, REFRESH_INTERVAL)
    return () => clearInterval(iv)
  }, [fetchAll])

  const closePosition = async (ticker, price) => {
    if (!confirm(`Close ${ticker} at $${price?.toFixed(2)}?`)) return
    try {
      await fetch(`${API}/api/v1/paper/close/${ticker}?exit_price=${price}`, { method: 'POST' })
      fetchAll()
    } catch(e) { console.error(e) }
  }

  const totalUnrealizedPnl = positions.reduce((s,p) => s + (p.unrealized_pnl||0), 0)
  const totalRealizedPnl = perf?.total_pnl || 0

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold text-white flex items-center gap-2">
            <Briefcase className="w-6 h-6 text-oracle-500" />
            Portfolio
          </h2>
          <p className="text-sm text-gray-500">
            {lastUpdate ? `Updated ${lastUpdate.toLocaleTimeString()}` : 'Loading...'}
            {' • Auto-refreshing every 30s'}
          </p>
        </div>
        <button onClick={fetchAll} disabled={loading} className="btn-primary flex items-center gap-2">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
        <div className="card"><p className="text-gray-400 text-xs mb-1">Open Positions</p><p className="text-xl font-bold text-white">{positions.length}</p></div>
        <div className="card"><p className="text-gray-400 text-xs mb-1">Unrealized P&L</p>
          <p className={`text-xl font-bold ${totalUnrealizedPnl>=0?'text-emerald-400':'text-red-400'}`}>${totalUnrealizedPnl.toFixed(2)}</p></div>
        <div className="card"><p className="text-gray-400 text-xs mb-1">Realized P&L</p>
          <p className={`text-xl font-bold ${totalRealizedPnl>=0?'text-emerald-400':'text-red-400'}`}>${totalRealizedPnl.toFixed(2)}</p></div>
        <div className="card"><p className="text-gray-400 text-xs mb-1">Win Rate</p>
          <p className="text-xl font-bold text-white">{perf?.win_rate||0}%</p></div>
        <div className="card"><p className="text-gray-400 text-xs mb-1">Profit Factor</p>
          <p className="text-xl font-bold text-white">{perf?.profit_factor||0}</p></div>
      </div>

      {/* Tabs */}
      <div className="flex gap-4 mb-4 border-b border-gray-800">
        {['open','closed'].map(t => (
          <button key={t} onClick={()=>setTab(t)}
            className={`pb-2 px-1 text-sm font-medium transition-colors ${
              tab===t ? 'text-oracle-400 border-b-2 border-oracle-400' : 'text-gray-500 hover:text-gray-300'}`}>
            {t==='open' ? `Open (${positions.length})` : `Closed (${trades.length})`}
          </button>
        ))}
      </div>

      {/* Open Positions Tab */}
      {tab==='open' && (
        positions.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {positions.map(p => (
              <PositionCard key={p.ticker} position={p} onClose={closePosition} />
            ))}
          </div>
        ) : (
          <div className="card text-center py-12 text-gray-500">
            <Briefcase className="w-12 h-12 mx-auto mb-3 opacity-30" />
            <p>No open positions.</p>
            <p className="text-sm mt-2">Signals with BUY action will auto-execute here.</p>
          </div>
        )
      )}

      {/* Closed Trades Tab */}
      {tab==='closed' && (
        trades.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-400 text-xs border-b border-gray-800">
                  <th className="text-left py-2 px-3">Ticker</th>
                  <th className="text-center py-2 px-3">Entry</th>
                  <th className="text-center py-2 px-3">Exit</th>
                  <th className="text-center py-2 px-3">P&L %</th>
                  <th className="text-center py-2 px-3">P&L $</th>
                  <th className="text-center py-2 px-3">Max R</th>
                  <th className="text-center py-2 px-3">Realized R</th>
                  <th className="text-center py-2 px-3">Exit Reason</th>
                  <th className="text-center py-2 px-3">Hold</th>
                </tr>
              </thead>
              <tbody>
                {trades.slice().reverse().map((t,i)=>(
                  <tr key={i} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                    <td className="py-2 px-3 font-semibold text-white">{t.ticker}</td>
                    <td className="text-center py-2 px-3">${t.entry_price?.toFixed(2)}</td>
                    <td className="text-center py-2 px-3">${t.exit_price?.toFixed(2)}</td>
                    <td className={`text-center py-2 px-3 font-semibold ${t.pnl_pct>=0?'text-emerald-400':'text-red-400'}`}>
                      {t.pnl_pct>=0?'+':''}{t.pnl_pct?.toFixed(2)}%</td>
                    <td className={`text-center py-2 px-3 ${t.pnl_dollars>=0?'text-emerald-400':'text-red-400'}`}>
                      {t.pnl_dollars>=0?'+':''}{t.pnl_dollars?.toFixed(2)}</td>
                    <td className="text-center py-2 px-3 text-cyan-400">{t.max_r_reached?.toFixed(1)}R</td>
                    <td className="text-center py-2 px-3 text-blue-400">{t.realized_r?.toFixed(1)}R</td>
                    <td className="text-center py-2 px-3"><span className={`px-2 py-0.5 rounded text-xs ${
                      t.exit_reason==='target'?'bg-green-900/40 text-green-400':
                      t.exit_reason==='trailing_stop'?'bg-purple-900/40 text-purple-400':
                      t.exit_reason==='breakeven'?'bg-yellow-900/40 text-yellow-400':
                      t.exit_reason==='time_exit'?'bg-gray-700/40 text-gray-400':
                      'bg-red-900/40 text-red-400'}`}>{t.exit_reason}</span></td>
                    <td className="text-center py-2 px-3 text-gray-400">{t.hold_minutes}m</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="card text-center py-12 text-gray-500">
            <BarChart3 className="w-12 h-12 mx-auto mb-3 opacity-30" />
            <p>No closed trades yet.</p>
          </div>
        )
      )}
    </div>
  )
}
