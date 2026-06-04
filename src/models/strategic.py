"""
Strategic model aliases used by lean-mode systems.

These aliases keep strategic code away from legacy repository modules while
preserving the existing database schema and table names.
"""

from src.models.database import Base, Watchlist as ManualUniverseTicker

__all__ = ["Base", "ManualUniverseTicker"]
