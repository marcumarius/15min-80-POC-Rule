"""Exhaustion: climactic volume/delta that fails to extend -- initiative
fires, then dries up right after a blow-off.

Phase 3 deliverable. config order_flow.exhaustion_climax_z.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from config import load_config
from features._stats import rolling_zscore

_cfg = load_config()


@dataclass
class ExhaustionEvent:
    climax_index: int
    confirm_index: int
    ts: datetime               # confirmation bar's timestamp
    direction: str              # "bearish" (up-climax fails to extend) | "bullish" (mirror)
    climax_price: float
    z_score: float


def detect_exhaustion(bars: list, climax_z: Optional[float] = None,
                       lookback: int = 20, confirm_bars: int = 1) -> list:
    """A bar is a climax if it makes a new `lookback`-bar high/low AND its
    |delta| z-score against the trailing window is >= climax_z. Exhaustion
    confirms if the next `confirm_bars` bar(s) fail to extend beyond the
    climax bar's extreme -- initiative fired, then died, rather than
    continuing (which would be FOLLOW's job to catch, not this)."""
    if climax_z is None:
        climax_z = _cfg.order_flow.exhaustion_climax_z
    if len(bars) < lookback + 1 + confirm_bars:
        return []

    abs_deltas = [abs(b.delta) for b in bars]
    events = []
    for i in range(lookback, len(bars) - confirm_bars):
        window = bars[i - lookback:i]
        b = bars[i]
        z = rolling_zscore(abs_deltas, i, lookback)
        if z < climax_z:
            continue

        confirm = bars[i + 1:i + 1 + confirm_bars]
        is_up_climax = b.high > max(w.high for w in window)
        is_dn_climax = b.low < min(w.low for w in window)

        if is_up_climax and all(c.high <= b.high for c in confirm):
            events.append(ExhaustionEvent(i, i + confirm_bars, confirm[-1].ts, "bearish", b.high, z))
        if is_dn_climax and all(c.low >= b.low for c in confirm):
            events.append(ExhaustionEvent(i, i + confirm_bars, confirm[-1].ts, "bullish", b.low, z))
    return events
