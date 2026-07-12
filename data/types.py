"""Data contract shared by every module. Define once, never break silently.

See docs/phase1_foundation_engine.md section 2. All timestamps are tz-aware ET.
Do NOT collapse footprint to OHLC before Phase 3 needs per-price bid/ask volume.
"""
from dataclasses import dataclass
from datetime import datetime, date

@dataclass
class Tick:
    ts: datetime            # tz-aware ET
    price: float
    volume: int
    aggressor: str          # "buy" | "sell" | "unknown"

@dataclass
class FootprintCell:
    ts_bucket: datetime     # ET
    price: float
    bid_volume: int         # traded at bid (sell aggression)
    ask_volume: int         # traded at ask (buy aggression)

@dataclass
class Level:
    name: str
    price: float
    kind: str               # "va" | "ib" | "weekly" | "session" | "vwap" | "overnight_vp"

@dataclass
class Bar:
    """Derived, for context/plotting and order-flow feature input only --
    never a trigger itself (CLAUDE.md D-007). bid_volume/ask_volume are the
    aggressor-classified split feeding absorption/exhaustion/imbalance;
    delta = ask_volume - bid_volume."""
    ts: datetime             # bar start, tz-aware ET
    open: float
    high: float
    low: float
    close: float
    volume: int              # total, including unclassified ("unknown" aggressor) ticks
    bid_volume: int
    ask_volume: int
    delta: int                # ask_volume - bid_volume
