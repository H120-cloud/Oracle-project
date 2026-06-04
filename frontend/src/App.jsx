import { Suspense } from 'react'
import { Routes, Route, NavLink, Navigate } from 'react-router-dom'
import {
  LayoutDashboard,
  LineChart,
  FlaskConical,
  BarChart3,
  Settings,
  Activity,
  Briefcase,
  Eye,
  Brain,
  Activity as ActivityIcon,
  Newspaper,
  Zap,
  Rocket,
} from 'lucide-react'
import News from './pages/News'
import Agentic from './pages/Agentic'
import HistoricalTraining from './pages/HistoricalTraining'
import NewsMomentum from './pages/NewsMomentum'
import SECIntelligence from './pages/SECIntelligence'

const LEAN_MODE = import.meta.env.VITE_ORACLE_LEAN_MODE === 'true'
const FRONTEND_FLAGS = {
  analysis: !LEAN_MODE || import.meta.env.VITE_ENABLE_ANALYSIS_ROUTES === 'true',
  backtest: !LEAN_MODE || import.meta.env.VITE_ENABLE_BACKTEST === 'true',
  intelligence: !LEAN_MODE || import.meta.env.VITE_ENABLE_INTELLIGENCE_ROUTES === 'true',
  paperTrading: !LEAN_MODE || import.meta.env.VITE_ENABLE_PAPER_TRADING === 'true',
  watchlist: !LEAN_MODE || import.meta.env.VITE_ENABLE_WATCHLIST === 'true',
}

const NAV = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard', legacy: true },
  { to: '/intelligence', icon: Brain, label: 'Intelligence', flag: 'intelligence' },
  { to: '/active-trades', icon: ActivityIcon, label: 'Active Trades', flag: 'intelligence' },
  { to: '/analysis', icon: LineChart, label: 'Analysis', flag: 'analysis' },
  { to: '/news', icon: Newspaper, label: 'News' },
  { to: '/watchlist', icon: Eye, label: 'Watchlist', flag: 'watchlist' },
  { to: '/portfolio', icon: Briefcase, label: 'Portfolio', legacy: true },
  { to: '/backtest', icon: FlaskConical, label: 'Backtest', flag: 'backtest' },
  { to: '/paper-trading', icon: FlaskConical, label: 'Paper Trading', flag: 'paperTrading' },
  { to: '/performance', icon: BarChart3, label: 'Performance', legacy: true },
  { to: '/agentic', icon: Zap, label: 'Agentic Mode' },
  { to: '/news-momentum', icon: Rocket, label: 'News Momentum' },
  { to: '/sec-intelligence', icon: Brain, label: 'SEC Intelligence' },
  { to: '/historical-training', icon: Brain, label: 'Historical Training' },
  { to: '/settings', icon: Settings, label: 'Settings', legacy: true },
]

function isVisible(item) {
  if (item.flag) return FRONTEND_FLAGS[item.flag]
  if (item.legacy) return !LEAN_MODE
  return true
}

function Sidebar() {
  return (
    <aside className="fixed inset-y-0 left-0 w-64 bg-gray-900 border-r border-gray-800 flex flex-col z-30">
      <div className="flex items-center gap-3 px-6 py-5 border-b border-gray-800">
        <Activity className="w-7 h-7 text-oracle-500" />
        <div>
          <h1 className="text-lg font-bold text-white tracking-tight">Oracle</h1>
          <p className="text-xs text-gray-500">Trading Signal Engine</p>
        </div>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-1">
        {NAV.filter(isVisible).map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
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
        <div className="text-xs text-gray-600">Oracle V23 — SEC Filing Intelligence</div>
      </div>
    </aside>
  )
}

function LegacyArchived({ title }) {
  return (
    <section className="min-h-[50vh] flex items-center justify-center">
      <div className="max-w-lg rounded-lg border border-gray-800 bg-gray-900/60 px-6 py-5">
        <h2 className="text-lg font-semibold text-white">{title}</h2>
        <p className="mt-2 text-sm text-gray-400">This legacy screen has been archived.</p>
      </div>
    </section>
  )
}

export default function App() {
  return (
    <div className="flex min-h-screen bg-gray-950">
      <Sidebar />
      <main className="flex-1 ml-64 p-6">
        <Suspense fallback={<div className="text-gray-400">Loading...</div>}>
          <Routes>
            <Route path="/" element={LEAN_MODE ? <Navigate to="/news-momentum" replace /> : <LegacyArchived title="Dashboard" />} />
            {FRONTEND_FLAGS.intelligence && <Route path="/intelligence" element={<LegacyArchived title="Intelligence" />} />}
            {FRONTEND_FLAGS.intelligence && <Route path="/active-trades" element={<LegacyArchived title="Active Trades" />} />}
            {FRONTEND_FLAGS.analysis && <Route path="/analysis" element={<LegacyArchived title="Analysis" />} />}
            <Route path="/news" element={<News />} />
            {FRONTEND_FLAGS.watchlist && <Route path="/watchlist" element={<LegacyArchived title="Watchlist" />} />}
            {!LEAN_MODE && <Route path="/portfolio" element={<LegacyArchived title="Portfolio" />} />}
            {FRONTEND_FLAGS.backtest && <Route path="/backtest" element={<LegacyArchived title="Backtest" />} />}
            {FRONTEND_FLAGS.paperTrading && <Route path="/paper-trading" element={<LegacyArchived title="Paper Trading" />} />}
            {!LEAN_MODE && <Route path="/performance" element={<LegacyArchived title="Performance" />} />}
            <Route path="/agentic" element={<Agentic />} />
            <Route path="/news-momentum" element={<NewsMomentum />} />
            <Route path="/sec-intelligence" element={<SECIntelligence />} />
            <Route path="/historical-training" element={<HistoricalTraining />} />
            {!LEAN_MODE && <Route path="/settings" element={<LegacyArchived title="Settings" />} />}
          </Routes>
        </Suspense>
      </main>
    </div>
  )
}
