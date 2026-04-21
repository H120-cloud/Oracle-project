import { useState } from 'react'
import { Search, BarChart3, Activity, Layers, TrendingUp, Zap, Eye, Clock, DollarSign } from 'lucide-react'
import { getCompleteAnalysis, getOrderFlow, addToWatchlist, getLiveQuote } from '../api'

function Section({ title, icon: Icon, data, color = 'text-oracle-400' }) {
  if (!data) return null
  return (
    <div className="card">
      <div className="card-header flex items-center gap-2">
        <Icon className={`w-4 h-4 ${color}`} />
        {title}
      </div>
      <pre className="text-xs text-gray-300 whitespace-pre-wrap max-h-64 overflow-auto">
        {JSON.stringify(data, null, 2)}
      </pre>
    </div>
  )
}

export default function Analysis() {
  const [ticker, setTicker] = useState('')
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState({})

  const analyze = async () => {
    if (!ticker.trim()) return
    setLoading(true)
    setResults({})
    const t = ticker.trim().toUpperCase()
    try {
      // Single combined call + order flow in parallel
      const [complete, flow] = await Promise.allSettled([
        getCompleteAnalysis(t),
        getOrderFlow(t),
      ])
      const data = complete.status === 'fulfilled' ? complete.value : {}
      setResults({
        quote: data.quote || null,
        volumeProfile: data.volume_profile || null,
        regime: data.regime || null,
        stage: data.stage || null,
        dipFeatures: data.dip_features || null,
        bounceFeatures: data.bounce_features || null,
        orderFlow: flow.status === 'fulfilled' ? flow.value : { error: flow.reason?.message },
      })
    } catch (err) {
      console.error('Analysis failed:', err)
      alert('Analysis failed: ' + err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <h2 className="text-2xl font-bold text-white mb-6">Stock Analysis</h2>

      <div className="flex gap-3 mb-6">
        <input
          type="text"
          value={ticker}
          onChange={e => setTicker(e.target.value.toUpperCase())}
          onKeyDown={e => e.key === 'Enter' && analyze()}
          placeholder="Enter ticker (e.g. AAPL)"
          className="input-field flex-1 max-w-xs"
        />
        <button onClick={analyze} disabled={loading} className="btn-primary flex items-center gap-2">
          <Search className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          {loading ? 'Analyzing...' : 'Analyze'}
        </button>
        {ticker.trim() && (
          <button
            onClick={async () => {
              try {
                await addToWatchlist({
                  ticker: ticker.trim().toUpperCase(),
                  source: 'analysis',
                  watch_reason: 'Added from analysis page',
                  tags: ['analysis_reviewed'],
                  analysis_snapshot: results || undefined,
                })
                alert(`Added ${ticker.trim().toUpperCase()} to watchlist`)
              } catch (err) {
                alert(err.message)
              }
            }}
            className="btn-secondary flex items-center gap-2"
          >
            <Eye className="w-4 h-4" />
            Watch
          </button>
        )}
      </div>

      {/* Live Market Data Panel */}
      {results.quote && (
        <div className="card mb-4 border border-gray-700">
          <div className="flex justify-between items-start mb-3">
            <div>
              <div className="text-xs text-gray-500 uppercase tracking-wider flex items-center gap-1">
                <DollarSign className="w-3 h-3" /> Live Market Data
              </div>
              <h3 className="text-xl font-bold text-white">{ticker.trim().toUpperCase()}</h3>
            </div>
            <div className="text-right">
              <div className="text-3xl font-bold text-white">${results.quote.price?.toFixed(2)}</div>
              <div className={`text-sm font-semibold ${results.quote.change >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {results.quote.change >= 0 ? '+' : ''}{results.quote.change?.toFixed(2)} ({results.quote.change >= 0 ? '+' : ''}{results.quote.change_pct?.toFixed(2)}%)
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs mb-3">
            <div><div className="text-gray-500">Open</div><div className="text-white font-semibold">${results.quote.open?.toFixed(2)}</div></div>
            <div><div className="text-gray-500">Prev Close</div><div className="text-white font-semibold">${results.quote.previous_close?.toFixed(2)}</div></div>
            <div><div className="text-gray-500">Day High</div><div className="text-emerald-400 font-semibold">${results.quote.day_high?.toFixed(2)}</div></div>
            <div><div className="text-gray-500">Day Low</div><div className="text-red-400 font-semibold">${results.quote.day_low?.toFixed(2)}</div></div>
          </div>

          {(results.quote.premarket?.volume > 0 || results.quote.afterhours?.volume > 0) && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 border-t border-gray-700 pt-3">
              {results.quote.premarket?.volume > 0 && (
                <div className="bg-blue-500/5 border border-blue-500/20 rounded-lg p-2">
                  <div className="text-xs text-blue-400 font-semibold mb-1 flex items-center gap-1">
                    <Clock className="w-3 h-3" /> Pre-Market
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-xs">
                    <div><div className="text-gray-500">Gap</div><div className={`font-bold ${results.quote.premarket.gap_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>{results.quote.premarket.gap_pct >= 0 ? '+' : ''}{results.quote.premarket.gap_pct?.toFixed(2)}%</div></div>
                    <div><div className="text-gray-500">High</div><div className="text-white">${results.quote.premarket.high?.toFixed(2)}</div></div>
                    <div><div className="text-gray-500">Volume</div><div className="text-white">{results.quote.premarket.volume?.toLocaleString()}</div></div>
                  </div>
                </div>
              )}
              {results.quote.afterhours?.volume > 0 && (
                <div className="bg-purple-500/5 border border-purple-500/20 rounded-lg p-2">
                  <div className="text-xs text-purple-400 font-semibold mb-1 flex items-center gap-1">
                    <Clock className="w-3 h-3" /> After Hours
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-xs">
                    <div><div className="text-gray-500">High</div><div className="text-white">${results.quote.afterhours.high?.toFixed(2)}</div></div>
                    <div><div className="text-gray-500">Low</div><div className="text-white">${results.quote.afterhours.low?.toFixed(2)}</div></div>
                    <div><div className="text-gray-500">Volume</div><div className="text-white">{results.quote.afterhours.volume?.toLocaleString()}</div></div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {results.volumeProfile && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
          {/* Volume Profile Summary */}
          <div className="card">
            <div className="card-header flex items-center gap-2">
              <BarChart3 className="w-4 h-4 text-oracle-400" />
              Volume Profile
            </div>
            {results.volumeProfile.error ? (
              <p className="text-sm text-red-400">{results.volumeProfile.error}</p>
            ) : (
              <div className="space-y-3">
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <div className="stat-label">POC</div>
                    <div className="text-lg font-bold text-white">
                      ${results.volumeProfile.poc_price?.toFixed(2)}
                    </div>
                  </div>
                  <div>
                    <div className="stat-label">Value Area High</div>
                    <div className="text-lg font-bold text-emerald-400">
                      ${results.volumeProfile.value_area_high?.toFixed(2)}
                    </div>
                  </div>
                  <div>
                    <div className="stat-label">Value Area Low</div>
                    <div className="text-lg font-bold text-red-400">
                      ${results.volumeProfile.value_area_low?.toFixed(2)}
                    </div>
                  </div>
                </div>
                {results.volumeProfile.high_volume_nodes?.length > 0 && (
                  <div>
                    <div className="stat-label mb-1">High Volume Nodes</div>
                    <div className="flex flex-wrap gap-2">
                      {results.volumeProfile.high_volume_nodes.map((n, i) => (
                        <span key={i} className="bg-oracle-600/20 text-oracle-300 px-2 py-0.5 rounded text-xs">
                          ${n.toFixed(2)}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Regime */}
          <div className="card">
            <div className="card-header flex items-center gap-2">
              <Activity className="w-4 h-4 text-amber-400" />
              Market Regime
            </div>
            {results.regime?.error ? (
              <p className="text-sm text-red-400">{results.regime.error}</p>
            ) : (
              <div className="space-y-2">
                <div className="flex items-center gap-3">
                  <span className="text-2xl font-bold text-white capitalize">
                    {results.regime?.regime?.replace('_', ' ')}
                  </span>
                  <span className="badge-neutral">
                    Sensitivity: {results.regime?.sensitivity_multiplier?.toFixed(1)}x
                  </span>
                </div>
                <div className="grid grid-cols-3 gap-3 text-sm">
                  <div>
                    <div className="stat-label">ADX</div>
                    <div className="text-white font-semibold">{results.regime?.adx?.toFixed(1)}</div>
                  </div>
                  <div>
                    <div className="stat-label">ATR %</div>
                    <div className="text-white font-semibold">{results.regime?.atr_pct?.toFixed(2)}%</div>
                  </div>
                  <div>
                    <div className="stat-label">BB Width</div>
                    <div className="text-white font-semibold">{results.regime?.bb_width?.toFixed(4)}</div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {(results.stage || results.orderFlow) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Stage */}
          <div className="card">
            <div className="card-header flex items-center gap-2">
              <Layers className="w-4 h-4 text-purple-400" />
              Stage of Move
            </div>
            {results.stage?.error ? (
              <p className="text-sm text-red-400">{results.stage.error}</p>
            ) : results.stage ? (
              <div>
                <div className="text-3xl font-bold text-white mb-1">
                  Stage {results.stage?.stage}
                </div>
                <p className="text-sm text-gray-400 mb-2">{results.stage?.reason}</p>
                <span className={results.stage?.entry_allowed ? 'badge-buy' : 'badge-avoid'}>
                  {results.stage?.entry_allowed ? 'Entry Allowed' : 'Entry Blocked'}
                </span>
              </div>
            ) : (
              <p className="text-sm text-gray-500">No stage data</p>
            )}
          </div>

          {/* Order Flow */}
          <div className="card">
            <div className="card-header flex items-center gap-2">
              <Zap className="w-4 h-4 text-yellow-400" />
              Order Flow
            </div>
            {results.orderFlow?.error ? (
              <p className="text-sm text-red-400">{results.orderFlow.error}</p>
            ) : (
              <div>
                <div className={`text-2xl font-bold mb-2 capitalize ${
                  results.orderFlow?.signal === 'bullish' ? 'text-emerald-400' :
                  results.orderFlow?.signal === 'bearish' ? 'text-red-400' : 'text-gray-400'
                }`}>
                  {results.orderFlow?.signal}
                </div>
                <div className="grid grid-cols-2 gap-2 text-sm">
                  <div>
                    <div className="stat-label">Imbalance</div>
                    <div className="text-white font-semibold">{results.orderFlow?.bid_ask_imbalance}</div>
                  </div>
                  <div>
                    <div className="stat-label">Net Flow</div>
                    <div className={`font-semibold ${
                      results.orderFlow?.net_flow > 0 ? 'text-emerald-400' : 'text-red-400'
                    }`}>
                      {results.orderFlow?.net_flow?.toLocaleString()}
                    </div>
                  </div>
                  <div>
                    <div className="stat-label">Buy %</div>
                    <div className="text-white font-semibold">
                      {(results.orderFlow?.aggressive_buy_ratio * 100)?.toFixed(1)}%
                    </div>
                  </div>
                  <div>
                    <div className="stat-label">Sell %</div>
                    <div className="text-white font-semibold">
                      {(results.orderFlow?.aggressive_sell_ratio * 100)?.toFixed(1)}%
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Error Display */}
      {Object.entries(results).some(([_, v]) => v?.error) && (
        <div className="card mt-4 border-red-500/50">
          <div className="card-header text-red-400">API Errors</div>
          <div className="text-sm text-red-400 space-y-1">
            {Object.entries(results).map(([key, val]) => 
              val?.error ? <div key={key}><strong>{key}:</strong> {val.error}</div> : null
            )}
          </div>
        </div>
      )}
    </div>
  )
}
