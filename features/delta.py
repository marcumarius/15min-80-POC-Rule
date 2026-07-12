"""Delta / CVD (cumulative volume delta) and price-vs-delta divergence.

Phase 3 deliverable. Session-anchored: caller passes only the bars within
one CVD-anchored session (config order_flow.cvd_reset, matches the VWAP
anchor) -- this module does no session filtering itself, same convention as
structure/levels.py::session_profile_from_ticks().
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from config import load_config
from data.types import Bar

_cfg = load_config()


def cumulative_delta(bars: list) -> list:
    """Running sum of bar.delta across the given bars (session-anchored by
    the caller). cvd[i] is the cumulative delta AT and INCLUDING bar i."""
    cvd = []
    running = 0
    for b in bars:
        running += b.delta
        cvd.append(running)
    return cvd


@dataclass
class DivergenceEvent:
    index: int
    ts: datetime
    direction: str    # "bearish" (price new high, CVD fails to confirm) | "bullish" (mirror)
    price: float
    cvd: float


def detect_divergence(bars: list, lookback: Optional[int] = None) -> list:
    """Price makes a new `lookback`-bar extreme while CVD does not confirm
    (doesn't also make a new extreme over the same window) -- D-005/CLAUDE.md
    §1.3's "delta/CVD divergence" trigger. Returns one DivergenceEvent per
    bar where this fires; a bar can fire both directions in principle (not
    in practice, since a bar can't be both a new high and a new low unless
    lookback is tiny) so both checks always run independently.
    """
    if lookback is None:
        lookback = _cfg.order_flow.delta_div_lookback
    if len(bars) <= lookback:
        return []

    cvd = cumulative_delta(bars)
    events = []
    for i in range(lookback, len(bars)):
        window = bars[i - lookback:i]
        window_cvd = cvd[i - lookback:i]
        cur = bars[i]

        if cur.high > max(b.high for b in window) and cvd[i] <= max(window_cvd):
            events.append(DivergenceEvent(i, cur.ts, "bearish", cur.high, cvd[i]))
        if cur.low < min(b.low for b in window) and cvd[i] >= min(window_cvd):
            events.append(DivergenceEvent(i, cur.ts, "bullish", cur.low, cvd[i]))

    return events
