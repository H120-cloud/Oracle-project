import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Rocket,
  AlertTriangle,
  TrendingUp,
  TrendingDown,
  Zap,
  Brain,
  BarChart3,
  RefreshCw,
  Filter,
  ChevronDown,
  ChevronUp,
  MessageCircle,
  Activity,
  Target,
  Clock,
  ShieldAlert,
  EyeOff,
} from 'lucide-react'
import {
  newsMomentumCandidates,
  newsMomentumTopRanked,
  newsMomentumTopExpectedReturn,
  newsMomentumTopContinuation,
  newsMomentumTopMultiday,
  newsMomentumTelegramQuality,
  newsMomentumStats,
  newsMomentumCatalystStats,
  newsMomentumScanNow,
  newsMomentumConfig,
  newsMomentumUpdateConfig,
  newsMomentumDeactivate,
  newsMomentumMissedWinners,
  newsMomentumMissedWinnersReport,
} from '../api_strategic'

const SCORE_COLORS = {
  high: 'text-emerald-400',
  medium: 'text-yellow-400',
  low: 'text-red-400',
}

function scoreColor(score) {
  if (score >= 75) return SCORE_COLORS.high
  if (score >= 50) return SCORE_COLORS.medium
  return SCORE_COLORS.low
}

function ScoreBadge({ score, label, icon: Icon }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      {Icon && <Icon className={`w-4 h-4 ${scoreColor(score)}`} />}
      <span className="text-gray-400">{label}:</span>
      <span className={`font-bold ${scoreColor(score)}`}>{score?.toFixed ? score.toFixed(1) : score}</span>
    </div>
  )
}

function CandidateCard({ candidate, onDeactivate }) {
  const [expanded, setExpanded] = useState(false)
  const actionColors = {
    WATCH: 'bg-blue-600/20 text-blue-400',
    TRADEABLE: 'bg-emerald-600/20 text-emerald-400',
    'SWING_WATCH': 'bg-purple-600/20 text-purple-400',
    'WAIT_FOR_RETEST': 'bg-yellow-600/20 text-yellow-400',
    'AVOID_CHASE': 'bg-orange-600/20 text-orange-400',
    'AVOID_TRAP': 'bg-red-600/20 text-red-400',
  }

  return (
    <div className={`card p-4 mb-3 ${candidate.trap_risk > 70 ? 'border-red-500/30' : ''}`}>
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <div className="flex items-center gap-3 mb-2">
            <h3 className="text-lg font-bold text-white">{candidate.ticker}</h3>
            <span className={`px-2 py-0.5 rounded text-xs font-medium ${actionColors[candidate.oracle_action] || 'bg-gray-700 text-gray-300'}`}>
              {candidate.oracle_action?.replace('_', ' ')}
            </span>
            {candidate.telegram_sent && (
              <span className="px-2 py-0.5 rounded text-xs bg-blue-600/20 text-blue-400 flex items-center gap-1">
                <MessageCircle className="w-3 h-3" /> Telegram
              </span>
            )}
            {candidate.trap_risk > 70 && (
              <span className="px-2 py-0.5 rounded text-xs bg-red-600/20 text-red-400 flex items-center gap-1">
                <ShieldAlert className="w-3 h-3" /> Trap Warning
              </span>
            )}
          </div>
          <p className="text-sm text-gray-300 mb-2 line-clamp-2">{candidate.headline}</p>
          <div className="flex flex-wrap gap-4 text-sm">
            <span className="text-gray-400">${candidate.current_price?.toFixed ? candidate.current_price.toFixed(4) : candidate.current_price}</span>
            <span className={candidate.move_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}>
              {candidate.move_pct >= 0 ? '+' : ''}{candidate.move_pct?.toFixed ? candidate.move_pct.toFixed(2) : candidate.move_pct}%
            </span>
            <span className="text-gray-500">{candidate.catalyst_sub_type?.replace(/_/g, ' ')}</span>
            <span className="text-gray-500">{candidate.session}</span>
          </div>
        </div>
        <div className="text-right ml-4">
          <div className="text-2xl font-bold text-white">#{candidate.rank || '-'}</div>
          <div className="text-xs text-gray-500">Rank</div>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3 pt-3 border-t border-gray-800">
        <ScoreBadge score={candidate.news_impact_score} label="Impact" icon={Zap} />
        <ScoreBadge score={candidate.expected_return_score} label="Exp. Return" icon={Target} />
        <ScoreBadge score={candidate.continuation_probability} label="Continuation" icon={TrendingUp} />
        <ScoreBadge score={candidate.multi_day_continuation_score} label="Multi-Day" icon={BarChart3} />
      </div>

      {expanded && (
        <div className="mt-3 pt-3 border-t border-gray-800 space-y-3">
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
            <div><span className="text-gray-500">Next-Day Cont:</span> <span className="text-white">{candidate.next_day_continuation_probability?.toFixed(1)}%</span></div>
            <div><span className="text-gray-500">2-Day Cont:</span> <span className="text-white">{candidate.two_day_continuation_probability?.toFixed(1)}%</span></div>
            <div><span className="text-gray-500">5-Day Cont:</span> <span className="text-white">{candidate.five_day_continuation_probability?.toFixed(1)}%</span></div>
            <div><span className="text-gray-500">Gap-Up Prob:</span> <span className="text-white">{candidate.next_day_gap_up_probability?.toFixed(1)}%</span></div>
            <div><span className="text-gray-500">Trap Risk:</span> <span className={candidate.trap_risk > 50 ? 'text-red-400' : 'text-gray-300'}>{candidate.trap_risk?.toFixed(1)}</span></div>
            <div><span className="text-gray-500">Dilution:</span> <span className={candidate.dilution_risk > 40 ? 'text-red-400' : 'text-gray-300'}>{candidate.dilution_risk?.toFixed(1)}</span></div>
          </div>

          {candidate.estimated_move && (
            <div className="text-sm">
              <span className="text-gray-500">Est. Moves:</span>
              <span className="text-gray-300 ml-2">Conservative +{candidate.estimated_move.conservative_pct}%</span>
              <span className="text-emerald-400 ml-2">Bullish +{candidate.estimated_move.bullish_pct}%</span>
              <span className="text-purple-400 ml-2">Extreme +{candidate.estimated_move.extreme_pct}%</span>
            </div>
          )}

          {candidate.bull_bear && (
            <div className="space-y-1 text-sm">
              <p className="text-emerald-400"><span className="text-gray-500">Bull:</span> {candidate.bull_bear.bull_case}</p>
              <p className="text-red-400"><span className="text-gray-500">Bear:</span> {candidate.bull_bear.bear_case}</p>
            </div>
          )}

          <div className="flex gap-2">
            <button onClick={() => onDeactivate(candidate.ticker)} className="btn-sm btn-danger">
              Deactivate
            </button>
          </div>
        </div>
      )}

      <button onClick={() => setExpanded(!expanded)} className="mt-2 text-xs text-gray-500 hover:text-white flex items-center gap-1">
        {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
        {expanded ? 'Collapse' : 'Expand'}
      </button>
    </div>
  )
}

export default function NewsMomentum() {
  const [activeTab, setActiveTab] = useState('candidates')
  const [candidates, setCandidates] = useState([])
  const [stats, setStats] = useState(null)
  const [telegramQuality, setTelegramQuality] = useState(null)
  const [catalystStats, setCatalystStats] = useState(null)
  const [missedWinners, setMissedWinners] = useState(null)
  const [missedReport, setMissedReport] = useState(null)
  const [config, setConfig] = useState(null)
  const [loading, setLoading] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState(null)
  const [filterSession, setFilterSession] = useState('all')
  const intervalRef = useRef(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [cand, st, tq, cs, mw, mr, cfg] = await Promise.all([
        newsMomentumCandidates(true, 50),
        newsMomentumStats(),
        newsMomentumTelegramQuality(),
        newsMomentumCatalystStats(),
        newsMomentumMissedWinners(50),
        newsMomentumMissedWinnersReport(),
        newsMomentumConfig(),
      ])
      setCandidates(cand || [])
      setStats(st)
      setTelegramQuality(tq)
      setCatalystStats(cs)
      setMissedWinners(mw || [])
      setMissedReport(mr || null)
      setConfig(cfg)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData()
    intervalRef.current = setInterval(fetchData, 30000)
    return () => clearInterval(intervalRef.current)
  }, [fetchData])

  const handleScanNow = async () => {
    setScanning(true)
    try {
      await newsMomentumScanNow()
      await fetchData()
    } catch (err) {
      setError(err.message)
    } finally {
      setScanning(false)
    }
  }

  const handleDeactivate = async (ticker) => {
    try {
      await newsMomentumDeactivate(ticker)
      await fetchData()
    } catch (err) {
      setError(err.message)
    }
  }

  const filteredCandidates = candidates.filter(c => {
    if (filterSession === 'all') return true
    return c.session === filterSession
  })

  const tabs = [
    { id: 'candidates', label: 'All Candidates', icon: Activity },
    { id: 'expected', label: 'Top Expected Return', icon: Target },
    { id: 'continuation', label: 'Top Continuation', icon: TrendingUp },
    { id: 'multiday', label: 'Multi-Day Runners', icon: BarChart3 },
    { id: 'traps', label: 'Trap Warnings', icon: AlertTriangle },
    { id: 'quality', label: 'Telegram Quality', icon: MessageCircle },
    { id: 'missed', label: 'Missed Winners', icon: EyeOff },
    { id: 'learning', label: 'Learning', icon: Brain },
  ]

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Rocket className="w-6 h-6 text-oracle-500" />
            News Momentum Intelligence
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            AI-powered catalyst detection, scoring, and continuation prediction
          </p>
        </div>
        <div className="flex items-center gap-3">
          <select
            value={filterSession}
            onChange={(e) => setFilterSession(e.target.value)}
            className="bg-gray-800 border border-gray-700 text-white text-sm rounded-lg px-3 py-2"
          >
            <option value="all">All Sessions</option>
            <option value="premarket">Premarket</option>
            <option value="regular">Regular</option>
            <option value="after_hours">After Hours</option>
          </select>
          <button
            onClick={handleScanNow}
            disabled={scanning}
            className="btn-primary flex items-center gap-2"
          >
            <RefreshCw className={`w-4 h-4 ${scanning ? 'animate-spin' : ''}`} />
            Scan Now
          </button>
          <button onClick={fetchData} className="btn-secondary">
            Refresh
          </button>
        </div>
      </div>

      {/* Stats Bar */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
          <div className="card p-3">
            <div className="text-xs text-gray-500">Active Candidates</div>
            <div className="text-xl font-bold text-white">{stats.active_candidates}</div>
          </div>
          <div className="card p-3">
            <div className="text-xs text-gray-500">Total Scanned</div>
            <div className="text-xl font-bold text-white">{stats.total_candidates}</div>
          </div>
          <div className="card p-3">
            <div className="text-xs text-gray-500">Telegram Alerts</div>
            <div className="text-xl font-bold text-white">{stats.telegram_alerts_sent}</div>
          </div>
          <div className="card p-3">
            <div className="text-xs text-gray-500">Alert Quality</div>
            <div className={`text-xl font-bold ${(stats.telegram_quality?.quality_score || 0) > 60 ? 'text-emerald-400' : 'text-yellow-400'}`}>
              {stats.telegram_quality?.quality_score?.toFixed ? stats.telegram_quality.quality_score.toFixed(1) : '-'}
            </div>
          </div>
        </div>
      )}

      {error && (
        <div className="bg-red-900/20 border border-red-500/30 text-red-400 p-3 rounded-lg mb-4 text-sm">
          {error}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 mb-4 overflow-x-auto pb-1">
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition-colors ${
              activeTab === tab.id
                ? 'bg-oracle-600/20 text-oracle-400'
                : 'text-gray-400 hover:text-white hover:bg-gray-800'
            }`}
          >
            <tab.icon className="w-4 h-4" />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      {loading && candidates.length === 0 ? (
        <div className="text-center py-12 text-gray-500">Loading...</div>
      ) : (
        <>
          {activeTab === 'candidates' && (
            <div>
              {filteredCandidates.length === 0 ? (
                <div className="text-center py-12 text-gray-500">No active candidates found</div>
              ) : (
                filteredCandidates.map(c => (
                  <CandidateCard key={c.id || c.ticker} candidate={c} onDeactivate={handleDeactivate} />
                ))
              )}
            </div>
          )}

          {activeTab === 'expected' && (
            <div>
              {[...candidates]
                .sort((a, b) => (b.expected_return_score || 0) - (a.expected_return_score || 0))
                .slice(0, 20)
                .map(c => (
                  <CandidateCard key={c.id || c.ticker} candidate={c} onDeactivate={handleDeactivate} />
                ))}
            </div>
          )}

          {activeTab === 'continuation' && (
            <div>
              {[...candidates]
                .sort((a, b) => (b.continuation_probability || 0) - (a.continuation_probability || 0))
                .slice(0, 20)
                .map(c => (
                  <CandidateCard key={c.id || c.ticker} candidate={c} onDeactivate={handleDeactivate} />
                ))}
            </div>
          )}

          {activeTab === 'multiday' && (
            <div>
              {[...candidates]
                .sort((a, b) => (b.multi_day_continuation_score || 0) - (a.multi_day_continuation_score || 0))
                .slice(0, 20)
                .map(c => (
                  <CandidateCard key={c.id || c.ticker} candidate={c} onDeactivate={handleDeactivate} />
                ))}
            </div>
          )}

          {activeTab === 'traps' && (
            <div>
              {candidates
                .filter(c => (c.trap_risk || 0) > 70 || (c.dilution_risk || 0) > 70)
                .sort((a, b) => (b.trap_risk || 0) - (a.trap_risk || 0))
                .map(c => (
                  <CandidateCard key={c.id || c.ticker} candidate={c} onDeactivate={handleDeactivate} />
                ))}
            </div>
          )}

          {activeTab === 'quality' && telegramQuality && (
            <div className="card p-6">
              <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
                <MessageCircle className="w-5 h-5 text-oracle-500" />
                Telegram Alert Quality
              </h3>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                <div className="text-center">
                  <div className="text-2xl font-bold text-white">{telegramQuality.total_alerts}</div>
                  <div className="text-xs text-gray-500">Total Alerts</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold text-emerald-400">{telegramQuality.great_alerts}</div>
                  <div className="text-xs text-gray-500">Great</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold text-red-400">{telegramQuality.trap_alerts}</div>
                  <div className="text-xs text-gray-500">Traps</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold text-yellow-400">{telegramQuality.no_follow_through}</div>
                  <div className="text-xs text-gray-500">No Follow-Through</div>
                </div>
              </div>
              {telegramQuality.avg_mfe_pct !== null && (
                <div className="text-sm text-gray-300">
                  Avg MFE: <span className="text-emerald-400">{telegramQuality.avg_mfe_pct}%</span>
                  {telegramQuality.avg_mae_pct !== null && (
                    <span className="ml-4">Avg MAE: <span className="text-red-400">{telegramQuality.avg_mae_pct}%</span></span>
                  )}
                </div>
              )}
            </div>
          )}

          {activeTab === 'missed' && (
            <div className="space-y-4">
              {missedReport && (
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
                  <div className="card p-4 text-center">
                    <div className="text-2xl font-bold text-red-400">{missedReport.total_missed}</div>
                    <div className="text-xs text-gray-500">Missed Winners</div>
                  </div>
                  <div className="card p-4 text-center">
                    <div className="text-2xl font-bold text-yellow-400">{missedReport.recommendations_pending}</div>
                    <div className="text-xs text-gray-500">Pending Fixes</div>
                  </div>
                  <div className="card p-4 text-center">
                    <div className="text-2xl font-bold text-emerald-400">{missedReport.shadow_adjustments_active}</div>
                    <div className="text-xs text-gray-500">Shadow Adjustments</div>
                  </div>
                  <div className="card p-4 text-center">
                    <div className="text-2xl font-bold text-white">{missedReport.avg_move_missed}%</div>
                    <div className="text-xs text-gray-500">Avg Move Missed</div>
                  </div>
                </div>
              )}

              {missedWinners && missedWinners.length > 0 ? (
                <div className="space-y-3">
                  {missedWinners.map((r) => (
                    <div key={r.id} className="card p-4 border-l-4 border-red-500">
                      <div className="flex items-start justify-between mb-2">
                        <div>
                          <div className="font-bold text-white text-lg">{r.ticker}</div>
                          <div className="text-sm text-gray-400">{r.headline?.substring(0, 100)}...</div>
                        </div>
                        <div className="text-right">
                          <div className="text-xl font-bold text-red-400">+{r.move_same_day_pct || 'N/A'}%</div>
                          <div className="text-xs text-gray-500">Same Day</div>
                        </div>
                      </div>

                      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs mb-3">
                        <div><span className="text-gray-500">Catalyst:</span> <span className="text-gray-300">{r.catalyst_sub_type?.replace(/_/g, ' ')}</span></div>
                        <div><span className="text-gray-500">Reason:</span> <span className="text-red-400">{r.missed_reason?.replace(/_/g, ' ')}</span></div>
                        <div><span className="text-gray-500">Blocked:</span> <span className="text-yellow-400">{r.blocking_rule}</span></div>
                        <div><span className="text-gray-500">Status:</span> <span className="text-gray-300">{r.status}</span></div>
                      </div>

                      <div className="text-xs text-gray-500 mb-2">
                        Impact: {r.news_impact_score} | ER: {r.expected_return_score} | Cont: {r.continuation_probability}% | Trap: {r.trap_risk}
                      </div>

                      <div className="text-sm text-oracle-400 bg-oracle-900/20 p-2 rounded">
                        <span className="font-bold">💡 Fix:</span> {r.recommendation}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center py-12 text-gray-500">No missed winners detected yet. Oracle will automatically detect missed opportunities as it scans.</div>
              )}
            </div>
          )}

          {activeTab === 'learning' && catalystStats && (
            <div className="space-y-4">
              <div className="card p-6">
                <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
                  <Brain className="w-5 h-5 text-oracle-500" />
                  Catalyst Learning Statistics
                </h3>
                <div className="text-sm text-gray-500 mb-2">Total Outcomes: {catalystStats.total_outcomes}</div>

                {catalystStats.by_catalyst_type && Object.keys(catalystStats.by_catalyst_type).length > 0 ? (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-gray-500 border-b border-gray-800">
                          <th className="text-left py-2">Catalyst</th>
                          <th className="text-right">Total</th>
                          <th className="text-right">Cont. Rate</th>
                          <th className="text-right">Fade Rate</th>
                          <th className="text-right">Avg Move</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(catalystStats.by_catalyst_type).map(([cat, data]) => (
                          <tr key={cat} className="border-b border-gray-800/50">
                            <td className="py-2 text-white">{cat.replace(/_/g, ' ')}</td>
                            <td className="text-right text-gray-300">{data.total_occurrences}</td>
                            <td className="text-right text-emerald-400">{data.continuation_rate}%</td>
                            <td className="text-right text-red-400">{data.fade_rate}%</td>
                            <td className="text-right text-gray-300">{data.avg_move_pct}%</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="text-gray-500 text-sm">Insufficient data for catalyst learning. Need at least 20 outcomes per catalyst type.</div>
                )}

                {catalystStats.recommendations && catalystStats.recommendations.length > 0 && (
                  <div className="mt-4 space-y-2">
                    <h4 className="text-sm font-bold text-white">Adaptive Recommendations</h4>
                    {catalystStats.recommendations.map((rec, i) => (
                      <div key={i} className="text-sm text-gray-300 bg-gray-800/50 p-2 rounded">
                        {rec.message}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Adaptive Thresholds */}
              {stats?.adaptive_thresholds && (
                <div className="card p-6">
                  <h3 className="text-lg font-bold text-white mb-4">Adaptive Telegram Thresholds</h3>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <div className="text-center">
                      <div className="text-lg font-bold text-white">{stats.adaptive_thresholds.news_impact}</div>
                      <div className="text-xs text-gray-500">Min Impact Score</div>
                    </div>
                    <div className="text-center">
                      <div className="text-lg font-bold text-white">{stats.adaptive_thresholds.expected_return}</div>
                      <div className="text-xs text-gray-500">Min Exp. Return</div>
                    </div>
                    <div className="text-center">
                      <div className="text-lg font-bold text-white">{stats.adaptive_thresholds.continuation}</div>
                      <div className="text-xs text-gray-500">Min Continuation</div>
                    </div>
                    <div className="text-center">
                      <div className="text-lg font-bold text-white">{stats.adaptive_thresholds.multi_day}</div>
                      <div className="text-xs text-gray-500">Min Multi-Day</div>
                    </div>
                  </div>
                  {!stats.adaptive_thresholds.adapted && (
                    <p className="text-xs text-gray-500 mt-2">{stats.adaptive_thresholds.reason}</p>
                  )}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}
