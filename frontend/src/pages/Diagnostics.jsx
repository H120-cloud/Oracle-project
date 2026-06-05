import { useEffect, useMemo, useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from 'recharts'
import { ArrowUpDown, Download, FileDown } from 'lucide-react'
import {
  getNewsLatency, getRocketShadow, getTelegramOutbox,
  getSourceHealth, getBlockedAlerts, getFastWatchAlerts,
  getReports, downloadAdminFile, dataDownloadUrl, reportDownloadUrl,
} from '../api_admin'

const TABS = [
  { id: 'news-latency', label: 'News Latency' },
  { id: 'rocket-shadow', label: 'Rocket Shadow' },
  { id: 'telegram-outbox', label: 'Telegram Outbox' },
  { id: 'reports', label: 'Reports' },
  { id: 'source-health', label: 'Source Health' },
  { id: 'blocked-alerts', label: 'Blocked Alerts' },
  { id: 'fast-watch', label: 'FAST WATCH' },
]

const fmtBytes = (n) => {
  if (n == null) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

// ── formatters ─────────────────────────────────────────────────────────────
const fmtTime = (v) => (v ? new Date(v).toLocaleString() : '—')
const fmtNum = (v, d = 2) => (v == null || Number.isNaN(v) ? '—' : Number(v).toFixed(d))
const fmtPct = (v) => (v == null ? '—' : `${(Number(v) * 100).toFixed(1)}%`)
const fmtLat = (v) => (v == null ? '—' : `${Number(v).toFixed(1)}s`)

// ── CSV export ──────────────────────────────────────────────────────────────
function toCSV(columns, rows) {
  const esc = (val) => {
    const s = val == null ? '' : String(val)
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const header = columns.map((c) => c.label).join(',')
  const lines = rows.map((r) =>
    columns.map((c) => esc(c.csv ? c.csv(r) : c.accessor ? c.accessor(r) : r[c.key])).join(','),
  )
  return [header, ...lines].join('\n')
}
function downloadCSV(name, csv) {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

// ── data hook ───────────────────────────────────────────────────────────────
function useDiagnostics(fetcher, params) {
  const [state, setState] = useState({ loading: true, error: null, data: null })
  const key = JSON.stringify(params)
  useEffect(() => {
    let alive = true
    setState((s) => ({ ...s, loading: true, error: null }))
    fetcher(params)
      .then((d) => alive && setState({ loading: false, error: null, data: d }))
      .catch((e) => alive && setState({ loading: false, error: e.message, data: null }))
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  return state
}

// ── shared UI ───────────────────────────────────────────────────────────────
function StatCard({ label, value, tone = 'gray' }) {
  const tones = {
    gray: 'text-white', green: 'text-green-400', yellow: 'text-yellow-400',
    red: 'text-red-400', blue: 'text-oracle-400',
  }
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg px-4 py-3">
      <div className="text-xs text-gray-500 uppercase tracking-wide">{label}</div>
      <div className={`text-2xl font-bold ${tones[tone] || tones.gray}`}>{value}</div>
    </div>
  )
}

function Badge({ status }) {
  const map = {
    alerted: 'bg-green-600/20 text-green-400',
    delayed: 'bg-yellow-600/20 text-yellow-400',
    blocked: 'bg-red-600/20 text-red-400',
    sent: 'bg-green-600/20 text-green-400',
    pending: 'bg-blue-600/20 text-blue-400',
    failed: 'bg-yellow-600/20 text-yellow-400',
    dead_letter: 'bg-red-600/20 text-red-400',
    HIGH: 'bg-green-600/20 text-green-400',
    MEDIUM: 'bg-yellow-600/20 text-yellow-400',
    LOW: 'bg-gray-600/20 text-gray-400',
  }
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${map[status] || 'bg-gray-700/40 text-gray-300'}`}>
      {status || '—'}
    </span>
  )
}

function Card({ title, children }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
      {title && <div className="text-sm font-semibold text-gray-300 mb-3">{title}</div>}
      {children}
    </div>
  )
}

function FilterBar({ draft, setDraft, statusOptions, sourceLabel, onApply, onReset }) {
  const set = (k) => (e) => setDraft({ ...draft, [k]: e.target.value })
  return (
    <div className="flex flex-wrap items-end gap-3 bg-gray-900 border border-gray-800 rounded-lg p-3 mb-4">
      <Field label="Ticker">
        <input value={draft.ticker} onChange={set('ticker')} placeholder="e.g. AAPL"
          className="input" />
      </Field>
      {statusOptions && (
        <Field label="Status">
          <select value={draft.status} onChange={set('status')} className="input">
            <option value="">All</option>
            {statusOptions.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </Field>
      )}
      <Field label={sourceLabel || 'Source'}>
        <input value={draft.source} onChange={set('source')} placeholder="any"
          className="input" />
      </Field>
      <Field label="From">
        <input type="datetime-local" value={draft.start} onChange={set('start')} className="input" />
      </Field>
      <Field label="To">
        <input type="datetime-local" value={draft.end} onChange={set('end')} className="input" />
      </Field>
      <Field label="Page size">
        <select value={draft.page_size} onChange={set('page_size')} className="input">
          {[25, 50, 100, 250].map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
      </Field>
      <button onClick={onApply} className="btn-primary">Apply</button>
      <button onClick={onReset} className="btn-ghost">Reset</button>
    </div>
  )
}

function Field({ label, children }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-gray-500">{label}</span>
      {children}
    </label>
  )
}

function Pagination({ page, pageSize, total, onPage }) {
  const pages = Math.max(1, Math.ceil((total || 0) / (pageSize || 50)))
  return (
    <div className="flex items-center justify-between mt-3 text-sm text-gray-400">
      <span>{total} rows</span>
      <div className="flex items-center gap-2">
        <button disabled={page <= 1} onClick={() => onPage(page - 1)} className="btn-ghost disabled:opacity-30">Prev</button>
        <span>Page {page} / {pages}</span>
        <button disabled={page >= pages} onClick={() => onPage(page + 1)} className="btn-ghost disabled:opacity-30">Next</button>
      </div>
    </div>
  )
}

function DataTable({ columns, rows, csvName }) {
  const [sort, setSort] = useState({ key: null, dir: 'desc' })
  const sorted = useMemo(() => {
    if (!sort.key) return rows
    const col = columns.find((c) => c.key === sort.key)
    const get = col?.sortAccessor || col?.accessor || ((r) => r[sort.key])
    return [...rows].sort((a, b) => {
      const va = get(a), vb = get(b)
      if (va == null && vb == null) return 0
      if (va == null) return 1
      if (vb == null) return -1
      if (va < vb) return sort.dir === 'asc' ? -1 : 1
      if (va > vb) return sort.dir === 'asc' ? 1 : -1
      return 0
    })
  }, [rows, sort, columns])
  const toggle = (key) =>
    setSort((s) => (s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'desc' }))

  return (
    <div>
      <div className="flex justify-end mb-2">
        <button
          onClick={() => downloadCSV(csvName || 'diagnostics.csv', toCSV(columns, sorted))}
          className="btn-ghost flex items-center gap-1.5"
        >
          <Download className="w-4 h-4" /> CSV
        </button>
      </div>
      <div className="overflow-x-auto border border-gray-800 rounded-lg">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-900 text-gray-400">
            <tr>
              {columns.map((c) => (
                <th key={c.key} className="px-3 py-2 text-left font-medium whitespace-nowrap">
                  {c.sortable === false ? c.label : (
                    <button onClick={() => toggle(c.key)} className="inline-flex items-center gap-1 hover:text-white">
                      {c.label}<ArrowUpDown className="w-3 h-3 opacity-50" />
                    </button>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {sorted.length === 0 ? (
              <tr><td colSpan={columns.length} className="px-3 py-6 text-center text-gray-600">No rows</td></tr>
            ) : sorted.map((r, i) => (
              <tr key={r.id || r.alert_id || r.candidate_id || i} className="hover:bg-gray-900/60">
                {columns.map((c) => (
                  <td key={c.key} className="px-3 py-2 align-top text-gray-200 whitespace-nowrap">
                    {c.render ? c.render(r) : (c.accessor ? c.accessor(r) : r[c.key]) ?? '—'}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function BarPanel({ title, data, color = '#6366f1', valueFmt }) {
  const series = Object.entries(data || {}).map(([name, value]) => ({ name, value }))
  return (
    <Card title={title}>
      <div style={{ height: 200 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={series}>
            <XAxis dataKey="name" tick={{ fill: '#9ca3af', fontSize: 11 }} />
            <YAxis tick={{ fill: '#9ca3af', fontSize: 11 }} />
            <Tooltip formatter={valueFmt} contentStyle={{ background: '#111827', border: '1px solid #374151' }} />
            <Bar dataKey="value" radius={[3, 3, 0, 0]}>
              {series.map((_, i) => <Cell key={i} fill={color} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  )
}

function TopList({ title, rows, metric, fmt }) {
  return (
    <Card title={title}>
      <ol className="space-y-1 text-sm">
        {(rows || []).slice(0, 10).map((r, i) => (
          <li key={r.ticker + i} className="flex justify-between text-gray-300">
            <span><span className="text-gray-500 mr-2">{i + 1}.</span>{r.ticker}</span>
            <span className="text-oracle-400 font-mono">{fmt(r[metric])}</span>
          </li>
        ))}
        {(!rows || rows.length === 0) && <li className="text-gray-600">No data</li>}
      </ol>
    </Card>
  )
}

// ── server-side downloads ───────────────────────────────────────────────────
function DownloadButton({ label, url, fallbackName, icon: Icon = Download }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const onClick = async () => {
    setBusy(true); setErr(null)
    try {
      await downloadAdminFile(url, fallbackName)
    } catch (e) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <button onClick={onClick} disabled={busy}
      title={err ? `Failed: ${err}` : label}
      className={`btn-ghost flex items-center gap-1.5 ${err ? 'border-red-600 text-red-400' : ''}`}>
      <Icon className="w-4 h-4" />{busy ? 'Downloading…' : label}
    </button>
  )
}

function DownloadBar({ kind, filters }) {
  const label = { 'news-latency': 'News Latency', 'rocket-shadow': 'Rocket Shadow', 'telegram-outbox': 'Telegram Outbox' }[kind]
  return (
    <div className="flex flex-wrap items-center gap-2 mb-4">
      <span className="text-xs text-gray-500 mr-1">Download {label}:</span>
      <DownloadButton label="CSV" url={dataDownloadUrl(kind, 'csv', filters)} fallbackName={`${kind}.csv`} />
      <DownloadButton label="JSONL" url={dataDownloadUrl(kind, 'jsonl', filters)} fallbackName={`${kind}.jsonl`} />
      <DownloadButton label="JSON" url={dataDownloadUrl(kind, 'json', filters)} fallbackName={`${kind}.json`} />
    </div>
  )
}

// ── generic tab ─────────────────────────────────────────────────────────────
function DiagnosticsTab({ fetcher, columns, statusOptions, sourceLabel, csvName,
  downloadKind, renderCards, renderCharts, renderTop }) {
  const empty = { ticker: '', status: '', source: '', start: '', end: '', page_size: 50 }
  const [draft, setDraft] = useState(empty)
  const [applied, setApplied] = useState(empty)
  const [page, setPage] = useState(1)
  const params = useMemo(() => {
    const p = { ...applied, page }
    // datetime-local -> ISO
    if (p.start) p.start = new Date(p.start).toISOString()
    if (p.end) p.end = new Date(p.end).toISOString()
    return p
  }, [applied, page])
  const { loading, error, data } = useDiagnostics(fetcher, params)
  const rows = data?.items || []
  const downloadFilters = useMemo(() => {
    const { page_size, ...rest } = params // eslint-disable-line no-unused-vars
    const { page: _p, ...f } = rest // eslint-disable-line no-unused-vars
    return f
  }, [params])

  return (
    <div>
      {renderCards && data && <div className="mb-4">{renderCards(data)}</div>}
      <FilterBar
        draft={draft} setDraft={setDraft} statusOptions={statusOptions} sourceLabel={sourceLabel}
        onApply={() => { setApplied(draft); setPage(1) }}
        onReset={() => { setDraft(empty); setApplied(empty); setPage(1) }}
      />
      {downloadKind && <DownloadBar kind={downloadKind} filters={downloadFilters} />}
      {renderCharts && data && <div className="mb-4">{renderCharts(data)}</div>}
      {renderTop && data && <div className="mb-4">{renderTop(data)}</div>}
      {error && <div className="text-red-400 mb-3">Error: {error}</div>}
      {loading ? <div className="text-gray-400 py-8 text-center">Loading…</div>
        : <DataTable columns={columns} rows={rows} csvName={csvName} />}
      <Pagination page={data?.page || 1} pageSize={data?.page_size || 50} total={data?.total || 0} onPage={setPage} />
    </div>
  )
}

// ── column configs ──────────────────────────────────────────────────────────
const LATENCY_COLUMNS = [
  { key: 'published_at', label: 'Time', render: (r) => fmtTime(r.published_at) },
  { key: 'ticker', label: 'Ticker', render: (r) => <span className="font-semibold">{r.ticker}</span> },
  { key: 'headline', label: 'Headline', sortable: false,
    render: (r) => <span className="text-gray-400 max-w-md inline-block truncate" title={r.headline}>{r.headline}</span> },
  { key: 'source', label: 'Source' },
  { key: 'latency', label: 'Latency', sortAccessor: (r) => r.derived?.total_latency_seconds,
    accessor: (r) => r.derived?.total_latency_seconds, render: (r) => fmtLat(r.derived?.total_latency_seconds) },
  { key: 'status', label: 'Status', render: (r) => <Badge status={r.status} /> },
  { key: 'blocked_reason', label: 'Blocked Reason', render: (r) => r.blocked_reason || '—' },
]

const ROCKET_COLUMNS = [
  { key: 'ticker', label: 'Ticker', render: (r) => <span className="font-semibold">{r.ticker}</span> },
  { key: 'binary_runner_probability', label: 'Runner %', render: (r) => fmtPct(r.binary_runner_probability) },
  { key: 'binary_major_plus_probability', label: 'Major %', render: (r) => fmtPct(r.binary_major_plus_probability) },
  { key: 'binary_monster_plus_probability', label: 'Monster %', render: (r) => fmtPct(r.binary_monster_plus_probability) },
  { key: 'rocket_rank_score', label: 'Rank Score', render: (r) => fmtNum(r.rocket_rank_score, 4) },
  { key: 'rule_score', label: 'Rule Score', render: (r) => fmtNum(r.rule_score, 1) },
  { key: 'prediction_confidence', label: 'Confidence', render: (r) => <Badge status={r.prediction_confidence} /> },
]

const OUTBOX_COLUMNS = [
  { key: 'alert_id', label: 'Alert', render: (r) => <span className="font-mono text-xs">{r.alert_id}</span> },
  { key: 'ticker', label: 'Ticker', render: (r) => <span className="font-semibold">{r.ticker}</span> },
  { key: 'status', label: 'Status', render: (r) => <Badge status={r.status} /> },
  { key: 'attempts', label: 'Attempts' },
  { key: 'last_error', label: 'Last Error', sortable: false, render: (r) => r.last_error || '—' },
  { key: 'created_at', label: 'Created', render: (r) => fmtTime(r.created_at) },
  { key: 'next_retry_at', label: 'Next Retry', render: (r) => fmtTime(r.next_retry_at) },
]

const SOURCE_HEALTH_COLUMNS = [
  { key: 'source', label: 'Source', render: (r) => <span className="font-semibold">{r.source}</span> },
  { key: 'total', label: 'Total' },
  { key: 'alerted', label: 'Alerted' },
  { key: 'delayed', label: 'Delayed' },
  { key: 'blocked', label: 'Blocked' },
  { key: 'fast_watch', label: 'Fast Watch' },
  { key: 'avg_latency_seconds', label: 'Avg Latency', render: (r) => fmtLat(r.avg_latency_seconds) },
]

// ── tabs ────────────────────────────────────────────────────────────────────
function NewsLatencyTab() {
  return (
    <DiagnosticsTab
      fetcher={getNewsLatency} columns={LATENCY_COLUMNS} csvName="news_latency.csv" downloadKind="news-latency"
      statusOptions={['alerted', 'delayed', 'blocked', 'duplicate_blocked', 'freshness_blocked', 'unresolved_ticker']}
      renderCards={(d) => (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <StatCard label="Total" value={d.summary?.total ?? 0} />
          <StatCard label="Alerted" value={d.summary?.alerted ?? 0} tone="green" />
          <StatCard label="Delayed >60s" value={d.summary?.delayed ?? 0} tone="yellow" />
          <StatCard label="Blocked" value={d.summary?.blocked ?? 0} tone="red" />
          <StatCard label="Fast Watch" value={d.summary?.fast_watch ?? 0} tone="blue" />
        </div>
      )}
      renderCharts={(d) => (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <BarPanel title="Alerts by Source" data={d.charts?.alerts_by_source} color="#22c55e" />
          <BarPanel title="Avg Latency by Source (s)" data={d.charts?.avg_latency_by_source} color="#eab308" valueFmt={(v) => `${v}s`} />
          <BarPanel title="Blocked Reason Distribution" data={d.charts?.blocked_reason_distribution} color="#ef4444" />
        </div>
      )}
    />
  )
}

function RocketShadowTab() {
  return (
    <DiagnosticsTab
      fetcher={getRocketShadow} columns={ROCKET_COLUMNS} csvName="rocket_shadow.csv" downloadKind="rocket-shadow"
      statusOptions={['HIGH', 'MEDIUM', 'LOW']} sourceLabel="Pipeline"
      renderTop={(d) => (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <TopList title="Top 10 Monster Candidates" rows={d.views?.highest_monster} metric="binary_monster_plus_probability" fmt={fmtPct} />
          <TopList title="Top 10 Major Candidates" rows={d.views?.highest_major} metric="binary_major_plus_probability" fmt={fmtPct} />
          <TopList title="Top 10 Rank Scores" rows={d.views?.top_rank} metric="rocket_rank_score" fmt={(v) => fmtNum(v, 4)} />
        </div>
      )}
    />
  )
}

function TelegramOutboxTab() {
  return (
    <DiagnosticsTab
      fetcher={getTelegramOutbox} columns={OUTBOX_COLUMNS} csvName="telegram_outbox.csv" downloadKind="telegram-outbox"
      statusOptions={['pending', 'sent', 'failed', 'dead_letter']} sourceLabel="Alert Type"
      renderCards={(d) => (
        <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
          <StatCard label="Pending" value={d.summary?.pending ?? 0} tone="blue" />
          <StatCard label="Sent" value={d.summary?.sent ?? 0} tone="green" />
          <StatCard label="Retrying" value={d.summary?.retrying ?? 0} tone="yellow" />
          <StatCard label="Failed" value={d.summary?.failed ?? 0} tone="yellow" />
          <StatCard label="Dead Letter" value={d.summary?.dead_letter ?? 0} tone="red" />
          <StatCard label="Success Rate" value={fmtPct(d.summary?.success_rate)} tone="green" />
        </div>
      )}
    />
  )
}

function SourceHealthTab() {
  return <DiagnosticsTab fetcher={getSourceHealth} columns={SOURCE_HEALTH_COLUMNS} csvName="source_health.csv" />
}
function BlockedAlertsTab() {
  return <DiagnosticsTab fetcher={getBlockedAlerts} columns={LATENCY_COLUMNS} csvName="blocked_alerts.csv"
    statusOptions={['duplicate_blocked', 'freshness_blocked', 'unresolved_ticker', 'cooldown_blocked']} />
}
function FastWatchTab() {
  return <DiagnosticsTab fetcher={getFastWatchAlerts} columns={LATENCY_COLUMNS} csvName="fast_watch.csv" />
}

function ReportsTab() {
  const { loading, error, data } = useDiagnostics(getReports, {})
  const items = data?.items || []
  return (
    <div>
      <Card title="Available Reports">
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-gray-400">
              <tr>
                {['Report', 'Type', 'Last Modified', 'Size', ''].map((h) => (
                  <th key={h} className="px-3 py-2 text-left font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {error && <tr><td colSpan={5} className="px-3 py-4 text-red-400">Error: {error}</td></tr>}
              {loading && <tr><td colSpan={5} className="px-3 py-4 text-gray-400">Loading…</td></tr>}
              {!loading && items.map((r) => (
                <tr key={r.name} className="hover:bg-gray-900/60">
                  <td className="px-3 py-2 font-mono text-xs text-gray-200">{r.name}</td>
                  <td className="px-3 py-2"><Badge status={r.type === 'markdown' ? 'MEDIUM' : 'pending'} /></td>
                  <td className="px-3 py-2 text-gray-400">{r.last_modified ? fmtTime(r.last_modified) : '—'}</td>
                  <td className="px-3 py-2 text-gray-400">{r.exists ? fmtBytes(r.size_bytes) : 'not generated'}</td>
                  <td className="px-3 py-2">
                    {r.exists ? (
                      <DownloadButton label="Download" icon={FileDown}
                        url={reportDownloadUrl(r.name)} fallbackName={r.name} />
                    ) : <span className="text-xs text-gray-600">unavailable</span>}
                  </td>
                </tr>
              ))}
              {!loading && items.length === 0 && !error && (
                <tr><td colSpan={5} className="px-3 py-6 text-center text-gray-600">No reports</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}

const TAB_COMPONENTS = {
  'news-latency': NewsLatencyTab,
  'rocket-shadow': RocketShadowTab,
  'telegram-outbox': TelegramOutboxTab,
  'reports': ReportsTab,
  'source-health': SourceHealthTab,
  'blocked-alerts': BlockedAlertsTab,
  'fast-watch': FastWatchTab,
}

export default function Diagnostics() {
  const [tab, setTab] = useState('news-latency')
  const Active = TAB_COMPONENTS[tab]
  return (
    <div className="max-w-7xl">
      <div className="mb-5">
        <h1 className="text-2xl font-bold text-white">Admin · Diagnostics</h1>
        <p className="text-sm text-gray-500">Read-only observability — why alerts are delayed, blocked, missed, retried, or ranked.</p>
      </div>
      <div className="flex flex-wrap gap-1 border-b border-gray-800 mb-5">
        {TABS.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              tab === t.id ? 'border-oracle-500 text-oracle-400' : 'border-transparent text-gray-400 hover:text-white'
            }`}>
            {t.label}
          </button>
        ))}
      </div>
      <Active />
    </div>
  )
}
