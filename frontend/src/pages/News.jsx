import { useState, useEffect, useCallback } from 'react'
import { Newspaper, Clock, TrendingUp, TrendingDown, Minus, ExternalLink, RefreshCw } from 'lucide-react'
import { getFinvizNews, getStockTitanNews, getAllNews, getLiveQuote } from '../api_strategic'

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

const TICKER_SENTIMENT_COLORS = {
  bullish: 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/25',
  bearish: 'bg-red-500/15 text-red-400 border border-red-500/30 hover:bg-red-500/25',
  neutral: 'bg-gray-700/50 text-gray-300 hover:bg-gray-600',
}

function getTickerColorClass(changePct) {
  if (changePct === undefined || changePct === null) return 'bg-gray-700/50 text-gray-300 hover:bg-gray-600'
  if (changePct > 0) return 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/25'
  if (changePct < 0) return 'bg-red-500/15 text-red-400 border border-red-500/30 hover:bg-red-500/25'
  return 'bg-gray-700/50 text-gray-300 hover:bg-gray-600'
}

function NewsCard({ item, tickerData }) {
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
            {item.tickers?.map((ticker) => {
              const quote = tickerData[ticker]
              const changePct = quote?.change_pct
              const sentimentClass = TICKER_SENTIMENT_COLORS[item.sentiment] || TICKER_SENTIMENT_COLORS.neutral
              return (
                <a
                  key={ticker}
                  href={`/intelligence?analyze=${ticker}`}
                  className={`text-xs px-2 py-0.5 rounded transition-colors ${sentimentClass}`}
                  title={quote ? `${quote.price?.toFixed(2)} (${changePct >= 0 ? '+' : ''}${changePct?.toFixed(2)}%)` : 'No live data'}
                >
                  ${ticker}
                  {quote && (
                    <span className="ml-1 text-[10px] opacity-80">
                      {changePct >= 0 ? '+' : ''}{changePct?.toFixed(1)}%
                    </span>
                  )}
                </a>
              )
            })}
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
  const [tickerData, setTickerData] = useState({})
  const [tickerFilter, setTickerFilter] = useState('all')
  const [newsSource, setNewsSource] = useState('all') // 'all', 'finviz', 'stocktitan'

  const fetchNews = useCallback(async ({ forceRefresh = false } = {}) => {
    setLoading(true)
    setError('')
    try {
      let newsItems = []
      let blogItems = []

      if (newsSource === 'finviz') {
        const data = await getFinvizNews({ forceRefresh })
        newsItems = data.news || []
        blogItems = data.blogs || []
        setLastUpdated(data.last_updated)
      } else if (newsSource === 'stocktitan') {
        const data = await getStockTitanNews({ forceRefresh })
        newsItems = data.news || []
        blogItems = []
        setLastUpdated(data.last_updated)
      } else {
        // Combined: all sources
        const data = await getAllNews({ forceRefresh })
        newsItems = data.news || []
        blogItems = []
        setLastUpdated(data.last_updated || new Date().toISOString())
      }

      setNews(newsItems)
      setBlogs(blogItems)

      // Fetch live quotes for all unique tickers
      const allTickers = [
        ...new Set(
          [...newsItems, ...blogItems]
            .flatMap((i) => i.tickers || [])
        ),
      ]
      if (allTickers.length > 0) {
        const quotes = await Promise.allSettled(
          allTickers.map((t) => getLiveQuote(t))
        )
        const newTickerData = {}
        allTickers.forEach((t, i) => {
          const res = quotes[i]
          if (res.status === 'fulfilled' && res.value?.change_pct !== undefined) {
            newTickerData[t] = res.value
          }
        })
        setTickerData(newTickerData)
      }
    } catch (err) {
      setError(err.message || 'Failed to fetch news')
    } finally {
      setLoading(false)
    }
  }, [newsSource])

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

  // Newest first; items without a parseable timestamp sink to the bottom
  const allItems = [...news, ...blogs].sort((a, b) => {
    const ta = a.timestamp ? new Date(a.timestamp).getTime() : -Infinity
    const tb = b.timestamp ? new Date(b.timestamp).getTime() : -Infinity
    return tb - ta
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
            <p className="text-sm text-gray-500">Real-time news from Finviz + Stock Titan • Auto-updates every 5 minutes</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {/* Source Toggle */}
          <div className="flex bg-gray-800/50 p-0.5 rounded-lg">
            {[
              { key: 'all', label: 'All Sources' },
              { key: 'finviz', label: 'Finviz' },
              { key: 'stocktitan', label: 'Stock Titan' },
            ].map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setNewsSource(key)}
                className={`px-2.5 py-1 rounded text-[11px] font-medium transition-colors ${
                  newsSource === key
                    ? 'bg-oracle-600/30 text-oracle-400'
                    : 'text-gray-400 hover:text-white'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          {lastUpdated && (
            <div className="flex items-center gap-1 text-xs text-gray-500">
              <Clock className="w-3 h-3" />
              Last updated: {new Date(lastUpdated).toLocaleTimeString()}
            </div>
          )}
          <button
            onClick={() => fetchNews({ forceRefresh: true })}
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
              displayItems.map((item, idx) => <NewsCard key={idx} item={item} tickerData={tickerData} />)
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
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-gray-400">Top Mentioned Tickers</h3>
            </div>
            <div className="flex flex-wrap gap-1.5 mb-3">
              {[
                { key: 'all', label: 'All' },
                { key: 'large', label: 'Large Cap' },
                { key: 'mid', label: 'Mid Cap' },
                { key: 'penny', label: 'Penny Stocks' },
              ].map(({ key, label }) => (
                <button
                  key={key}
                  onClick={() => setTickerFilter(key)}
                  className={`px-2 py-0.5 rounded text-[11px] font-medium transition-colors ${
                    tickerFilter === key
                      ? 'bg-oracle-500/20 text-oracle-400 border border-oracle-500/40'
                      : 'bg-gray-800 text-gray-400 hover:text-white hover:bg-gray-700 border border-transparent'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="flex flex-wrap gap-2">
              {(() => {
                // Compute per-ticker sentiment counts from articles
                const tickerSentimentCounts = {}
                allItems.forEach((item) => {
                  (item.tickers || []).forEach((t) => {
                    if (!tickerSentimentCounts[t]) tickerSentimentCounts[t] = { bullish: 0, bearish: 0, neutral: 0, count: 0 }
                    tickerSentimentCounts[t][item.sentiment || 'neutral']++
                    tickerSentimentCounts[t].count++
                  })
                })
                const getDominantSentiment = (counts) => {
                  if (counts.bullish > counts.bearish && counts.bullish > counts.neutral) return 'bullish'
                  if (counts.bearish > counts.bullish && counts.bearish > counts.neutral) return 'bearish'
                  return 'neutral'
                }
                const priceFilter = (ticker) => {
                  if (tickerFilter === 'all') return true
                  const price = tickerData[ticker]?.price
                  if (price === undefined || price === null) return false
                  if (tickerFilter === 'large') return price >= 50
                  if (tickerFilter === 'mid') return price >= 10 && price < 50
                  if (tickerFilter === 'penny') return price < 5
                  return true
                }
                return Object.entries(tickerSentimentCounts)
                  .filter(([ticker]) => priceFilter(ticker))
                  .sort((a, b) => b[1].count - a[1].count)
                  .slice(0, 15)
                  .map(([ticker, counts]) => {
                    const quote = tickerData[ticker]
                    const changePct = quote?.change_pct
                    const dominant = getDominantSentiment(counts)
                    return (
                      <a
                        key={ticker}
                        href={`/intelligence?analyze=${ticker}`}
                        className={`text-xs px-2 py-1 rounded transition-colors ${TICKER_SENTIMENT_COLORS[dominant]}`}
                        title={quote ? `${quote.price?.toFixed(2)} (${changePct >= 0 ? '+' : ''}${changePct?.toFixed(2)}%)` : 'No live data'}
                      >
                        ${ticker} ({counts.count})
                        {quote && (
                          <span className="ml-1 text-[10px] opacity-80">
                            {changePct >= 0 ? '+' : ''}{changePct?.toFixed(1)}%
                          </span>
                        )}
                      </a>
                    )
                  })
              })()}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
