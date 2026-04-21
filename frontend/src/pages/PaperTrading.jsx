import { useState, useEffect, useCallback } from 'react'
import { RefreshCw, TrendingUp, Target, CheckCircle, AlertTriangle, BarChart3, Play } from 'lucide-react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Area, ComposedChart, ReferenceLine } from 'recharts'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function MetricCard({ label, value, color = 'text-white' }) {
  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
      <p className="text-gray-400 text-xs mb-1">{label}</p>
      <p className={`text-xl font-bold ${color}`}>{value}</p>
    </div>
  )
}

export default function PaperTrading() {
  const [positions, setPositions] = useState([])
  const [trades, setTrades] = useState([])
  const [perf, setPerf] = useState(null)
  const [calibration, setCalibration] = useState(null)
  const [valResult, setValResult] = useState(null)
  const [validating, setValidating] = useState(false)
  const [tab, setTab] = useState('positions')
  const [loading, setLoading] = useState(false)
  const [valTickers, setValTickers] = useState('AAPL,MSFT,NVDA,TSLA,AMD,GOOGL,META,AMZN,NFLX,CRM,PYPL,UBER,COIN,PLTR,ROKU')
  const [valStart, setValStart] = useState('2024-06-01')
  const [valEnd, setValEnd] = useState('2025-04-19')
  const [valInterval, setValInterval] = useState('1d')

  const fetchAll = useCallback(async () => {
    setLoading(true)
    try {
      const [p, t, pf, c] = await Promise.all([
        fetch(`${API}/api/v1/paper/positions`).then(r=>r.json()).catch(()=>({positions:[]})),
        fetch(`${API}/api/v1/paper/trades?limit=100`).then(r=>r.json()).catch(()=>({trades:[]})),
        fetch(`${API}/api/v1/paper/performance`).then(r=>r.json()).catch(()=>null),
        fetch(`${API}/api/v1/paper/calibration`).then(r=>r.json()).catch(()=>null),
      ])
      setPositions(p.positions||[]); setTrades(t.trades||[]); setPerf(pf); setCalibration(c)
    } catch(e) { console.error(e) }
    setLoading(false)
  }, [])

  useEffect(() => { fetchAll() }, [fetchAll])

  const runValidation = async () => {
    setValidating(true)
    try {
      await fetch(`${API}/api/v1/paper/validate?tickers=${valTickers}&start=${valStart}&end=${valEnd}&interval=${valInterval}`, {method:'POST'})
      const poll = setInterval(async () => {
        const r = await fetch(`${API}/api/v1/paper/validation-results`).then(r=>r.json())
        if (r?.performance) { setValResult(r); setValidating(false); clearInterval(poll); fetchAll() }
      }, 3000)
      setTimeout(() => { clearInterval(poll); setValidating(false) }, 300000)
    } catch(e) { setValidating(false) }
  }

  const tabs = [
    {id:'positions', label:'Positions', icon:Target},
    {id:'trades', label:'Trades', icon:BarChart3},
    {id:'performance', label:'Performance', icon:TrendingUp},
    {id:'validation', label:'Validation', icon:CheckCircle},
    {id:'calibration', label:'Calibration', icon:AlertTriangle},
  ]

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Paper Trading & Validation</h1>
          <p className="text-gray-400 text-sm mt-1">V10 — Validate edge before going live</p>
        </div>
        <button onClick={fetchAll} disabled={loading}
          className="flex items-center gap-2 px-4 py-2 bg-gray-800 rounded-lg text-gray-300 hover:bg-gray-700">
          <RefreshCw className={`w-4 h-4 ${loading?'animate-spin':''}`}/> Refresh
        </button>
      </div>

      <div className="flex gap-1 bg-gray-900 p-1 rounded-lg">
        {tabs.map(t=>(
          <button key={t.id} onClick={()=>setTab(t.id)}
            className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              tab===t.id?'bg-oracle-600 text-white':'text-gray-400 hover:text-white hover:bg-gray-800'}`}>
            <t.icon className="w-4 h-4"/>{t.label}
          </button>
        ))}
      </div>

      {tab==='positions' && (
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-6">
          <h2 className="text-lg font-semibold text-white mb-4">Open Positions ({positions.length})</h2>
          {positions.length===0 ? <p className="text-gray-500 text-center py-8">No open positions</p> : (
            <table className="w-full text-sm"><thead><tr className="text-gray-400 border-b border-gray-800">
              <th className="text-left py-2 px-3">Ticker</th><th className="text-right py-2 px-3">Entry</th>
              <th className="text-right py-2 px-3">Current</th><th className="text-right py-2 px-3">P/L</th>
              <th className="text-center py-2 px-3">Conf</th><th className="text-center py-2 px-3">HTF</th>
            </tr></thead><tbody>
              {positions.map(p=>(
                <tr key={p.ticker} className="border-b border-gray-800/50">
                  <td className="py-2 px-3 font-bold text-white">{p.ticker}</td>
                  <td className="text-right py-2 px-3 text-gray-300">${p.entry_price?.toFixed(2)}</td>
                  <td className="text-right py-2 px-3 text-gray-300">${p.current_price?.toFixed(2)}</td>
                  <td className={`text-right py-2 px-3 font-medium ${p.unrealized_pnl_pct>0?'text-green-400':'text-red-400'}`}>
                    {p.unrealized_pnl_pct?.toFixed(1)}%</td>
                  <td className="text-center py-2 px-3 text-gray-300">{p.confidence?.toFixed(0)}%</td>
                  <td className={`text-center py-2 px-3 text-xs ${p.htf_bias==='BULLISH'?'text-green-400':p.htf_bias==='BEARISH'?'text-red-400':'text-gray-500'}`}>
                    {p.htf_bias||'—'}</td>
                </tr>))}
            </tbody></table>
          )}
        </div>
      )}

      {tab==='trades' && (
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-6">
          <h2 className="text-lg font-semibold text-white mb-4">Closed Trades ({trades.length})</h2>
          {trades.length===0 ? <p className="text-gray-500 text-center py-8">No closed trades yet</p> : (
            <table className="w-full text-sm"><thead><tr className="text-gray-400 border-b border-gray-800">
              <th className="text-left py-2 px-3">Ticker</th><th className="text-right py-2 px-3">P/L%</th>
              <th className="text-right py-2 px-3">P/L$</th><th className="text-center py-2 px-3">Exit</th>
              <th className="text-center py-2 px-3">Conf</th>
            </tr></thead><tbody>
              {trades.map((t,i)=>(
                <tr key={i} className="border-b border-gray-800/50">
                  <td className="py-2 px-3 font-bold text-white">{t.ticker}</td>
                  <td className={`text-right py-2 px-3 font-medium ${t.pnl_pct>0?'text-green-400':'text-red-400'}`}>
                    {t.pnl_pct>0?'+':''}{t.pnl_pct?.toFixed(2)}%</td>
                  <td className={`text-right py-2 px-3 ${t.pnl_dollars>0?'text-green-400':'text-red-400'}`}>${t.pnl_dollars?.toFixed(2)}</td>
                  <td className="text-center py-2 px-3"><span className={`px-2 py-0.5 rounded text-xs ${
                    t.exit_reason==='target'||t.exit_reason==='target_hit'?'bg-green-900/40 text-green-400':
                    t.exit_reason==='trailing_stop'?'bg-purple-900/40 text-purple-400':
                    t.exit_reason==='breakeven'?'bg-yellow-900/40 text-yellow-400':
                    t.exit_reason==='time_exit'?'bg-gray-700/40 text-gray-400':
                    'bg-red-900/40 text-red-400'}`}>{t.exit_reason}</span></td>
                  <td className="text-center py-2 px-3 text-gray-300">{t.confidence?.toFixed(0)}%</td>
                </tr>))}
            </tbody></table>
          )}
        </div>
      )}

      {tab==='performance' && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <MetricCard label="Total Trades" value={perf?.total_trades||0}/>
          <MetricCard label="Win Rate" value={`${perf?.win_rate||0}%`} color={perf?.win_rate>50?'text-green-400':'text-red-400'}/>
          <MetricCard label="Profit Factor" value={perf?.profit_factor||0} color={perf?.profit_factor>1?'text-green-400':'text-red-400'}/>
          <MetricCard label="Total P/L" value={`$${perf?.total_pnl||0}`} color={perf?.total_pnl>0?'text-green-400':'text-red-400'}/>
          <MetricCard label="Avg Win" value={`${perf?.avg_win_pct||0}%`} color="text-green-400"/>
          <MetricCard label="Avg Loss" value={`${perf?.avg_loss_pct||0}%`} color="text-red-400"/>
          <MetricCard label="Sharpe" value={perf?.sharpe_estimate||0} color={perf?.sharpe_estimate>1?'text-green-400':'text-yellow-400'}/>
          <MetricCard label="Max DD" value={`$${perf?.max_drawdown||0}`} color="text-red-400"/>
        </div>
      )}

      {tab==='validation' && (
        <div className="space-y-6">
          <div className="bg-gray-900 rounded-xl border border-gray-800 p-6">
            <h2 className="text-lg font-semibold text-white mb-4">Backtest Validation</h2>
            <p className="text-gray-400 text-sm mb-4">Run full pipeline on historical data to measure edge.</p>
            <div className="grid grid-cols-4 gap-4 mb-4">
              <div><label className="text-gray-400 text-xs">Tickers</label>
                <input value={valTickers} onChange={e=>setValTickers(e.target.value)}
                  className="w-full mt-1 px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white text-sm"/></div>
              <div><label className="text-gray-400 text-xs">Interval</label>
                <select value={valInterval} onChange={e=>setValInterval(e.target.value)}
                  className="w-full mt-1 px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white text-sm">
                  <option value="1d">1d (Daily - Full History)</option>
                  <option value="1h">1h (Hourly - 730 days max)</option>
                  <option value="5m">5m (5 min - 60 days max)</option>
                  <option value="1m">1m (1 min - 7 days max)</option>
                </select>
                <p className="text-gray-500 text-xs mt-1">{valInterval==='1d'?'Use any date range':valInterval==='5m'?'Use last 60 days only':valInterval==='1m'?'Use last 7 days only':'Use last 730 days'}</p>
              </div>
              <div><label className="text-gray-400 text-xs">Start</label>
                <input type="date" value={valStart} onChange={e=>setValStart(e.target.value)}
                  className="w-full mt-1 px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white text-sm"/></div>
              <div><label className="text-gray-400 text-xs">End</label>
                <input type="date" value={valEnd} onChange={e=>setValEnd(e.target.value)}
                  className="w-full mt-1 px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white text-sm"/></div>
            </div>
            <button onClick={runValidation} disabled={validating}
              className="flex items-center gap-2 px-6 py-2 bg-oracle-600 rounded-lg text-white hover:bg-oracle-500 disabled:opacity-50">
              <Play className="w-4 h-4"/> {validating?'Running...':'Run Validation'}
            </button>
          </div>
          {valResult?.performance && (
            <div className="bg-gray-900 rounded-xl border border-gray-800 p-6">
              <h3 className="text-md font-semibold text-white mb-3">Results</h3>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
                <MetricCard label="Trades" value={valResult.performance.total_trades}/>
                <MetricCard label="Win Rate" value={`${valResult.performance.win_rate}%`}
                  color={valResult.performance.win_rate>50?'text-green-400':'text-red-400'}/>
                <MetricCard label="Profit Factor" value={valResult.performance.profit_factor}
                  color={valResult.performance.profit_factor>1?'text-green-400':'text-red-400'}/>
                <MetricCard label="Sharpe" value={valResult.performance.sharpe}
                  color={valResult.performance.sharpe>1?'text-green-400':'text-yellow-400'}/>
              </div>
              {valResult.trailing_stop && (
                <div className="mt-4">
                  <h4 className="text-sm font-semibold text-white mb-2">Trailing Stop Analysis</h4>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
                    <MetricCard label="Reached +1R" value={`${valResult.trailing_stop.pct_reached_1r}%`} color="text-blue-400"/>
                    <MetricCard label="Reached +2R" value={`${valResult.trailing_stop.pct_reached_2r}%`} color="text-blue-400"/>
                    <MetricCard label="BE Activated" value={valResult.trailing_stop.breakeven_activated} color="text-yellow-400"/>
                    <MetricCard label="Trail Activated" value={valResult.trailing_stop.trailing_activated} color="text-purple-400"/>
                    <MetricCard label="Avg Max R" value={valResult.trailing_stop.avg_max_r} color="text-cyan-400"/>
                    <MetricCard label="Avg Realized R" value={valResult.trailing_stop.avg_realized_r}
                      color={valResult.trailing_stop.avg_realized_r>=0?'text-green-400':'text-red-400'}/>
                  </div>
                  {valResult.trailing_stop.exit_type_breakdown && (
                    <div className="flex flex-wrap gap-2">
                      {Object.entries(valResult.trailing_stop.exit_type_breakdown).map(([type,count])=>(
                        <span key={type} className={`px-2 py-1 rounded text-xs font-medium ${
                          type==='target'?'bg-green-900/40 text-green-400':
                          type==='trailing_stop'?'bg-purple-900/40 text-purple-400':
                          type==='breakeven'?'bg-yellow-900/40 text-yellow-400':
                          type==='time_exit'?'bg-gray-700/40 text-gray-400':
                          'bg-red-900/40 text-red-400'}`}>
                          {type}: {count}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )}
              {/* Equity Curve Chart */}
              {valResult.equity_curve && valResult.equity_curve.length > 0 && (
                <div className="mt-6">
                  <h4 className="text-sm font-semibold text-white mb-3">Equity Curve & Drawdown</h4>
                  <div className="bg-gray-800/50 rounded-lg p-4" style={{height: 320}}>
                    <ResponsiveContainer width="100%" height="100%">
                      <ComposedChart data={valResult.equity_curve} margin={{top:5,right:20,bottom:5,left:20}}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                        <XAxis dataKey="trade_num" stroke="#666" tick={{fontSize:11}} label={{value:'Trade #', position:'insideBottom', offset:-2, fill:'#888', fontSize:11}} />
                        <YAxis yAxisId="eq" stroke="#666" tick={{fontSize:11}} label={{value:'Equity %', angle:-90, position:'insideLeft', fill:'#888', fontSize:11}} />
                        <YAxis yAxisId="dd" orientation="right" stroke="#666" tick={{fontSize:11}} reversed />
                        <Tooltip
                          contentStyle={{background:'#1f2937',border:'1px solid #374151',borderRadius:8,fontSize:12}}
                          labelStyle={{color:'#9ca3af'}}
                          formatter={(val,name)=>[
                            name==='equity'?`${val}%`:name==='drawdown'?`-${val}%`:val,
                            name==='equity'?'Equity':name==='drawdown'?'Drawdown':name
                          ]}
                          labelFormatter={(n)=>{
                            const d=valResult.equity_curve[n-1];
                            return d?`#${n} ${d.ticker} (${d.exit_reason})`:`Trade #${n}`
                          }}
                        />
                        <ReferenceLine yAxisId="eq" y={100} stroke="#666" strokeDasharray="3 3" />
                        <Area yAxisId="dd" type="monotone" dataKey="drawdown" fill="#ef444420" stroke="#ef4444" strokeWidth={1} />
                        <Line yAxisId="eq" type="monotone" dataKey="equity" stroke="#10b981" strokeWidth={2} dot={false} />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}
              {valResult.verdict && (
                <div className={`mt-4 p-4 rounded-lg border ${valResult.verdict.has_edge?'border-green-700 bg-green-900/20':'border-red-700 bg-red-900/20'}`}>
                  <p className={`font-bold ${valResult.verdict.has_edge?'text-green-400':'text-red-400'}`}>
                    {valResult.verdict.has_edge?'Edge Detected':'No Reliable Edge'}
                  </p>
                  <p className="text-gray-400 text-sm mt-1">{valResult.verdict.recommendation}</p>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {tab==='calibration' && (
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-6">
          <h2 className="text-lg font-semibold text-white mb-4">Confidence Calibration</h2>
          {!calibration?.calibrated ? (
            <p className="text-gray-500 text-center py-8">Run validation first to calibrate confidence scores.</p>
          ) : (
            <div className="space-y-4">
              <p className="text-gray-400 text-sm">Based on {calibration.total_trades} trades (last calibrated: {calibration.last_calibrated?.slice(0,10)})</p>
              {calibration.buckets?.map(b => (
                <div key={b.raw_range} className="flex items-center gap-4">
                  <span className="text-gray-400 text-sm w-24">Raw {b.raw_range}</span>
                  <div className="flex-1 bg-gray-800 rounded-full h-4 overflow-hidden">
                    <div className={`h-full rounded-full ${b.actual_win_rate>50?'bg-green-500':'bg-red-500'}`}
                      style={{width:`${Math.min(b.actual_win_rate,100)}%`}}/>
                  </div>
                  <span className="text-sm text-gray-300 w-32 text-right">
                    Win: {b.actual_win_rate}% ({b.trades} trades)
                  </span>
                </div>
              ))}
              {calibration.htf_impact && Object.keys(calibration.htf_impact).length > 0 && (
                <div className="mt-4 pt-4 border-t border-gray-800">
                  <h4 className="text-sm font-medium text-white mb-2">HTF Bias Impact</h4>
                  {Object.entries(calibration.htf_impact).map(([bias, adj]) => (
                    <p key={bias} className="text-sm text-gray-400">
                      {bias}: <span className={adj>0?'text-green-400':'text-red-400'}>{adj>0?'+':''}{adj}%</span> vs baseline
                    </p>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
