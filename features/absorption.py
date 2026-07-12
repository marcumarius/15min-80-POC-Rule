"""Absorption: passive limit orders soaking up aggressive market orders --
price stalls despite heavy one-sided volume/delta.

Phase 3 deliverable. config order_flow.absorption_vol_z /
absorption_price_stall_ticks.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from config import load_config
from features._stats import rolling_zscore

_cfg = load_config()


@dataclass
class AbsorptionEvent:
    index: int
    ts: datetime
    direction: str    # "bullish" (selling absorbed by buyers) | "bearish" (buying absorbed by sellers)
    price: float
    delta: int
    z_score: float


def detect_absorption(bars: list, tick_size: float, vol_z: Optional[float] = None,
                       stall_ticks: Optional[float] = None, lookback: int = 20) -> list:
    """Flags bars with anomalous one-sided volume (|delta| z-score >= vol_z
    against the trailing `lookback` bars) whose price range still stalled
    (high-low <= stall_ticks * tick_size) -- heavy pressure, no progress,
    the passive side is defending the level."""
    if vol_z is None:
        vol_z = _cfg.order_flow.absorption_vol_z
    if stall_ticks is None:
        stall_ticks = _cfg.order_flow.absorption_price_stall_ticks

    abs_deltas = [abs(b.delta) for b in bars]
    events = []
    for i, b in enumerate(bars):
        z = rolling_zscore(abs_deltas, i, lookback)
        if z < vol_z:
            continue
        if (b.high - b.low) > stall_ticks * tick_size:
            continue
        direction = "bullish" if b.delta < 0 else "bearish"
        events.append(AbsorptionEvent(i, b.ts, direction, b.close, b.delta, z))
    return events
