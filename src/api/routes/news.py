"""
News API routes — Finviz news endpoints.

Endpoints:
- GET /news/finviz — fetch all Finviz news (v=3 + v=6)
- GET /news/finviz/news — news articles only (v=3)
- GET /news/finviz/blogs — blogs/press releases only (v=6)
"""

import logging
from fastapi import APIRouter
from src.core.finviz_news import FinvizNewsScraper

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/news", tags=["news"])

# Shared scraper instance
_scraper = FinvizNewsScraper()


@router.get("/finviz")
def get_finviz_news():
    """Fetch all Finviz news (articles + blogs/press releases). Updates every 5 minutes via frontend polling."""
    try:
        summary = _scraper.fetch_all()
        return summary.to_dict()
    except Exception as exc:
        logger.error("Failed to fetch Finviz news: %s", exc)
        return {"error": str(exc), "news": [], "blogs": [], "count": 0}


@router.get("/finviz/news")
def get_finviz_articles():
    """Fetch Finviz news articles only (v=3)."""
    try:
        items = _scraper._fetch_news()
        return {"news": [n.to_dict() for n in items], "count": len(items)}
    except Exception as exc:
        logger.error("Failed to fetch news: %s", exc)
        return {"error": str(exc), "news": [], "count": 0}


@router.get("/finviz/blogs")
def get_finviz_blogs():
    """Fetch Finviz blogs/press releases only (v=6)."""
    try:
        items = _scraper._fetch_blogs()
        return {"blogs": [b.to_dict() for b in items], "count": len(items)}
    except Exception as exc:
        logger.error("Failed to fetch blogs: %s", exc)
        return {"error": str(exc), "blogs": [], "count": 0}
