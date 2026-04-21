import { useState, useEffect } from 'react'
import { RefreshCw, TrendingUp, TrendingDown, Award, Lightbulb } from 'lucide-react'
import { getPerformance, getAdjustments } from '../api'
import {
  PieChart, Pie, Cell, ResponsiveContainer, Tooltip,
} from 'recharts'

const GRADE_COLORS = {
  A: '#10b981', B: '#22c55e', C: '#eab308', D: '#f97316', F: '#ef4444',
}

export default function Performance() {
  const [perf, setPerf] = useState(null)
  const [adjustments, setAdjustments] = useState([])
  const [loading, setLoading] = useState(false)

  const refresh = async () => {
    setLoading(true)
    try {
      const [p, a] = await Promise.allSettled([
        getPerformance(),
        getAdjustments(),
      ])
      if (p.status === 'fulfilled') setPerf(p.value)
      if (a.status === 'fulfilled') setAdjustments(a.value.adjustments || [])
    } catch (err) {
      console.error('Failed to load performance:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { refresh() }, [])

  const winLossData = perf ? [
    { name: 'Wins', value: perf.total_wins, color: '#10b981' },
    { name: 'Losses', value: perf.total_losses, color: '#ef4444' },
    { name: 'Pending', value: Math.max(0, perf.total_signals - perf.total_wins - perf.total_losses), color: '#6b7280' },
  ] : []

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold text-white">Performance</h2>
        <button onClick={refresh} disabled={loading} className="btn-secondary flex items-center gap-2">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {!perf && !loading && (
        <div className="card text-center py-12 text-gray-500">
          <TrendingUp className="w-12 h-12 mx-auto mb-3 opacity-30" />
          <p>No performance data available yet. Generate signals and record outcomes first.</p>
        </div>
      )}

      {perf && (
        <>
          {/* KPI Row */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <div className="card">
              <div className="stat-label">Total Signals</div>
              <div className="stat-value">{perf.total_signals}</div>
            </div>
            <div className="card">
              <div className="stat-label">Win Rate</div>
              <div className={`stat-value ${perf.win_rate >= 50 ? 'text-emerald-400' : 'text-red-400'}`}>
                {perf.win_rate}%
              </div>
            </div>
            <div className="card">
              <div className="stat-label">Avg PnL</div>
              <div className={`stat-value ${perf.avg_pnl_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {perf.avg_pnl_pct > 0 ? '+' : ''}{perf.avg_pnl_pct}%
              </div>
            </div>
            <div className="card">
              <div className="stat-label">Profit Factor</div>
              <div className="stat-value">{perf.profit_factor}</div>
            </div>
          </div>

          {/* Win/Loss Pie + Details */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
            <div className="card">
              <div className="card-header">Win / Loss Breakdown</div>
              <ResponsiveContainer width="100%" height={200}>
                <PieChart>
                  <Pie
                    data={winLossData}
                    cx="50%"
                    cy="50%"
                    innerRadius={50}
                    outerRadius={80}
                    dataKey="value"
                  >
                    {winLossData.map((entry, i) => (
                      <Cell key={i} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{ background: '#1f2937', border: '1px solid #374151', borderRadius: 8 }}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="flex justify-center gap-4 text-xs mt-2">
                {winLossData.map(d => (
                  <div key={d.name} className="flex items-center gap-1.5">
                    <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: d.color }} />
                    <span className="text-gray-400">{d.name}: {d.value}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="card">
              <div className="card-header">Quality Metrics</div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="stat-label">Best Grade</div>
                  <div className={`text-3xl font-bold ${GRADE_COLORS[perf.best_setup_grade] ? '' : 'text-white'}`}
                       style={{ color: GRADE_COLORS[perf.best_setup_grade] }}>
                    {perf.best_setup_grade || '—'}
                  </div>
                </div>
                <div>
                  <div className="stat-label">Worst Grade</div>
                  <div className={`text-3xl font-bold`}
                       style={{ color: GRADE_COLORS[perf.worst_setup_grade] || '#9ca3af' }}>
                    {perf.worst_setup_grade || '—'}
                  </div>
                </div>
                <div>
                  <div className="stat-label">Avg Confidence</div>
                  <div className="text-2xl font-bold text-white">{perf.avg_confidence}%</div>
                </div>
                <div>
                  <div className="stat-label">Wins / Losses</div>
                  <div className="text-2xl font-bold">
                    <span className="text-emerald-400">{perf.total_wins}</span>
                    <span className="text-gray-600"> / </span>
                    <span className="text-red-400">{perf.total_losses}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </>
      )}

      {/* Self-Learning Adjustments */}
      <div className="card">
        <div className="card-header flex items-center gap-2">
          <Lightbulb className="w-4 h-4 text-amber-400" />
          Self-Learning Suggestions
        </div>
        {adjustments.length === 0 ? (
          <p className="text-sm text-gray-500">
            No adjustments suggested. Need more signal history (min 20 signals).
          </p>
        ) : (
          <div className="space-y-3">
            {adjustments.map((adj, i) => (
              <div key={i} className="flex items-start gap-3 p-3 bg-gray-800/50 rounded-lg">
                <Award className="w-5 h-5 text-oracle-400 mt-0.5 flex-shrink-0" />
                <div>
                  <div className="text-sm font-medium text-white">{adj.parameter}</div>
                  <div className="text-xs text-gray-400 mt-0.5">{adj.reason}</div>
                  <div className="text-xs mt-1">
                    <span className="text-red-400">{adj.old_value}</span>
                    <span className="text-gray-600 mx-1">→</span>
                    <span className="text-emerald-400">{adj.new_value}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
