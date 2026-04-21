import { useState, useEffect } from 'react'
import { Brain, RefreshCw, CheckCircle, XCircle, Server } from 'lucide-react'
import { getHealth, getModelStatus, trainModels } from '../api'

export default function Settings() {
  const [health, setHealth] = useState(null)
  const [modelStatus, setModelStatus] = useState(null)
  const [training, setTraining] = useState(false)
  const [trainResult, setTrainResult] = useState(null)

  useEffect(() => {
    const load = async () => {
      try {
        const [h, m] = await Promise.allSettled([getHealth(), getModelStatus()])
        if (h.status === 'fulfilled') setHealth(h.value)
        if (m.status === 'fulfilled') setModelStatus(m.value)
      } catch {}
    }
    load()
  }, [])

  const handleTrain = async () => {
    setTraining(true)
    setTrainResult(null)
    try {
      const result = await trainModels()
      setTrainResult(result)
    } catch (err) {
      setTrainResult({ error: err.message })
    } finally {
      setTraining(false)
    }
  }

  return (
    <div>
      <h2 className="text-2xl font-bold text-white mb-6">Settings & System</h2>

      {/* System Health */}
      <div className="card mb-6">
        <div className="card-header flex items-center gap-2">
          <Server className="w-4 h-4 text-oracle-400" />
          System Status
        </div>
        {health ? (
          <div className="grid grid-cols-3 gap-4">
            <div>
              <div className="stat-label">Status</div>
              <div className="flex items-center gap-2 mt-1">
                <CheckCircle className="w-5 h-5 text-emerald-400" />
                <span className="text-emerald-400 font-semibold">Online</span>
              </div>
            </div>
            <div>
              <div className="stat-label">Version</div>
              <div className="stat-value">{health.version}</div>
            </div>
            <div>
              <div className="stat-label">Phase</div>
              <div className="stat-value">{health.phase}</div>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-2 text-red-400">
            <XCircle className="w-5 h-5" />
            <span>Cannot connect to backend</span>
          </div>
        )}
      </div>

      {/* ML Models */}
      <div className="card mb-6">
        <div className="card-header flex items-center gap-2">
          <Brain className="w-4 h-4 text-purple-400" />
          ML Models
        </div>
        {modelStatus && !modelStatus.error ? (
          <div className="space-y-4">
            {Object.entries(modelStatus).map(([name, info]) => (
              <div key={name} className="flex items-center justify-between p-3 bg-gray-800/50 rounded-lg">
                <div>
                  <div className="text-sm font-medium text-white capitalize">{name} Model</div>
                  <div className="text-xs text-gray-500">
                    {info.trained ? `Trained — Version ${info.version}` : 'Not trained (cold start)'}
                  </div>
                </div>
                <span className={info.trained ? 'badge-buy' : 'badge-neutral'}>
                  {info.trained ? 'Active' : 'Cold Start'}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-gray-500">Model status unavailable. Backend may not be running.</p>
        )}

        <button
          onClick={handleTrain}
          disabled={training}
          className="btn-primary mt-4 flex items-center gap-2"
        >
          <RefreshCw className={`w-4 h-4 ${training ? 'animate-spin' : ''}`} />
          {training ? 'Training...' : 'Train All Models'}
        </button>

        {trainResult && (
          <div className={`mt-3 p-3 rounded-lg text-sm ${
            trainResult.error ? 'bg-red-900/20 text-red-400' : 'bg-emerald-900/20 text-emerald-400'
          }`}>
            {trainResult.error || 'Training complete!'}
          </div>
        )}
      </div>

      {/* Pipeline Info */}
      <div className="card">
        <div className="card-header">Signal Pipeline (V5)</div>
        <div className="space-y-2 text-sm">
          {[
            { step: '1. Scanner', desc: 'Market scan: volume, RVOL, gainers' },
            { step: '2. Volume Profile', desc: 'POC, value area, HVN, S/R levels' },
            { step: '3. Regime Detection', desc: 'Trending, choppy, high/low volatility' },
            { step: '4. Stock Segmentation', desc: 'Low-float, mid-cap, biotech, earnings' },
            { step: '5. Stage Detection', desc: '5 stages — only enter at stage 1-2' },
            { step: '6. Order Flow', desc: 'Bid/ask imbalance, net flow signal' },
            { step: '7. Dip Detection (± ML)', desc: 'Rule-based + ML enhanced probability' },
            { step: '8. Bounce Detection (± ML)', desc: 'Rule-based + ML enhanced probability' },
            { step: '9. Classification', desc: 'dip_forming, bounce_forming, breakout, etc.' },
            { step: '10. Decision Engine', desc: 'Entry/stop/target + risk score + grade' },
            { step: '11. Ranking', desc: 'Top 5 signals by composite quality score' },
            { step: '12. Logging', desc: 'Feature snapshots for ML training' },
          ].map(({ step, desc }) => (
            <div key={step} className="flex items-start gap-3 p-2 rounded hover:bg-gray-800/30">
              <span className="text-oracle-400 font-mono text-xs min-w-[3rem]">{step}</span>
              <span className="text-gray-400">{desc}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
