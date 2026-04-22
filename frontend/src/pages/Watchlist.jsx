import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Eye, Plus, Trash2, Archive, RefreshCw, Bell, Clock,
  TrendingUp, TrendingDown, AlertTriangle, Star, Filter,
  ChevronDown, ChevronUp, X, Save, ArrowUpRight, ArrowDownRight,
  Activity, Shield, Target, Zap, Search, Volume2, VolumeX, BellRing,
} from 'lucide-react'
import { playAlertSound, unlockAudio } from '../sounds'
import {
  getWatchlist, addToWatchlist, removeFromWatchlist,
  archiveWatchlistItem, restoreWatchlistItem,
  updateWatchlistItem, getWatchlistDetail,
  refreshWatchlist, refreshWatchlistItem,
  getWatchlistAlerts, markAlertRead,
  getCustomAlerts, createCustomAlert, deleteCustomAlert,
  getTickerNews,
} from '../api'

const PRIORITY_COLORS = {
  high: 'text-red-400 bg-red-500/10',
  medium: 'text-yellow-400 bg-yellow-500/10',
  low: 'text-gray-400 bg-gray-500/10',
}

const ALERT_SEVERITY = {
  critical: 'border-red-500/50 bg-red-500/5',
  warning: 'border-yellow-500/50 bg-yellow-500/5',
  info: 'border-blue-500/50 bg-blue-500/5',
}

const TAG_OPTIONS = [
  'dip_candidate', 'breakout_watch', 'bearish_watch',
  'earnings_news', 'long_term', 'momentum', 'penny_stock',
]

function AlertBadge({ count }) {
  if (!count) return null
  return (
    <span className="absolute -top-1 -right-1 bg-red-500 text-white text-xs rounded-full w-4 h-4 flex items-center justify-center">
      {count > 9 ? '9+' : count}
    </span>
  )
}

// V8: HTF data status helpers
function getHTFDataStatus(timestamp) {
  if (!timestamp) return { status: 'MISSING', ageSeconds: null, label: 'No HTF Data', color: 'gray' }
  const ageMs = Date.now() - new Date(timestamp).getTime()
  const ageSeconds = Math.floor(ageMs / 1000)
  const ageMinutes = Math.floor(ageSeconds / 60)
  
  if (ageSeconds < 120) return { status: 'FRESH', ageSeconds, label: 'Just now', color: 'emerald' }
  if (ageMinutes < 5) return { status: 'AGING', ageSeconds, label: `${ageMinutes}m ago`, color: 'yellow' }
  if (ageMinutes < 15) return { status: 'STALE', ageSeconds, label: `${ageMinutes}m ago`, color: 'orange' }
  return { status: 'STALE', ageSeconds, label: `${Math.floor(ageMinutes / 60)}h ago`, color: 'red' }
}

function WatchlistRow({ item, onSelect, onRemove, onArchive, onRefresh }) {
  const changePct = item.latest_change_pct || 0
  const isUp = changePct >= 0

  // Calculate days until earnings
  const daysUntilEarnings = item.next_earnings_date
    ? Math.ceil((new Date(item.next_earnings_date) - new Date()) / (1000 * 60 * 60 * 24))
    : null
  const earningsWarning = daysUntilEarnings !== null && daysUntilEarnings >= 0 && daysUntilEarnings <= 2
  
  // V8: HTF data status
  const htfStatus = getHTFDataStatus(item.latest_htf_updated_at || item.metrics_updated_at)

  return (
    <tr
      className="border-b border-gray-800 hover:bg-gray-800/50 cursor-pointer transition-colors"
      onClick={() => onSelect(item)}
    >
      <td className="px-3 py-3">
        <div className="flex items-center gap-2">
          <span className={`text-xs px-1.5 py-0.5 rounded ${PRIORITY_COLORS[item.priority] || PRIORITY_COLORS.medium}`}>
            {item.priority?.[0]?.toUpperCase()}
          </span>
          <div>
            <div className="font-bold text-white flex items-center gap-1">
              {item.ticker}
              {earningsWarning && (
                <span className="text-[10px] px-1 py-0.5 bg-orange-500/20 text-orange-400 rounded" title={`Earnings in ${daysUntilEarnings} day${daysUntilEarnings !== 1 ? 's' : ''}`}>
                  ER {daysUntilEarnings}d
                </span>
              )}
            </div>
            <div className="text-xs text-gray-500">{item.company_name || item.source}</div>
          </div>
        </div>
      </td>
      <td className="px-3 py-3 text-right">
        <div className="text-white font-semibold">${item.latest_price?.toFixed(2) || '—'}</div>
        <div className={`text-xs flex items-center justify-end gap-0.5 ${isUp ? 'text-emerald-400' : 'text-red-400'}`}>
          {isUp ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />}
          {changePct.toFixed(2)}%
        </div>
      </td>
      <td className="px-3 py-3 text-right text-sm">
        <div className="text-gray-300">{item.latest_volume ? (item.latest_volume / 1e6).toFixed(1) + 'M' : '—'}</div>
        {item.latest_rvol && (
          <div className={`text-xs ${item.latest_rvol >= 2 ? 'text-oracle-400' : 'text-gray-500'}`}>
            {item.latest_rvol.toFixed(1)}x RVOL
          </div>
        )}
      </td>
      <td className="px-3 py-3 text-center">
        {item.latest_dip_prob != null && (
          <span className={`text-xs px-1.5 py-0.5 rounded ${item.latest_dip_prob >= 60 ? 'bg-emerald-500/20 text-emerald-400' : 'bg-gray-700 text-gray-400'}`}>
            D:{item.latest_dip_prob.toFixed(0)}%
          </span>
        )}
      </td>
      <td className="px-3 py-3 text-center">
        {item.latest_bounce_prob != null && (
          <span className={`text-xs px-1.5 py-0.5 rounded ${item.latest_bounce_prob >= 60 ? 'bg-emerald-500/20 text-emerald-400' : 'bg-gray-700 text-gray-400'}`}>
            B:{item.latest_bounce_prob.toFixed(0)}%
          </span>
        )}
      </td>
      <td className="px-3 py-3 text-center">
        {item.latest_bearish_prob != null && (
          <span className={`text-xs px-1.5 py-0.5 rounded ${item.latest_bearish_prob >= 50 ? 'bg-red-500/20 text-red-400' : 'bg-gray-700 text-gray-400'}`}>
            Bear:{item.latest_bearish_prob.toFixed(0)}%
          </span>
        )}
      </td>
      <td className="px-3 py-3 text-center text-xs text-gray-400">
        {item.latest_regime || '—'}
      </td>
      <td className="px-3 py-3 text-center text-xs text-gray-400">
        {item.latest_stage || '—'}
      </td>
      <td className="px-3 py-3">
        {/* V7: Momentum & Structure Badges */}
        <div className="flex flex-wrap gap-1 mb-1">
          {item.latest_momentum_state && item.latest_momentum_state !== 'neutral' && (
            <span className={`text-[9px] px-1 py-0.5 rounded ${
              item.latest_momentum_state === 'accelerating_up' ? 'bg-emerald-500/20 text-emerald-400' :
              item.latest_momentum_state === 'slowing_down' ? 'bg-blue-500/20 text-blue-400' :
              item.latest_momentum_state === 'accelerating_down' ? 'bg-red-500/20 text-red-400' :
              'bg-gray-700 text-gray-400'
            }`}>
              {item.latest_momentum_state.replace(/_/g, ' ')}
            </span>
          )}
          {item.latest_structure_status && (
            <span className={`text-[9px] px-1 py-0.5 rounded ${
              item.latest_structure_status === 'intact' ? 'bg-emerald-500/20 text-emerald-400' :
              item.latest_structure_status === 'broken' ? 'bg-red-500/20 text-red-400' :
              'bg-gray-700 text-gray-400'
            }`}>
              {item.latest_structure_status}
            </span>
          )}
          {item.latest_breakout_quality && item.latest_breakout_quality !== 'none' && (
            <span className={`text-[9px] px-1 py-0.5 rounded ${
              item.latest_breakout_quality === 'confirmed' ? 'bg-emerald-500/20 text-emerald-400' :
              item.latest_breakout_quality === 'weak' ? 'bg-yellow-500/20 text-yellow-400' :
              'bg-red-500/20 text-red-400'
            }`}>
              {item.latest_breakout_quality}
            </span>
          )}
          {/* V8: HTF Bias with Strength Score */}
          {item.latest_htf_bias ? (
            <span className={`text-[9px] px-1 py-0.5 rounded ${
              item.latest_htf_bias === 'BULLISH' ? 'bg-emerald-500/20 text-emerald-400' :
              item.latest_htf_bias === 'BEARISH' ? 'bg-red-500/20 text-red-400' :
              'bg-yellow-500/20 text-yellow-400'
            }`} title={`HTF Strength: ${item.latest_htf_strength_score?.toFixed(0) ?? '?'}/100`}>
              HTF: {item.latest_htf_bias} ({item.latest_htf_strength_score?.toFixed(0) ?? '?'})
            </span>
          ) : (
            <span className="text-[9px] px-1 py-0.5 rounded bg-gray-700 text-gray-500" title="No HTF data available">
              HTF: —
            </span>
          )}
          {/* V8: Alignment Status */}
          {item.latest_alignment_status ? (
            <span className={`text-[9px] px-1 py-0.5 rounded ${
              item.latest_alignment_status === 'ALIGNED' ? 'bg-emerald-500/20 text-emerald-400' :
              item.latest_alignment_status === 'COUNTER_TREND' ? 'bg-red-500/20 text-red-400' :
              'bg-gray-500/20 text-gray-400'
            }`}>
              {item.latest_alignment_status.replace(/_/g, ' ')}
            </span>
          ) : (
            <span className="text-[9px] px-1 py-0.5 rounded bg-gray-700 text-gray-500">
              Align: —
            </span>
          )}
          {/* V8: Trade Type (Counter-Trend Warning) */}
          {item.latest_trade_type === 'COUNTER_TREND_REVERSAL' && (
            <span className="text-[9px] px-1 py-0.5 rounded bg-orange-500/20 text-orange-400" title="High-risk counter-trend setup">
              ⚠️ CT
            </span>
          )}
          {/* V8: Data Freshness Indicator */}
          <span className={`text-[9px] px-1 py-0.5 rounded bg-${htfStatus.color}-500/10 text-${htfStatus.color}-400`} title={`HTF data: ${htfStatus.label}`}>
            ● {htfStatus.label}
          </span>
        </div>

        {/* V7: Warnings */}
        {item.latest_is_falling_knife && (
          <div className="text-[9px] text-red-400 flex items-center gap-0.5 mb-0.5">
            <span className="text-red-500">🔥</span> Falling knife
          </div>
        )}
        {item.latest_early_bearish_warning && (
          <div className="text-[9px] text-orange-400 flex items-center gap-0.5 mb-0.5">
            <span className="text-orange-500">⚠</span> Topping ({item.latest_early_bearish_confidence?.toFixed(0)}%)
          </div>
        )}
        {/* V8: HTF Blocked Warning */}
        {item.latest_htf_blocked && (
          <div className="text-[9px] text-red-400 flex items-center gap-0.5 mb-0.5" title={item.latest_htf_alignment_reason}>
            <TrendingDown className="w-3 h-3 text-red-500" />
            HTF Blocked: {item.latest_htf_alignment_reason?.slice(0, 30)}{item.latest_htf_alignment_reason?.length > 30 ? '...' : ''}
          </div>
        )}

        {item.latest_alert && (
          <div className="text-xs text-yellow-400 truncate max-w-[150px]" title={item.latest_alert}>
            {item.latest_alert}
          </div>
        )}
      </td>
      <td className="px-3 py-3 text-right">
        <div className="flex items-center gap-1 justify-end" onClick={e => e.stopPropagation()}>
          <button onClick={() => onRefresh(item.ticker)} className="p-1 hover:bg-gray-700 rounded" title="Refresh">
            <RefreshCw className="w-3.5 h-3.5 text-gray-400" />
          </button>
          <button onClick={() => onArchive(item.ticker)} className="p-1 hover:bg-gray-700 rounded" title="Archive">
            <Archive className="w-3.5 h-3.5 text-gray-400" />
          </button>
          <button onClick={() => onRemove(item.ticker)} className="p-1 hover:bg-red-900/50 rounded" title="Remove">
            <Trash2 className="w-3.5 h-3.5 text-red-400" />
          </button>
        </div>
      </td>
    </tr>
  )
}

function AddDialog({ open, onClose, onAdd }) {
  const [ticker, setTicker] = useState('')
  const [source, setSource] = useState('manual')
  const [watchReason, setWatchReason] = useState('')
  const [priority, setPriority] = useState('medium')
  const [tags, setTags] = useState([])
  const [notes, setNotes] = useState('')
  const [supportLevel, setSupportLevel] = useState('')
  const [resistanceLevel, setResistanceLevel] = useState('')

  if (!open) return null

  const handleAdd = () => {
    if (!ticker.trim()) return
    onAdd({
      ticker: ticker.trim().toUpperCase(),
      source,
      watch_reason: watchReason || undefined,
      priority,
      tags,
      notes: notes || undefined,
      support_level: supportLevel ? parseFloat(supportLevel) : undefined,
      resistance_level: resistanceLevel ? parseFloat(resistanceLevel) : undefined,
    })
    setTicker('')
    setWatchReason('')
    setNotes('')
    setSupportLevel('')
    setResistanceLevel('')
    setTags([])
    onClose()
  }

  const toggleTag = (tag) => {
    setTags(prev => prev.includes(tag) ? prev.filter(t => t !== tag) : [...prev, tag])
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-gray-900 border border-gray-700 rounded-lg p-6 w-full max-w-md" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-bold text-white">Add to Watchlist</h3>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>

        <div className="space-y-3">
          <input
            type="text" placeholder="Ticker (e.g. AAPL)" value={ticker}
            onChange={e => setTicker(e.target.value.toUpperCase())}
            onKeyDown={e => e.key === 'Enter' && handleAdd()}
            className="input-field w-full" autoFocus
          />

          <input
            type="text" placeholder="Watch reason" value={watchReason}
            onChange={e => setWatchReason(e.target.value)}
            className="input-field w-full"
          />

          <div className="flex gap-2">
            <select value={priority} onChange={e => setPriority(e.target.value)} className="input-field flex-1">
              <option value="high">High Priority</option>
              <option value="medium">Medium Priority</option>
              <option value="low">Low Priority</option>
            </select>
            <select value={source} onChange={e => setSource(e.target.value)} className="input-field flex-1">
              <option value="manual">Manual</option>
              <option value="scanner">Scanner</option>
              <option value="analysis">Analysis</option>
              <option value="bearish">Bearish Watch</option>
            </select>
          </div>

          <div className="flex gap-2">
            <input type="number" step="0.01" placeholder="Support $" value={supportLevel}
              onChange={e => setSupportLevel(e.target.value)} className="input-field flex-1" />
            <input type="number" step="0.01" placeholder="Resistance $" value={resistanceLevel}
              onChange={e => setResistanceLevel(e.target.value)} className="input-field flex-1" />
          </div>

          <div className="flex flex-wrap gap-1.5">
            {TAG_OPTIONS.map(tag => (
              <button key={tag} onClick={() => toggleTag(tag)}
                className={`text-xs px-2 py-1 rounded border transition-colors ${
                  tags.includes(tag) ? 'border-oracle-500 bg-oracle-500/20 text-oracle-300' : 'border-gray-700 text-gray-500 hover:border-gray-600'
                }`}
              >
                {tag.replace(/_/g, ' ')}
              </button>
            ))}
          </div>

          <textarea placeholder="Notes..." value={notes} onChange={e => setNotes(e.target.value)}
            className="input-field w-full h-20 resize-none" />

          <button onClick={handleAdd} className="btn-primary w-full flex items-center justify-center gap-2">
            <Plus className="w-4 h-4" /> Add to Watchlist
          </button>
        </div>
      </div>
    </div>
  )
}

function CustomAlertsSection({ item, onUpdate }) {
  const [alerts, setAlerts] = useState([])
  const [showAdd, setShowAdd] = useState(false)
  const [alertType, setAlertType] = useState('price_above')
  const [targetValue, setTargetValue] = useState('')
  const [message, setMessage] = useState('')

  useEffect(() => {
    loadAlerts()
  }, [item.ticker])

  const loadAlerts = async () => {
    try {
      const data = await getCustomAlerts(item.ticker)
      setAlerts(data.alerts || [])
    } catch (err) {
      console.error('Failed to load custom alerts:', err)
    }
  }

  const handleCreate = async () => {
    if (!targetValue) return
    try {
      await createCustomAlert(item.ticker, {
        alert_type: alertType,
        target_value: parseFloat(targetValue),
        message: message || undefined,
        reference_price: alertType.startsWith('percent') ? item.latest_price : undefined,
      })
      setShowAdd(false)
      setTargetValue('')
      setMessage('')
      loadAlerts()
      onUpdate()
    } catch (err) {
      alert('Failed to create alert: ' + err.message)
    }
  }

  const handleDelete = async (alertId) => {
    if (!confirm('Delete this alert?')) return
    try {
      await deleteCustomAlert(alertId)
      loadAlerts()
    } catch (err) {
      console.error('Failed to delete alert:', err)
    }
  }

  const getAlertLabel = (type) => {
    const labels = {
      'price_above': 'Price rises above',
      'price_below': 'Price drops below',
      'percent_change_up': 'Gains',
      'percent_change_down': 'Drops',
      'rvol_above': 'RVOL spikes above',
    }
    return labels[type] || type
  }

  return (
    <div className="card mb-4">
      <div className="card-header text-sm flex justify-between items-center">
        <div className="flex items-center gap-2">
          <Target className="w-3.5 h-3.5 text-oracle-400" /> Custom Alerts
        </div>
        <button onClick={() => setShowAdd(!showAdd)} className="text-xs text-oracle-400 hover:underline">
          {showAdd ? 'Cancel' : '+ Add'}
        </button>
      </div>

      {showAdd && (
        <div className="space-y-2 mb-3 p-2 bg-gray-800/50 rounded">
          <select value={alertType} onChange={e => setAlertType(e.target.value)} className="input-field w-full text-sm">
            <option value="price_above">Price rises above $</option>
            <option value="price_below">Price drops below $</option>
            <option value="percent_change_up">Price gains % from now</option>
            <option value="percent_change_down">Price drops % from now</option>
            <option value="rvol_above">RVOL spikes above</option>
          </select>
          <input
            type="number"
            step="0.01"
            placeholder={alertType.includes('percent') ? 'Percent (e.g. 5)' : alertType === 'rvol_above' ? 'RVOL (e.g. 3)' : 'Price (e.g. 175.50)'}
            value={targetValue}
            onChange={e => setTargetValue(e.target.value)}
            className="input-field w-full text-sm"
          />
          <input
            type="text"
            placeholder="Optional message (e.g. 'Take profit at $180')"
            value={message}
            onChange={e => setMessage(e.target.value)}
            className="input-field w-full text-sm"
          />
          <button onClick={handleCreate} className="btn-primary text-xs w-full">
            Create Alert
          </button>
        </div>
      )}

      {alerts.length === 0 ? (
        <p className="text-xs text-gray-500">No custom alerts set</p>
      ) : (
        <div className="space-y-1.5">
          {alerts.map(a => (
            <div key={a.id} className={`text-xs p-2 rounded border flex justify-between items-start ${a.is_active ? 'border-gray-700 bg-gray-800/30' : 'border-green-700/50 bg-green-500/5'}`}>
              <div>
                <div className="font-medium text-gray-300">
                  {getAlertLabel(a.alert_type)} {a.target_value}{a.alert_type.includes('percent') ? '%' : a.alert_type === 'rvol_above' ? 'x' : '$'}
                </div>
                {a.message && <div className="text-gray-500">{a.message}</div>}
                {!a.is_active && a.triggered_at && (
                  <div className="text-green-400 text-[10px]">
                    Triggered at ${a.triggered_price?.toFixed(2)} on {new Date(a.triggered_at).toLocaleString()}
                  </div>
                )}
              </div>
              {a.is_active && (
                <button onClick={() => handleDelete(a.id)} className="text-gray-500 hover:text-red-400">
                  <Trash2 className="w-3 h-3" />
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function NewsSection({ ticker }) {
  const [news, setNews] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadNews()
  }, [ticker])

  const loadNews = async () => {
    setLoading(true)
    try {
      const data = await getTickerNews(ticker, 8)
      setNews(data.news || [])
    } catch (err) {
      console.error('Failed to load news:', err)
    } finally {
      setLoading(false)
    }
  }

  const getSentimentColor = (sentiment) => {
    switch (sentiment) {
      case 'positive': return 'text-emerald-400'
      case 'negative': return 'text-red-400'
      default: return 'text-gray-400'
    }
  }

  const highlightKeywords = (headline) => {
    const keywords = ['earnings', 'revenue', 'profit', 'loss', 'beat', 'miss', 'upgrade', 'downgrade',
                      'buy', 'sell', 'target', 'analyst', 'forecast', 'guidance', 'growth', 'decline']
    let result = headline
    keywords.forEach(kw => {
      const regex = new RegExp(`\\b${kw}\\b`, 'gi')
      result = result.replace(regex, match => `<span class="text-oracle-400">${match}</span>`)
    })
    return result
  }

  return (
    <div className="card mb-4">
      <div className="card-header text-sm flex items-center gap-2">
        <Zap className="w-3.5 h-3.5 text-yellow-400" /> Latest News
      </div>

      {loading ? (
        <p className="text-xs text-gray-500">Loading news...</p>
      ) : news.length === 0 ? (
        <p className="text-xs text-gray-500">No recent news</p>
      ) : (
        <div className="space-y-2 max-h-48 overflow-y-auto">
          {news.map((n, i) => (
            <a
              key={i}
              href={n.url}
              target="_blank"
              rel="noopener noreferrer"
              className="block text-xs p-2 rounded bg-gray-800/30 hover:bg-gray-800/60 transition-colors"
            >
              <div className="flex items-start gap-2">
                <span className={`text-[10px] mt-0.5 ${getSentimentColor(n.sentiment)}`}>
                  {n.sentiment === 'positive' ? '▲' : n.sentiment === 'negative' ? '▼' : '•'}
                </span>
                <div className="flex-1">
                  <div
                    className="text-gray-300 leading-tight"
                    dangerouslySetInnerHTML={{ __html: highlightKeywords(n.headline) }}
                  />
                  <div className="text-[10px] text-gray-500 mt-0.5">{n.source}</div>
                </div>
              </div>
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

function DetailPanel({ item, onClose, onUpdate }) {
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(true)
  const [editNotes, setEditNotes] = useState('')
  const [editingNotes, setEditingNotes] = useState(false)

  const loadDetail = () => {
    if (!item) return
    setLoading(true)
    getWatchlistDetail(item.ticker)
      .then(d => { setDetail(d); setEditNotes(d.item.notes || '') })
      .catch(() => setDetail(null))
      .finally(() => setLoading(false))
  }

  useEffect(() => { loadDetail() }, [item?.ticker])

  const handleRefresh = async () => {
    setLoading(true)
    try {
      await refreshWatchlistItem(item.ticker)
      await loadDetail()
      onUpdate()
    } catch (err) {
      console.error('Refresh failed:', err)
    } finally {
      setLoading(false)
    }
  }

  if (!item) return null

  const saveNotes = async () => {
    await updateWatchlistItem(item.ticker, { notes: editNotes })
    setEditingNotes(false)
    onUpdate()
  }

  return (
    <div className="fixed inset-y-0 right-0 w-96 bg-gray-900 border-l border-gray-700 shadow-2xl z-40 overflow-y-auto">
      <div className="p-4">
        <div className="flex justify-between items-center mb-4">
          <div>
            <h3 className="text-xl font-bold text-white">{item.ticker}</h3>
            <p className="text-xs text-gray-500">{item.company_name || 'No market data'}</p>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={handleRefresh} disabled={loading} title="Refresh metrics" className="p-1.5 hover:bg-gray-800 rounded">
              <RefreshCw className={`w-4 h-4 text-oracle-400 ${loading ? 'animate-spin' : ''}`} />
            </button>
            <button onClick={onClose} className="p-1.5 hover:bg-gray-800 rounded">
              <X className="w-5 h-5 text-gray-400" />
            </button>
          </div>
        </div>

        {/* Metrics Summary */}
        <div className="grid grid-cols-2 gap-2 mb-4">
          <div className="bg-gray-800 rounded p-2">
            <div className="stat-label">Price</div>
            <div className="text-white font-bold">${item.latest_price?.toFixed(2) || '—'}</div>
          </div>
          <div className="bg-gray-800 rounded p-2">
            <div className="stat-label">Change</div>
            <div className={`font-bold ${(item.latest_change_pct || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              {(item.latest_change_pct || 0).toFixed(2)}%
            </div>
          </div>
          <div className="bg-gray-800 rounded p-2">
            <div className="stat-label">Dip Prob</div>
            <div className="text-white font-bold">{item.latest_dip_prob?.toFixed(0) || '—'}%</div>
          </div>
          <div className="bg-gray-800 rounded p-2">
            <div className="stat-label">Bounce Prob</div>
            <div className="text-white font-bold">{item.latest_bounce_prob?.toFixed(0) || '—'}%</div>
          </div>
          <div className="bg-gray-800 rounded p-2">
            <div className="stat-label">Bearish</div>
            <div className="text-white font-bold">{item.latest_bearish_prob?.toFixed(0) || '—'}%</div>
          </div>
          <div className="bg-gray-800 rounded p-2">
            <div className="stat-label">RVOL</div>
            <div className="text-white font-bold">{item.latest_rvol?.toFixed(1) || '—'}x</div>
          </div>
        </div>

        {/* Key Levels */}
        {(item.support_level || item.resistance_level || item.invalidation_level) && (
          <div className="card mb-4">
            <div className="card-header text-sm">Key Levels</div>
            <div className="space-y-1 text-sm">
              {item.support_level && <div className="flex justify-between"><span className="text-gray-400">Support</span><span className="text-emerald-400">${item.support_level.toFixed(2)}</span></div>}
              {item.resistance_level && <div className="flex justify-between"><span className="text-gray-400">Resistance</span><span className="text-red-400">${item.resistance_level.toFixed(2)}</span></div>}
              {item.invalidation_level && <div className="flex justify-between"><span className="text-gray-400">Invalidation</span><span className="text-orange-400">${item.invalidation_level.toFixed(2)}</span></div>}
            </div>
          </div>
        )}

        {/* V8: Higher Timeframe Analysis */}
        <div className="card mb-4">
          <div className="card-header text-sm flex justify-between items-center">
            <span>Higher Timeframe Analysis</span>
            {(() => {
              const htfStatus = getHTFDataStatus(item.latest_htf_updated_at || item.metrics_updated_at)
              return (
                <span className={`text-[10px] px-1.5 py-0.5 rounded bg-${htfStatus.color}-500/20 text-${htfStatus.color}-400`}>
                  {htfStatus.label}
                </span>
              )
            })()}
          </div>
          <div className="space-y-2 text-sm">
            {/* HTF Bias & Strength */}
            <div className="flex justify-between items-center">
              <span className="text-gray-400">HTF Bias</span>
              {item.latest_htf_bias ? (
                <span className={`font-medium ${
                  item.latest_htf_bias === 'BULLISH' ? 'text-emerald-400' :
                  item.latest_htf_bias === 'BEARISH' ? 'text-red-400' :
                  'text-yellow-400'
                }`}>
                  {item.latest_htf_bias} ({item.latest_htf_strength_score?.toFixed(0) ?? '?'}/100)
                </span>
              ) : (
                <span className="text-gray-500">—</span>
              )}
            </div>
            
            {/* Alignment Status */}
            <div className="flex justify-between items-center">
              <span className="text-gray-400">Alignment</span>
              {item.latest_alignment_status ? (
                <span className={`font-medium ${
                  item.latest_alignment_status === 'ALIGNED' ? 'text-emerald-400' :
                  item.latest_alignment_status === 'COUNTER_TREND' ? 'text-red-400' :
                  'text-gray-400'
                }`}>
                  {item.latest_alignment_status.replace(/_/g, ' ')}
                </span>
              ) : (
                <span className="text-gray-500">—</span>
              )}
            </div>
            
            {/* Trade Type */}
            {item.latest_trade_type && (
              <div className="flex justify-between items-center">
                <span className="text-gray-400">Trade Type</span>
                <span className={`font-medium ${
                  item.latest_trade_type === 'COUNTER_TREND_REVERSAL' ? 'text-orange-400' : 'text-blue-400'
                }`}>
                  {item.latest_trade_type.replace(/_/g, ' ')}
                </span>
              </div>
            )}
            
            {/* HTF RSI & ADX */}
            {(item.latest_htf_rsi !== null || item.latest_htf_adx !== null) && (
              <div className="grid grid-cols-2 gap-2 pt-1 border-t border-gray-700">
                {item.latest_htf_rsi !== null && (
                  <div className="flex justify-between">
                    <span className="text-gray-500 text-xs">HTF RSI</span>
                    <span className="text-white text-xs">{item.latest_htf_rsi.toFixed(1)}</span>
                  </div>
                )}
                {item.latest_htf_adx !== null && (
                  <div className="flex justify-between">
                    <span className="text-gray-500 text-xs">HTF ADX</span>
                    <span className={`text-xs ${item.latest_htf_adx > 25 ? 'text-emerald-400' : 'text-gray-400'}`}>
                      {item.latest_htf_adx.toFixed(1)} {item.latest_htf_adx > 25 ? '(trending)' : '(weak)'}
                    </span>
                  </div>
                )}
              </div>
            )}
            
            {/* Blocked Warning */}
            {item.latest_htf_blocked && (
              <div className="mt-2 bg-red-500/10 border border-red-500/30 rounded px-2 py-1.5">
                <div className="text-[10px] text-red-400 flex items-center gap-1">
                  <TrendingDown className="w-3 h-3" />
                  <span className="font-medium">HTF FILTER BLOCKED</span>
                </div>
                {item.latest_htf_alignment_reason && (
                  <div className="text-[10px] text-red-400/80 mt-0.5">
                    {item.latest_htf_alignment_reason}
                  </div>
                )}
              </div>
            )}
            
            {/* Missing Data Warning */}
            {!item.latest_htf_bias && (
              <div className="mt-2 bg-gray-500/10 border border-gray-500/30 rounded px-2 py-1.5">
                <div className="text-[10px] text-gray-400 flex items-center gap-1">
                  <AlertTriangle className="w-3 h-3" />
                  HTF data not available. Refresh to calculate.
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Tags */}
        {item.tags?.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-4">
            {item.tags.map(tag => (
              <span key={tag} className="text-xs px-2 py-0.5 rounded bg-oracle-600/20 text-oracle-300">
                {tag.replace(/_/g, ' ')}
              </span>
            ))}
          </div>
        )}

        {/* Notes */}
        <div className="card mb-4">
          <div className="card-header text-sm flex justify-between items-center">
            Notes
            {!editingNotes && (
              <button onClick={() => setEditingNotes(true)} className="text-xs text-oracle-400 hover:underline">Edit</button>
            )}
          </div>
          {editingNotes ? (
            <div>
              <textarea value={editNotes} onChange={e => setEditNotes(e.target.value)}
                className="input-field w-full h-20 resize-none mb-2" />
              <div className="flex gap-2">
                <button onClick={saveNotes} className="btn-primary text-xs flex items-center gap-1">
                  <Save className="w-3 h-3" /> Save
                </button>
                <button onClick={() => setEditingNotes(false)} className="text-xs text-gray-400">Cancel</button>
              </div>
            </div>
          ) : (
            <p className="text-sm text-gray-400">{item.notes || 'No notes yet'}</p>
          )}
        </div>

        {/* Alerts */}
        {detail?.alerts?.length > 0 && (
          <div className="card mb-4">
            <div className="card-header text-sm flex items-center gap-2">
              <Bell className="w-3.5 h-3.5 text-yellow-400" /> Recent Alerts
            </div>
            <div className="space-y-2 max-h-48 overflow-y-auto">
              {detail.alerts.map(a => (
                <div key={a.id} className={`text-xs p-2 rounded border ${ALERT_SEVERITY[a.severity] || ALERT_SEVERITY.info}`}>
                  <div className="font-semibold">{a.alert_type.replace(/_/g, ' ')}</div>
                  <div className="text-gray-400">{a.message}</div>
                  <div className="text-gray-600 mt-0.5">{new Date(a.created_at).toLocaleString()}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Custom Price Alerts */}
        <CustomAlertsSection item={item} onUpdate={onUpdate} />

        {/* News Feed */}
        <NewsSection ticker={item.ticker} />

        {/* Timeline */}
        {detail?.timeline?.length > 0 && (
          <div className="card">
            <div className="card-header text-sm flex items-center gap-2">
              <Clock className="w-3.5 h-3.5 text-blue-400" /> Timeline
            </div>
            <div className="space-y-2 max-h-48 overflow-y-auto">
              {detail.timeline.map(t => (
                <div key={t.id} className="text-xs border-l-2 border-gray-700 pl-2">
                  <div className="text-gray-300">{t.description}</div>
                  <div className="text-gray-600">{new Date(t.created_at).toLocaleString()}</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

const ALERT_ICONS = {
  dip_detected: { icon: TrendingDown, color: 'text-red-400', bg: 'bg-red-500/10 border-red-500/30' },
  bounce_confirmed: { icon: TrendingUp, color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/30' },
  bearish_warning: { icon: AlertTriangle, color: 'text-orange-400', bg: 'bg-orange-500/10 border-orange-500/30' },
  volume_surge: { icon: Activity, color: 'text-blue-400', bg: 'bg-blue-500/10 border-blue-500/30' },
  big_move: { icon: Zap, color: 'text-yellow-400', bg: 'bg-yellow-500/10 border-yellow-500/30' },
}

function AlertToast({ alert, onDismiss }) {
  const config = ALERT_ICONS[alert.alert_type] || ALERT_ICONS.big_move
  const Icon = config.icon

  useEffect(() => {
    const timer = setTimeout(onDismiss, 8000)
    return () => clearTimeout(timer)
  }, [onDismiss])

  return (
    <div className={`flex items-start gap-3 p-3 rounded-lg border ${config.bg} animate-slide-in shadow-lg max-w-sm`}>
      <Icon className={`w-5 h-5 mt-0.5 ${config.color} flex-shrink-0`} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-bold text-white text-sm">{alert.ticker}</span>
          <span className="text-[10px] text-gray-400">${alert.price?.toFixed(2)}</span>
        </div>
        <p className="text-xs text-gray-300 mt-0.5">{alert.message}</p>
      </div>
      <button onClick={onDismiss} className="text-gray-500 hover:text-gray-300 flex-shrink-0">
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  )
}

function NotificationControls({ soundEnabled, setSoundEnabled, notifEnabled, setNotifEnabled }) {
  const handleToggleSound = () => {
    const next = !soundEnabled
    setSoundEnabled(next)
    localStorage.setItem('oracle_sound_enabled', JSON.stringify(next))
    if (next) {
      unlockAudio()
      playAlertSound('bullish') // Play a test sound
    }
  }

  const handleToggleNotif = async () => {
    if (!notifEnabled) {
      // Request permission
      if (!('Notification' in window)) {
        alert('Browser notifications are not supported')
        return
      }
      const perm = await Notification.requestPermission()
      if (perm === 'granted') {
        setNotifEnabled(true)
        localStorage.setItem('oracle_notif_enabled', 'true')
        new Notification('Oracle Alerts Enabled', {
          body: 'You will receive desktop notifications for watchlist alerts.',
          icon: '/favicon.ico',
        })
      }
    } else {
      setNotifEnabled(false)
      localStorage.setItem('oracle_notif_enabled', 'false')
    }
  }

  return (
    <div className="flex items-center gap-1.5">
      <button
        onClick={handleToggleSound}
        className={`p-1.5 rounded transition-colors ${soundEnabled ? 'bg-oracle-600/20 text-oracle-400' : 'bg-gray-800 text-gray-500'}`}
        title={soundEnabled ? 'Sound alerts ON — click to mute' : 'Sound alerts OFF — click to enable'}
      >
        {soundEnabled ? <Volume2 className="w-4 h-4" /> : <VolumeX className="w-4 h-4" />}
      </button>
      <button
        onClick={handleToggleNotif}
        className={`p-1.5 rounded transition-colors ${notifEnabled ? 'bg-oracle-600/20 text-oracle-400' : 'bg-gray-800 text-gray-500'}`}
        title={notifEnabled ? 'Desktop notifications ON — click to disable' : 'Desktop notifications OFF — click to enable'}
      >
        {notifEnabled ? <BellRing className="w-4 h-4" /> : <Bell className="w-4 h-4" />}
      </button>
    </div>
  )
}

export default function WatchlistPage() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  
  // V8: HTF filter state
  const [htfFilter, setHtfFilter] = useState('ALL') // ALL, BULLISH, BEARISH, NEUTRAL, ALIGNED, BLOCKED
  const [showAdd, setShowAdd] = useState(false)
  const [selectedItem, setSelectedItem] = useState(null)
  const [filter, setFilter] = useState('all') // all, high, dip, bearish, active
  const [sortBy, setSortBy] = useState('priority_score')
  const [alerts, setAlerts] = useState([])
  const [showArchived, setShowArchived] = useState(false)

  // Notification state
  const [soundEnabled, setSoundEnabled] = useState(() => {
    try { return JSON.parse(localStorage.getItem('oracle_sound_enabled')) ?? false } catch { return false }
  })
  const [notifEnabled, setNotifEnabled] = useState(() => {
    return localStorage.getItem('oracle_notif_enabled') === 'true' &&
      'Notification' in window && Notification.permission === 'granted'
  })
  const [toastAlerts, setToastAlerts] = useState([])
  const toastIdRef = useRef(0)

  const fetchData = useCallback(async () => {
    try {
      const [wl, al] = await Promise.allSettled([
        getWatchlist(showArchived),
        getWatchlistAlerts(),
      ])
      if (wl.status === 'fulfilled') setItems(wl.value.items || [])
      if (al.status === 'fulfilled') setAlerts(al.value.alerts || [])
    } catch (err) {
      console.error('Failed to fetch watchlist:', err)
    } finally {
      setLoading(false)
    }
  }, [showArchived])

  useEffect(() => { fetchData() }, [fetchData])

  // V8: Auto-refresh watchlist data every 60 seconds for HTF updates
  useEffect(() => {
    const interval = setInterval(() => {
      // Only auto-refresh if not manually refreshing
      if (!refreshing) {
        fetchData()
      }
    }, 60000) // 60 seconds
    return () => clearInterval(interval)
  }, [fetchData, refreshing])

  // WebSocket for real-time price updates
  useEffect(() => {
    const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${wsProto}//${window.location.host}/ws/watchlist`
    let ws = null
    let reconnectTimer = null
    let retryCount = 0
    const MAX_RETRIES = 5

    const connect = () => {
      if (retryCount >= MAX_RETRIES) return
      try {
        ws = new WebSocket(wsUrl)
      } catch {
        return
      }

      ws.onopen = () => {
        console.log('Watchlist WS connected')
        retryCount = 0
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)

          // Price updates
          if (data.type === 'price_update' && data.updates) {
            setItems(prev => prev.map(item => {
              const update = data.updates.find(u => u.ticker === item.ticker)
              if (update) {
                return {
                  ...item,
                  latest_price: update.price,
                  latest_change_pct: update.change_pct ?? item.latest_change_pct,
                }
              }
              return item
            }))
          }

          // Alert events — play sounds + show desktop notifications + toast
          if (data.type === 'alert_event' && data.alerts) {
            data.alerts.forEach(a => {
              // Play distinct sound per alert type
              if (soundEnabled) {
                playAlertSound(a.sound || 'default')
              }

              // Browser desktop notification
              if (notifEnabled && 'Notification' in window && Notification.permission === 'granted') {
                const titles = {
                  dip_detected: '📉 Dip Forming',
                  bounce_confirmed: '🚀 Bullish Bounce',
                  bearish_warning: '⚠️ Bearish Shift',
                  volume_surge: '📊 Volume Surge',
                  big_move: '⚡ Big Move',
                }
                new Notification(titles[a.alert_type] || 'Oracle Alert', {
                  body: a.message,
                  icon: '/favicon.ico',
                  tag: `oracle-${a.ticker}-${a.alert_type}`,
                  requireInteraction: a.severity === 'critical',
                })
              }

              // In-app toast
              const toastId = ++toastIdRef.current
              setToastAlerts(prev => [...prev, { ...a, _id: toastId }])
            })

            // Refresh alert list
            fetchData()
          }
        } catch (err) {
          console.error('WS message error:', err)
        }
      }

      ws.onerror = () => {}

      ws.onclose = () => {
        retryCount++
        if (retryCount < MAX_RETRIES) {
          reconnectTimer = setTimeout(connect, 3000 * retryCount)
        }
      }
    }

    connect()

    return () => {
      clearTimeout(reconnectTimer)
      retryCount = MAX_RETRIES
      if (ws) ws.close()
    }
  }, [])

  const handleAdd = async (data) => {
    try {
      await addToWatchlist(data)
      fetchData()
    } catch (err) {
      alert('Failed to add: ' + err.message)
    }
  }

  const handleRemove = async (ticker) => {
    if (!confirm(`Remove ${ticker} from watchlist?`)) return
    try {
      await removeFromWatchlist(ticker)
      setSelectedItem(null)
      fetchData()
    } catch (err) {
      alert('Failed to remove: ' + err.message)
    }
  }

  const handleArchive = async (ticker) => {
    try {
      await archiveWatchlistItem(ticker)
      fetchData()
    } catch (err) {
      alert('Failed to archive: ' + err.message)
    }
  }

  const handleRefreshOne = async (ticker) => {
    try {
      await refreshWatchlistItem(ticker)
      fetchData()
    } catch (err) {
      console.error('Refresh failed:', err)
    }
  }

  const handleRefreshAll = async () => {
    setRefreshing(true)
    try {
      await refreshWatchlist()
      await fetchData()
    } catch (err) {
      console.error('Refresh all failed:', err)
    } finally {
      setRefreshing(false)
    }
  }

  // Filter
  const filtered = items.filter(item => {
    // Standard filters
    if (filter === 'high') return item.priority === 'high'
    if (filter === 'dip') return item.latest_dip_prob >= 50
    if (filter === 'bearish') return item.latest_bearish_prob >= 40
    if (filter === 'active') return item.latest_rvol >= 1.5
    
    // V8: HTF filters
    if (htfFilter === 'BULLISH') return item.latest_htf_bias === 'BULLISH'
    if (htfFilter === 'BEARISH') return item.latest_htf_bias === 'BEARISH'
    if (htfFilter === 'NEUTRAL') return item.latest_htf_bias === 'NEUTRAL'
    if (htfFilter === 'ALIGNED') return item.latest_alignment_status === 'ALIGNED'
    if (htfFilter === 'BLOCKED') return item.latest_htf_blocked === true
    
    return true
  })

  // Sort
  const sorted = [...filtered].sort((a, b) => {
    if (sortBy === 'priority_score') return (b.priority_score || 0) - (a.priority_score || 0)
    if (sortBy === 'change') return Math.abs(b.latest_change_pct || 0) - Math.abs(a.latest_change_pct || 0)
    if (sortBy === 'alerts') return (b.alert_count || 0) - (a.alert_count || 0)
    if (sortBy === 'score') return (b.latest_final_score || 0) - (a.latest_final_score || 0)
    return 0
  })

  const panelOpen = !!selectedItem

  return (
    <div className={`relative transition-all duration-300 ${panelOpen ? 'mr-96' : ''}`}>
      {/* Live Toast Alerts */}
      {toastAlerts.length > 0 && (
        <div className={`fixed top-4 z-50 space-y-2 transition-all duration-300 ${panelOpen ? 'right-100' : 'right-4'}`}>
          {toastAlerts.map(ta => (
            <AlertToast
              key={ta._id}
              alert={ta}
              onDismiss={() => setToastAlerts(prev => prev.filter(t => t._id !== ta._id))}
            />
          ))}
        </div>
      )}

      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <h2 className="text-2xl font-bold text-white">Watchlist</h2>
          <span className="text-sm text-gray-500">{items.length} stocks</span>
          {alerts.length > 0 && (
            <span className="text-xs px-2 py-0.5 bg-red-500/20 text-red-400 rounded-full">
              {alerts.length} unread alerts
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <NotificationControls
            soundEnabled={soundEnabled}
            setSoundEnabled={setSoundEnabled}
            notifEnabled={notifEnabled}
            setNotifEnabled={setNotifEnabled}
          />
          <button onClick={handleRefreshAll} disabled={refreshing}
            className="btn-secondary flex items-center gap-1.5 text-sm">
            <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`} />
            {refreshing ? 'Refreshing...' : 'Refresh All'}
          </button>
          <button onClick={() => setShowAdd(true)} className="btn-primary flex items-center gap-1.5 text-sm">
            <Plus className="w-3.5 h-3.5" /> Add Stock
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-2 mb-4 flex-wrap">
        <div className="flex items-center gap-1">
          <Filter className="w-3.5 h-3.5 text-gray-500" />
          {['all', 'high', 'dip', 'bearish', 'active'].map(f => (
            <button key={f} onClick={() => setFilter(f)}
              className={`text-xs px-2.5 py-1 rounded transition-colors ${
                filter === f ? 'bg-oracle-600/30 text-oracle-300 border border-oracle-600' : 'bg-gray-800 text-gray-400 border border-gray-700 hover:border-gray-600'
              }`}>
              {f === 'all' ? 'All' : f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-1">
          <span className="text-xs text-gray-500">Sort:</span>
          <select value={sortBy} onChange={e => setSortBy(e.target.value)} className="input-field text-xs py-1">
            <option value="priority_score">Priority</option>
            <option value="change">% Move</option>
            <option value="alerts">Alerts</option>
            <option value="score">Score</option>
          </select>
          <label className="flex items-center gap-1 text-xs text-gray-500 ml-2">
            <input type="checkbox" checked={showArchived} onChange={e => setShowArchived(e.target.checked)} className="rounded" />
            Archived
          </label>
        </div>
      </div>

      {/* Table */}
      {loading ? (
        <div className="text-center text-gray-400 py-12">Loading watchlist...</div>
      ) : sorted.length === 0 ? (
        <div className="text-center py-12">
          <Eye className="w-12 h-12 text-gray-600 mx-auto mb-3" />
          <p className="text-gray-400">No stocks on watchlist</p>
          <p className="text-sm text-gray-600 mt-1">Add stocks from the scanner or manually</p>
          <button onClick={() => setShowAdd(true)} className="btn-primary mt-4 text-sm">
            <Plus className="w-4 h-4 inline mr-1" /> Add First Stock
          </button>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="text-xs text-gray-500 border-b border-gray-800">
                <th className="text-left px-3 py-2">Stock</th>
                <th className="text-right px-3 py-2">Price</th>
                <th className="text-right px-3 py-2">Volume</th>
                <th className="text-center px-3 py-2">Dip</th>
                <th className="text-center px-3 py-2">Bounce</th>
                <th className="text-center px-3 py-2">Bearish</th>
                <th className="text-center px-3 py-2">Regime</th>
                <th className="text-center px-3 py-2">Stage</th>
                <th className="text-left px-3 py-2">Alert</th>
                <th className="text-right px-3 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map(item => (
                <WatchlistRow
                  key={item.ticker}
                  item={item}
                  onSelect={setSelectedItem}
                  onRemove={handleRemove}
                  onArchive={handleArchive}
                  onRefresh={handleRefreshOne}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Dialogs */}
      <AddDialog open={showAdd} onClose={() => setShowAdd(false)} onAdd={handleAdd} />
      <DetailPanel item={selectedItem} onClose={() => setSelectedItem(null)} onUpdate={fetchData} />
    </div>
  )
}
