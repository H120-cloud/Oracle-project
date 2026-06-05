import { Suspense } from 'react'
import { Routes, Route, NavLink, Navigate } from 'react-router-dom'
import {
  Activity,
  Brain,
  Clock,
  Gauge,
  Newspaper,
  Rocket,
  Zap,
} from 'lucide-react'
import News from './pages/News'
import Agentic from './pages/Agentic'
import HistoricalTraining from './pages/HistoricalTraining'
import NewsMomentum from './pages/NewsMomentum'
import SECIntelligence from './pages/SECIntelligence'
import TimingReview from './pages/TimingReview'
import Diagnostics from './pages/Diagnostics'
import FrontendAuthGate from './components/FrontendAuthGate'

const NAV = [
  { to: '/news-momentum', icon: Rocket, label: 'News Momentum' },
  { to: '/timing-review', icon: Clock, label: 'Timing Review' },
  { to: '/agentic', icon: Zap, label: 'Agentic / Pre-News' },
  { to: '/sec-intelligence', icon: Brain, label: 'SEC Intelligence' },
  { to: '/historical-training', icon: Brain, label: 'Historical Training' },
  { to: '/news', icon: Newspaper, label: 'News Feed' },
  { to: '/diagnostics', icon: Gauge, label: 'Diagnostics' },
]

function Sidebar() {
  return (
    <aside className="fixed inset-y-0 left-0 w-64 bg-gray-900 border-r border-gray-800 flex flex-col z-30">
      <div className="flex items-center gap-3 px-6 py-5 border-b border-gray-800">
        <Activity className="w-7 h-7 text-oracle-500" />
        <div>
          <h1 className="text-lg font-bold text-white tracking-tight">Oracle</h1>
          <p className="text-xs text-gray-500">News / Rocket Runner</p>
        </div>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-1">
        {NAV.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-oracle-600/20 text-oracle-400'
                  : 'text-gray-400 hover:text-white hover:bg-gray-800'
              }`
            }
          >
            <Icon className="w-4.5 h-4.5" />
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="px-4 py-4 border-t border-gray-800">
        <div className="text-xs text-gray-600">Oracle Lean — Rocket Runner</div>
      </div>
    </aside>
  )
}

export default function App() {
  return (
    <FrontendAuthGate>
      <div className="flex min-h-screen bg-gray-950">
        <Sidebar />
        <main className="flex-1 ml-64 p-6">
          <Suspense fallback={<div className="text-gray-400">Loading...</div>}>
            <Routes>
              <Route path="/" element={<Navigate to="/news-momentum" replace />} />
              <Route path="/news" element={<News />} />
              <Route path="/agentic" element={<Agentic />} />
              <Route path="/news-momentum" element={<NewsMomentum />} />
              <Route path="/timing-review" element={<TimingReview />} />
              <Route path="/sec-intelligence" element={<SECIntelligence />} />
              <Route path="/historical-training" element={<HistoricalTraining />} />
              <Route path="/diagnostics" element={<Diagnostics />} />
              <Route path="*" element={<Navigate to="/news-momentum" replace />} />
            </Routes>
          </Suspense>
        </main>
      </div>
    </FrontendAuthGate>
  )
}
