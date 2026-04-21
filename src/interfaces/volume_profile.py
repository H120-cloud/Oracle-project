"""
Volume Profile Interface — Stub for V3

Will provide:
  - Point of Control (POC)
  - Value Area High / Low
  - High-volume nodes
  - Support/resistance identification from volume
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class VolumeProfileData:
    poc_price: float
    value_area_high: float
    value_area_low: float
    high_volume_nodes: list[float]


class IVolumeProfile(ABC):
    """Interface for Volume Profile engine (V3)."""

    @abstractmethod
    def compute_profile(self, ticker: str, bars: list) -> Optional[VolumeProfileData]:
        ...

    @abstractmethod
    def get_support_resistance(self, ticker: str) -> tuple[list[float], list[float]]:
        """Return (support_levels, resistance_levels)."""
        ...


class VolumeProfileStub(IVolumeProfile):
    """No-op implementation for V1."""

    def compute_profile(self, ticker: str, bars: list) -> Optional[VolumeProfileData]:
        raise NotImplementedError("Volume profile not available until V3")

    def get_support_resistance(self, ticker: str) -> tuple[list[float], list[float]]:
        raise NotImplementedError("Volume profile not available until V3")
