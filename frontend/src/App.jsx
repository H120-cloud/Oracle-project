import { Routes, Route, NavLink } from 'react-router-dom'
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
} from 'lucide-react'
import Dashboard from './pages/Dashboard'
import Analysis from './pages/Analysis'
import Backtest from './pages/Backtest'
import Performance from './pages/Performance'
import Portfolio from './pages/Portfolio'
import SettingsPage from './pages/Settings'
import Watchlist from './pages/Watchlist'
import Intelligence from './pages/Intelligence'
import ActiveTrades from './pages/ActiveTrades'
import News from './pages/News'
import PaperTrading from './pages/PaperTrading'

const NAV = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/intelligence', icon: Brain, label: 'Intelligence' },
  { to: '/active-trades', icon: ActivityIcon, label: 'Active Trades' },
  { to: '/analysis', icon: LineChart, label: 'Analysis' },
  { to: '/news', icon: Newspaper, label: 'News' },
  { to: '/watchlist', icon: Eye, label: 'Watchlist' },
  { to: '/portfolio', icon: Briefcase, label: 'Portfolio' },
  { to: '/backtest', icon: FlaskConical, label: 'Backtest' },
  { to: '/paper-trading', icon: FlaskConical, label: 'Paper Trading' },
  { to: '/performance', icon: BarChart3, label: 'Performance' },
  { to: '/settings', icon: Settings, label: 'Settings' },
]

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
        {NAV.map(({ to, icon: Icon, label }) => (
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
        <div className="text-xs text-gray-600">Oracle V10.0 — Paper Trading + Validation</div>
      </div>
    </aside>
  )
}

export default function App() {
  return (
    <div className="flex min-h-screen bg-gray-950">
      <Sidebar />
      <main className="flex-1 ml-64 p-6">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/intelligence" element={<Intelligence />} />
          <Route path="/active-trades" element={<ActiveTrades />} />
          <Route path="/analysis" element={<Analysis />} />
          <Route path="/news" element={<News />} />
          <Route path="/watchlist" element={<Watchlist />} />
          <Route path="/portfolio" element={<Portfolio />} />
          <Route path="/backtest" element={<Backtest />} />
          <Route path="/paper-trading" element={<PaperTrading />} />
          <Route path="/performance" element={<Performance />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  )
}
