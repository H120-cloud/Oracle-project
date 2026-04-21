import { useState } from 'react'
import { Play, BarChart3, TrendingUp, TrendingDown, AlertCircle } from 'lucide-react'
import { runBacktest } from '../api'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

export default function Backtest() {
  const [config, setConfig] = useState({
    ticker: 'AAPL',
    start_date: '2024-01-01',
    end_date: '2024-06-30',
    interval: '1d',
    initial_capital: 10000,
  })
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const run = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await runBacktest(config)
      setResult(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const tradeChartData = result?.trades?.map((t, i) => ({
    name: `#${i + 1}`,
    pnl: t.pnl_pct,
  })) || []

  return (
    <div>
      <h2 className="text-2xl font-bold text-white mb-6">Backtesting</h2>

      {/* Config Form */}
      <div className="card mb-6">
        <div className="card-header">Configuration</div>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <div>
            <label className="text-xs text-gray-500 block mb-1">Ticker</label>
            <input
              className="input-field w-full"
              value={config.ticker}
              onChange={e => setConfig({ ...config, ticker: e.target.value.toUpperCase() })}
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">Start Date</label>
            <input
              type="date"
              className="input-field w-full"
              value={config.start_date}
              onChange={e => setConfig({ ...config, start_date: e.target.value })}
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">End Date</label>
            <input
              type="date"
              className="input-field w-full"
              value={config.end_date}
              onChange={e => setConfig({ ...config, end_date: e.target.value })}
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">Interval</label>
            <select
              className="input-field w-full"
              value={config.interval}
              onChange={e => setConfig({ ...config, interval: e.target.value })}
            >
              <option value="1m">1 min</option>
              <option value="5m">5 min</option>
              <option value="1d">1 day</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">Capital</label>
            <input
              type="number"
              className="input-field w-full"
              value={config.initial_capital}
              onChange={e => setConfig({ ...config, initial_capital: Number(e.target.value) })}
            />
          </div>
        </div>
        <button onClick={run} disabled={loading} className="btn-primary mt-4 flex items-center gap-2">
          <Play className={`w-4 h-4 ${loading ? 'animate-pulse' : ''}`} />
          {loading ? 'Running...' : 'Run Backtest'}
        </button>
      </div>

      {error && (
        <div className="card border-red-800 bg-red-900/20 mb-6 flex items-center gap-2">
          <AlertCircle className="w-5 h-5 text-red-400" />
          <span className="text-red-400 text-sm">{error}</span>
        </div>
      )}

      {result && (
        <>
          {/* Stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <div className="card">
              <div className="stat-label">Total Trades</div>
              <div className="stat-value">{result.total_trades}</div>
            </div>
            <div className="card">
              <div className="stat-label">Win Rate</div>
              <div className={`stat-value ${result.win_rate >= 50 ? 'text-emerald-400' : 'text-red-400'}`}>
                {result.win_rate}%
              </div>
            </div>
            <div className="card">
              <div className="stat-label">Total Return</div>
              <div className={`stat-value ${result.total_return_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {result.total_return_pct > 0 ? '+' : ''}{result.total_return_pct}%
              </div>
            </div>
            <div className="card">
              <div className="stat-label">Max Drawdown</div>
              <div className="stat-value text-red-400">-{result.max_drawdown_pct}%</div>
            </div>
            <div className="card">
              <div className="stat-label">Profit Factor</div>
              <div className="stat-value">{result.profit_factor}</div>
            </div>
            <div className="card">
              <div className="stat-label">Sharpe Ratio</div>
              <div className="stat-value">{result.sharpe_ratio ?? '—'}</div>
            </div>
            <div className="card">
              <div className="stat-label">Avg Win</div>
              <div className="stat-value text-emerald-400">+{result.avg_win_pct}%</div>
            </div>
            <div className="card">
              <div className="stat-label">Avg Loss</div>
              <div className="stat-value text-red-400">{result.avg_loss_pct}%</div>
            </div>
          </div>

          {/* PnL Chart */}
          {tradeChartData.length > 0 && (
            <div className="card mb-6">
              <div className="card-header">Trade PnL Distribution</div>
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={tradeChartData}>
                  <XAxis dataKey="name" tick={{ fill: '#6b7280', fontSize: 11 }} />
                  <YAxis tick={{ fill: '#6b7280', fontSize: 11 }} />
                  <Tooltip
                    contentStyle={{ background: '#1f2937', border: '1px solid #374151', borderRadius: 8 }}
                    labelStyle={{ color: '#fff' }}
                  />
                  <Bar dataKey="pnl" radius={[4, 4, 0, 0]}>
                    {tradeChartData.map((entry, index) => (
                      <Cell key={index} fill={entry.pnl >= 0 ? '#10b981' : '#ef4444'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Trade List */}
          {result.trades?.length > 0 && (
            <div className="card">
              <div className="card-header">Trade Log</div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-gray-500 text-xs uppercase">
                      <th className="text-left py-2 px-3">#</th>
                      <th className="text-left py-2 px-3">Entry</th>
                      <th className="text-left py-2 px-3">Exit</th>
                      <th className="text-right py-2 px-3">Entry $</th>
                      <th className="text-right py-2 px-3">Exit $</th>
                      <th className="text-left py-2 px-3">Action</th>
                      <th className="text-right py-2 px-3">PnL %</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.trades.map((t, i) => (
                      <tr key={i} className="border-t border-gray-800 hover:bg-gray-800/50">
                        <td className="py-2 px-3 text-gray-400">{i + 1}</td>
                        <td className="py-2 px-3 text-gray-300">{t.entry_date?.slice(0, 19)}</td>
                        <td className="py-2 px-3 text-gray-300">{t.exit_date?.slice(0, 19)}</td>
                        <td className="py-2 px-3 text-right text-white">${t.entry_price}</td>
                        <td className="py-2 px-3 text-right text-white">${t.exit_price}</td>
                        <td className="py-2 px-3">
                          <span className={t.action === 'TARGET_HIT' ? 'badge-buy' : 'badge-avoid'}>
                            {t.action}
                          </span>
                        </td>
                        <td className={`py-2 px-3 text-right font-semibold ${
                          t.pnl_pct >= 0 ? 'text-emerald-400' : 'text-red-400'
                        }`}>
                          {t.pnl_pct > 0 ? '+' : ''}{t.pnl_pct}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
