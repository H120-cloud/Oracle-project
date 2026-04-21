import { useState, useEffect, useCallback } from 'react'
import {
  Activity, TrendingUp, TrendingDown, Target, RefreshCw,
  AlertTriangle, CheckCircle, XCircle, Eye, Play, X,
} from 'lucide-react'
import {
  getActiveTrades, updateTradeTracking, closeTradeTracking,
} from '../api'

const STATUS_COLORS = {
  ON_TRACK: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  OVERPERFORMING: 'bg-emerald-500/30 text-emerald-300 border-emerald-500/50',
  UNDERPERFORMING: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  FAILED: 'bg-red-500/20 text-red-400 border-red-500/30',
}

const STATUS_ICONS = {
  ON_TRACK: Activity,
  OVERPERFORMING: TrendingUp,
  UNDERPERFORMING: AlertTriangle,
  FAILED: XCircle,
}

function TradeCard({ trade, onUpdate, onClose, updating }) {
  const StatusIcon = STATUS_ICONS[trade.status] || Activity
  const isLong = trade.progress_t2 >= 0

  return (
    <div className="card border border-gray-700">
      {/* Header */}
      <div className="flex justify-between items-start mb-3">
        <div>
          <h3 className="text-xl font-bold text-white">{trade.ticker}</h3>
          <div className={`text-xs px-2 py-0.5 rounded border inline-flex items-center gap-1 mt-1 ${STATUS_COLORS[trade.status] || STATUS_COLORS.ON_TRACK}`}>
            <StatusIcon className="w-3 h-3" />
            {trade.status?.replace('_', ' ')}
          </div>
        </div>
        <div className="text-right">
          <div className="text-2xl font-bold text-white">
            ${trade.current_price?.toFixed(2)}
          </div>
          <div className="text-xs text-gray-500">
            Entry: ${trade.entry_price?.toFixed(2)}
          </div>
        </div>
      </div>

      {/* Progress Bars */}
      <div className="space-y-2 mb-3">
        <div>
          <div className="flex justify-between text-xs mb-1">
            <span className="text-gray-500">To Target 1</span>
            <span className={trade.progress_t1 >= 100 ? 'text-emerald-400' : 'text-white'}>
              {trade.progress_t1?.toFixed(1)}%
            </span>
          </div>
          <div className="w-full h-2 bg-gray-700 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full ${trade.progress_t1 >= 100 ? 'bg-emerald-500' : 'bg-blue-500'}`}
              style={{ width: `${Math.min(100, trade.progress_t1 || 0)}%` }}
            />
          </div>
        </div>

        <div>
          <div className="flex justify-between text-xs mb-1">
            <span className="text-gray-500">To Target 2</span>
            <span className={trade.progress_t2 >= 100 ? 'text-emerald-400' : 'text-white'}>
              {trade.progress_t2?.toFixed(1)}%
            </span>
          </div>
          <div className="w-full h-2 bg-gray-700 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full ${trade.progress_t2 >= 100 ? 'bg-emerald-400' : 'bg-blue-400/50'}`}
              style={{ width: `${Math.min(100, Math.max(0, trade.progress_t2 || 0))}%` }}
            />
          </div>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 gap-3 mb-3">
        <div className="bg-gray-800/50 rounded p-2">
          <div className="text-[10px] text-gray-500">MFE (Best)</div>
          <div className="text-sm text-emerald-400 font-medium">
            +{trade.mfe?.toFixed(2)}%
          </div>
        </div>
        <div className="bg-gray-800/50 rounded p-2">
          <div className="text-[10px] text-gray-500">MAE (Worst)</div>
          <div className="text-sm text-red-400 font-medium">
            -{trade.mae?.toFixed(2)}%
          </div>
        </div>
      </div>

      {/* Hit Flags */}
      <div className="flex gap-2 mb-3">
        {trade.t1_hit && (
          <span className="text-[10px] px-2 py-0.5 bg-emerald-500/20 text-emerald-400 rounded">
            T1 Hit
          </span>
        )}
        {trade.t2_hit && (
          <span className="text-[10px] px-2 py-0.5 bg-emerald-500/30 text-emerald-300 rounded">
            T2 Hit
          </span>
        )}
      </div>

      {/* Actions */}
      <div className="flex gap-2">
        <button
          onClick={() => onUpdate(trade.ticker)}
          disabled={updating === trade.ticker}
          className="flex-1 bg-gray-800 hover:bg-gray-700 text-gray-300 text-xs py-2 rounded flex items-center justify-center gap-1 transition-colors disabled:opacity-50"
        >
          {updating === trade.ticker ? (
            <RefreshCw className="w-3 h-3 animate-spin" />
          ) : (
            <RefreshCw className="w-3 h-3" />
          )}
          Update Price
        </button>
        <button
          onClick={() => onClose(trade.ticker)}
          className="flex-1 bg-red-500/20 hover:bg-red-500/30 text-red-400 text-xs py-2 rounded flex items-center justify-center gap-1 transition-colors"
        >
          <X className="w-3 h-3" />
          Close Trade
        </button>
      </div>
    </div>
  )
}

export default function ActiveTradesPage() {
  const [trades, setTrades] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [updating, setUpdating] = useState('')
  const [closeModal, setCloseModal] = useState(null)
  const [exitPrice, setExitPrice] = useState('')

  const loadTrades = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await getActiveTrades()
      setTrades(data.trades || [])
    } catch (err) {
      setError(err.message || 'Failed to load trades')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadTrades()
    // Auto-refresh every 30 seconds
    const interval = setInterval(loadTrades, 30000)
    return () => clearInterval(interval)
  }, [loadTrades])

  const handleUpdate = async (ticker) => {
    setUpdating(ticker)
    try {
      // Fetch current price (would need price API in real implementation)
      // For now, simulate with a small random change
      const trade = trades.find(t => t.ticker === ticker)
      if (trade) {
        const newPrice = trade.current_price * (1 + (Math.random() - 0.5) * 0.02)
        await updateTradeTracking(ticker, newPrice)
        await loadTrades()
      }
    } catch (err) {
      setError(err.message || 'Update failed')
    } finally {
      setUpdating('')
    }
  }

  const handleClose = async () => {
    if (!closeModal || !exitPrice) return
    try {
      const price = parseFloat(exitPrice)
      if (isNaN(price) || price <= 0) {
        setError('Invalid exit price')
        return
      }
      await closeTradeTracking(closeModal, price)
      setCloseModal(null)
      setExitPrice('')
      await loadTrades()
    } catch (err) {
      setError(err.message || 'Failed to close trade')
    }
  }

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Activity className="w-7 h-7 text-oracle-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">Active Trades</h1>
            <p className="text-sm text-gray-500">Track predictions vs. actual performance</p>
          </div>
        </div>
        <button
          onClick={loadTrades}
          disabled={loading}
          className="text-xs text-gray-500 hover:text-oracle-400 flex items-center gap-1"
        >
          <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/50 rounded-lg p-3 mb-4 text-red-400 text-sm">
          {error}
        </div>
      )}

      {loading && trades.length === 0 && (
        <div className="text-center py-12">
          <RefreshCw className="w-8 h-8 text-oracle-400 animate-spin mx-auto mb-2" />
          <p className="text-gray-500">Loading active trades...</p>
        </div>
      )}

      {!loading && trades.length === 0 && (
        <div className="text-center py-12 bg-gray-900/50 rounded-lg border border-gray-800">
          <Eye className="w-12 h-12 text-gray-600 mx-auto mb-3" />
          <p className="text-gray-500">No active trades being tracked</p>
          <p className="text-sm text-gray-600 mt-1">
            Go to <strong>Intelligence</strong> page and click "Start Tracking" on an ENTER signal
          </p>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {trades.map(trade => (
          <TradeCard
            key={trade.ticker}
            trade={trade}
            onUpdate={handleUpdate}
            onClose={(ticker) => setCloseModal(ticker)}
            updating={updating}
          />
        ))}
      </div>

      {/* Close Trade Modal */}
      {closeModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-gray-900 border border-gray-700 rounded-lg p-6 w-full max-w-sm">
            <h3 className="text-lg font-bold text-white mb-2">Close Trade: {closeModal}</h3>
            <p className="text-sm text-gray-500 mb-4">
              Enter the exit price to grade the trade outcome
            </p>
            <input
              type="number"
              step="0.01"
              value={exitPrice}
              onChange={e => setExitPrice(e.target.value)}
              placeholder="Exit price (e.g. 245.50)"
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white mb-4"
              autoFocus
            />
            <div className="flex gap-2">
              <button
                onClick={() => { setCloseModal(null); setExitPrice('') }}
                className="flex-1 bg-gray-800 hover:bg-gray-700 text-gray-300 py-2 rounded"
              >
                Cancel
              </button>
              <button
                onClick={handleClose}
                className="flex-1 bg-red-500/20 hover:bg-red-500/30 text-red-400 py-2 rounded"
              >
                Close Trade
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
