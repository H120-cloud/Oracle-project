import { useState, useEffect, useCallback } from 'react'
import { Newspaper, Clock, TrendingUp, TrendingDown, Minus, ExternalLink, RefreshCw } from 'lucide-react'
import { getFinvizNews } from '../api'

const SENTIMENT_COLORS = {
  bullish: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
  bearish: 'text-red-400 bg-red-500/10 border-red-500/20',
  neutral: 'text-gray-400 bg-gray-500/10 border-gray-500/20',
}

const SENTIMENT_ICONS = {
  bullish: TrendingUp,
  bearish: TrendingDown,
  neutral: Minus,
}

const CATEGORY_COLORS = {
  news: 'text-blue-400',
  blog: 'text-purple-400',
  press_release: 'text-amber-400',
}

function NewsCard({ item }) {
  const SentimentIcon = SENTIMENT_ICONS[item.sentiment] || Minus
  const time = item.timestamp ? new Date(item.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''

  return (
    <div className="card mb-3 border border-gray-700 hover:border-gray-600 transition-colors">
      <div className="flex items-start gap-3">
        <div className={`flex-shrink-0 p-2 rounded-lg border ${SENTIMENT_COLORS[item.sentiment]}`}>
          <SentimentIcon className="w-4 h-4" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className={`text-xs font-semibold uppercase ${CATEGORY_COLORS[item.category] || 'text-gray-400'}`}>
              {item.category?.replace('_', ' ')}
            </span>
            <span className="text-xs text-gray-500">• {item.source}</span>
            {time && <span className="text-xs text-gray-500">• {time}</span>}
          </div>
          <h4 className="text-sm text-white font-medium leading-snug mb-2">
            {item.headline}
          </h4>
          <div className="flex items-center gap-2 flex-wrap">
            {item.tickers?.map((ticker) => (
              <a
                key={ticker}
                href={`/intelligence?analyze=${ticker}`}
                className="text-xs px-2 py-0.5 rounded bg-oracle-500/20 text-oracle-300 hover:bg-oracle-500/30 transition-colors"
              >
                ${ticker}
              </a>
            ))}
            <a
              href={item.url}
              target="_blank"
              rel="noopener noreferrer"
              className="ml-auto text-xs text-gray-400 hover:text-oracle-400 flex items-center gap-1 transition-colors"
            >
              Read <ExternalLink className="w-3 h-3" />
            </a>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function News() {
  const [news, setNews] = useState([])
  const [blogs, setBlogs] = useState([])
  const [lastUpdated, setLastUpdated] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [activeTab, setActiveTab] = useState('all')

  const fetchNews = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await getFinvizNews()
      setNews(data.news || [])
      setBlogs(data.blogs || [])
      setLastUpdated(data.last_updated)
    } catch (err) {
      setError(err.message || 'Failed to fetch news')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchNews()
  }, [fetchNews])

  // Auto-refresh every 5 minutes
  useEffect(() => {
    const interval = setInterval(() => {
      fetchNews()
    }, 5 * 60 * 1000) // 5 minutes
    return () => clearInterval(interval)
  }, [fetchNews])

  const allItems = [...news, ...blogs].sort((a, b) => {
    if (!a.timestamp || !b.timestamp) return 0
    return new Date(b.timestamp) - new Date(a.timestamp)
  })

  const displayItems = activeTab === 'all' ? allItems : activeTab === 'news' ? news : blogs

  const counts = {
    all: allItems.length,
    news: news.length,
    blogs: blogs.length,
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Newspaper className="w-7 h-7 text-oracle-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">Stock News</h1>
            <p className="text-sm text-gray-500">Real-time news from Finviz • Auto-updates every 5 minutes</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdated && (
            <div className="flex items-center gap-1 text-xs text-gray-500">
              <Clock className="w-3 h-3" />
              Last updated: {new Date(lastUpdated).toLocaleTimeString()}
            </div>
          )}
          <button
            onClick={fetchNews}
            disabled={loading}
            className="btn-secondary flex items-center gap-2 text-sm"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 mb-6">
        {[
          { key: 'all', label: 'All News', count: counts.all },
          { key: 'news', label: 'Articles', count: counts.news },
          { key: 'blogs', label: 'Blogs / Press', count: counts.blogs },
        ].map(({ key, label, count }) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              activeTab === key
                ? 'bg-oracle-500/20 text-oracle-400 border border-oracle-500/50'
                : 'text-gray-400 hover:text-white hover:bg-gray-800 border border-transparent'
            }`}
          >
            {label} ({count})
          </button>
        ))}
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/50 rounded-lg p-3 mb-4 text-red-400 text-sm">
          {error}
        </div>
      )}

      {loading && !displayItems.length && (
        <div className="text-center py-12">
          <RefreshCw className="w-8 h-8 text-oracle-400 animate-spin mx-auto mb-2" />
          <p className="text-gray-500">Loading news from Finviz...</p>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div>
          <h2 className="text-sm font-semibold text-gray-400 mb-3 uppercase tracking-wider">
            {activeTab === 'all' ? 'Latest News' : activeTab === 'news' ? 'News Articles' : 'Blogs & Press Releases'}
          </h2>
          <div className="space-y-2 max-h-[calc(100vh-280px)] overflow-y-auto pr-2">
            {displayItems.length > 0 ? (
              displayItems.map((item, idx) => <NewsCard key={idx} item={item} />)
            ) : (
              <p className="text-gray-500 text-sm">No news available</p>
            )}
          </div>
        </div>

        {/* Sidebar Stats */}
        <div className="space-y-4">
          <div className="card">
            <h3 className="text-sm font-semibold text-gray-400 mb-3">Sentiment Overview</h3>
            <div className="space-y-2">
              {['bullish', 'bearish', 'neutral'].map((sentiment) => {
                const count = allItems.filter((i) => i.sentiment === sentiment).length
                const percent = allItems.length ? Math.round((count / allItems.length) * 100) : 0
                return (
                  <div key={sentiment} className="flex items-center gap-3">
                    <span className={`text-xs font-medium capitalize w-16 ${SENTIMENT_COLORS[sentiment].split(' ')[0]}`}>
                      {sentiment}
                    </span>
                    <div className="flex-1 h-2 bg-gray-700 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full ${
                          sentiment === 'bullish' ? 'bg-emerald-500' : sentiment === 'bearish' ? 'bg-red-500' : 'bg-gray-500'
                        }`}
                        style={{ width: `${percent}%` }}
                      />
                    </div>
                    <span className="text-xs text-gray-400 w-10 text-right">{count}</span>
                  </div>
                )
              })}
            </div>
          </div>

          <div className="card">
            <h3 className="text-sm font-semibold text-gray-400 mb-3">Top Mentioned Tickers</h3>
            <div className="flex flex-wrap gap-2">
              {Object.entries(
                allItems
                  .flatMap((i) => i.tickers || [])
                  .reduce((acc, t) => {
                    acc[t] = (acc[t] || 0) + 1
                    return acc
                  }, {})
              )
                .sort((a, b) => b[1] - a[1])
                .slice(0, 15)
                .map(([ticker, count]) => (
                  <a
                    key={ticker}
                    href={`/intelligence?analyze=${ticker}`}
                    className="text-xs px-2 py-1 rounded bg-gray-700/50 text-gray-300 hover:bg-oracle-500/20 hover:text-oracle-300 transition-colors"
                  >
                    ${ticker} ({count})
                  </a>
                ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
