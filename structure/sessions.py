"""Session & trading-day logic (ET, DST-aware). 18:00 ET futures boundary.

Phase 1 deliverable (section 3.2). Timezone bugs are silent and catastrophic --
every record is tz-aware ET from ingestion on. All comparisons here use local
wall-clock time() extracted from a tz-aware datetime, so they stay correct
across DST transitions without any manual offset handling.
"""
from datetime import date, datetime, time, timedelta

from config import load_config

_cfg = load_config()


def _parse_hms(hms: str) -> time:
    parts = [int(p) for p in hms.split(":")]
    while len(parts) < 3:
        parts.append(0)
    h, m, s = parts[:3]
    return time(h, m, s)


US_START = _parse_hms(_cfg.structural.session_start)
US_END = _parse_hms(_cfg.structural.session_end)
UK_START = _parse_hms(_cfg.structural.uk_session_start)
UK_END = _parse_hms(_cfg.structural.uk_session_end)
ASIA_START = _parse_hms(_cfg.structural.asia_session_start)
ASIA_END = _parse_hms(_cfg.structural.asia_session_end)
# The futures trading-day boundary is the same event as the daily VWAP anchor
# (the 18:00 ET reopen) -- reuse vwap_reset rather than a second, independently
# driftable 18:00 constant.
DAY_BOUNDARY = _parse_hms(_cfg.structural.vwap_reset)


def trading_day(ts: datetime) -> date:
    """Map a tz-aware ET timestamp to its futures trading day.

    The trading day begins at the 18:00 ET reopen the prior calendar evening,
    so Sunday 18:00+ maps to Monday's trading day.
    """
    d = ts.date()
    if ts.time() >= DAY_BOUNDARY:
        d += timedelta(days=1)
    return d


def session_of(ts: datetime) -> str:
    """Classify a tz-aware ET timestamp into 'asia', 'uk', or 'us'.

    Asia wraps midnight (18:00 -> 03:00). The post-RTH gap between US close
    (16:00) and the Asia reopen (18:00) has no dedicated bucket in the
    3-category contract, so it is folded into 'asia' as the lead-in to the
    next session -- consistent with trading_day() already rolling anything
    from 18:00 into the next trading day.
    """
    t = ts.time()
    if US_START <= t < US_END:
        return "us"
    if UK_START <= t < UK_END:
        return "uk"
    if ASIA_START <= t or t < ASIA_END:
        return "asia"
    return "asia"


def in_rth(ts: datetime) -> bool:
    """True if ts falls within the US regular trading hours window."""
    return US_START <= ts.time() < US_END
