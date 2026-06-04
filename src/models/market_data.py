from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class OHLCVBar(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
