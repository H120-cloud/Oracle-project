import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  Clock,
  EyeOff,
  Filter,
  RefreshCw,
  Search,
  Target,
  TrendingUp,
} from 'lucide-react'
import {
  newsMomentumTimingReviews,
  newsMomentumTimingSummary,
} from '../api_strategic'

const LABELS = [
  'ALL',
  'EARLY_WIN',
  'ON_TIME_WIN',
  'LATE_CHASE',
  'MISSED_ALERT',
  'MISSED_DISCOVERY',
  'FALSE_POSITIVE',
  'TRAP_ALERT',
  'NEUTRAL',
]

const LABEL_STYLES = {
  EARLY_WIN: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/25',
  ON_TIME_WIN: 'bg-lime-500/10 text-lime-300 border-lime-500/25',
  LATE_CHASE: 'bg-orange-500/10 text-orange-300 border-orange-500/25',
  MISSED_ALERT: 'bg-red-500/10 text-red-300 border-red-500/25',
  MISSED_DISCOVERY: 'bg-fuchsia-500/10 text-fuchsia-300 border-fuchsia-500/25',
  FALSE_POSITIVE: 'bg-yellow-500/10 text-yellow-300 border-yellow-500/25',
  TRAP_ALERT: 'bg-rose-500/10 text-rose-300 border-rose-500/25',
  NEUTRAL: 'bg-gray-700/50 text-gray-300 border-gray-600',
}

function fmtPct(value) {
  if (value === null || value === undefined) return '-'
  const n = Number(value)
  if (!Number.isFinite(n)) return '-'
  return `${n >= 0 ? '+' : ''}${n.toFixed(1)}%`
}

function fmtDate(value) {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString()
  } catch {
    return '-'
  }
}

function LabelBadge({ label }) {
  return (
    <span className={`inline-flex items-center rounded border px-2 py-0.5 text-xs font-semibold ${LABEL_STYLES[label] || LABEL_STYLES.NEUTRAL}`}>
      {label?.replaceAll('_', ' ') || 'UNKNOWN'}
    </span>
  )
}

function SummaryCard({ title, value, icon: Icon, tone = 'text-white' }) {
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900/70 p-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs text-gray-500">{title}</p>
          <p className={`mt-1 text-2xl font-bold ${tone}`}>{value ?? 0}</p>
        </div>
        <Icon className={`h-5 w-5 ${tone}`} />
      </div>
    </div>
  )
}

export default function TimingReview() {
  const [rows, setRows] = useState([])
  const [summary, setSummary] = useState(null)
  const [label, setLabel] = useState('ALL')
  const [ticker, setTicker] = useState('')
  const [source, setSource] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const params = useMemo(() => ({
    ticker: ticker.trim(),
    label: label === 'ALL' ? '' : label,
    source_system: source,
    limit: 250,
  }), [ticker, label, source])

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const [reviewData, summaryData] = await Promise.all([
        newsMomentumTimingReviews(params),
        newsMomentumTimingSummary(params),
      ])
      setRows(reviewData.items || [])
      setSummary(summaryData)
    } catch (e) {
      setError(e.message || 'Failed to load timing reviews')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [params])

  const byLabel = summary?.by_label || {}

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
            <Clock className="h-6 w-6 text-oracle-500" />
            Timing Review
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            EOD review of whether Oracle was early, late, blocked, or blind on runner stocks.
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-md bg-oracle-600 px-4 py-2 text-sm font-medium text-white hover:bg-oracle-500 disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-4">
        <SummaryCard title="Total Reviews" value={summary?.total || 0} icon={Filter} />
        <SummaryCard title="Early / On Time" value={(byLabel.EARLY_WIN || 0) + (byLabel.ON_TIME_WIN || 0)} icon={TrendingUp} tone="text-emerald-300" />
        <SummaryCard title="Missed" value={(byLabel.MISSED_ALERT || 0) + (byLabel.MISSED_DISCOVERY || 0)} icon={EyeOff} tone="text-red-300" />
        <SummaryCard title="Late Chase" value={byLabel.LATE_CHASE || 0} icon={AlertTriangle} tone="text-orange-300" />
      </div>

      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-gray-800 bg-gray-900/70 p-4">
        <div className="relative">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-gray-500" />
          <input
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            placeholder="Ticker"
            className="w-36 rounded-md border border-gray-700 bg-gray-800 py-2 pl-9 pr-3 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-oracle-500"
          />
        </div>
        <select
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          className="rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-oracle-500"
        >
          {LABELS.map((item) => (
            <option key={item} value={item}>{item.replaceAll('_', ' ')}</option>
          ))}
        </select>
        <select
          value={source}
          onChange={(e) => setSource(e.target.value)}
          className="rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-oracle-500"
        >
          <option value="">All Sources</option>
          <option value="news_momentum">News Momentum</option>
          <option value="pre_news">Pre-News</option>
          <option value="rocket_shadow">Rocket Shadow</option>
          <option value="sec">SEC</option>
        </select>
      </div>

      <div className="overflow-hidden rounded-lg border border-gray-800 bg-gray-900/70">
        <table className="min-w-full divide-y divide-gray-800 text-sm">
          <thead className="bg-gray-900">
            <tr className="text-left text-xs uppercase tracking-wide text-gray-500">
              <th className="px-4 py-3">Ticker</th>
              <th className="px-4 py-3">Label</th>
              <th className="px-4 py-3">Before</th>
              <th className="px-4 py-3">After</th>
              <th className="px-4 py-3">Issue</th>
              <th className="px-4 py-3">Detected</th>
              <th className="px-4 py-3">Headline</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {loading && (
              <tr>
                <td colSpan="7" className="px-4 py-8 text-center text-gray-400">Loading timing reviews...</td>
              </tr>
            )}
            {!loading && rows.length === 0 && (
              <tr>
                <td colSpan="7" className="px-4 py-8 text-center text-gray-500">No timing reviews found.</td>
              </tr>
            )}
            {!loading && rows.map((row) => (
              <tr key={row.id} className="hover:bg-gray-800/40">
                <td className="px-4 py-3">
                  <div className="font-bold text-white">{row.ticker}</div>
                  <div className="text-xs text-gray-500">{row.event_type}</div>
                </td>
                <td className="px-4 py-3"><LabelBadge label={row.timing_label} /></td>
                <td className="px-4 py-3 text-gray-300">{fmtPct(row.move_before_alert_pct)}</td>
                <td className="px-4 py-3">
                  <span className={Number(row.move_after_alert_pct || 0) >= 30 ? 'text-emerald-300 font-semibold' : 'text-gray-300'}>
                    {fmtPct(row.move_after_alert_pct)}
                  </span>
                </td>
                <td className="px-4 py-3 text-gray-300">{row.primary_issue || '-'}</td>
                <td className="px-4 py-3 text-xs text-gray-400">{fmtDate(row.detected_at)}</td>
                <td className="px-4 py-3">
                  <div className="max-w-xl text-gray-300 line-clamp-2">{row.headline || '-'}</div>
                  <div className="mt-1 flex items-center gap-2 text-xs text-gray-500">
                    <Target className="h-3 w-3" />
                    {row.catalyst_sub_type || 'unknown'} · {row.source || row.source_system}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
