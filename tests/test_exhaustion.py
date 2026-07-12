from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from data.types import Bar
from features.exhaustion import detect_exhaustion

ET = ZoneInfo("America/New_York")
_T0 = datetime(2026, 7, 8, 9, 30, tzinfo=ET)


def _bar(i, delta, high, low, close=None):
    if close is None:
        close = (high + low) / 2
    return Bar(ts=_T0 + timedelta(minutes=i), open=close, high=high, low=low, close=close,
               volume=abs(delta) + 10, bid_volume=0, ask_volume=0, delta=delta)


def _baseline(n=5, base_high=100.0):
    deltas = [5, -3, 4, -2, 3]
    return [_bar(i, deltas[i % len(deltas)], base_high + i * 0.1, base_high + i * 0.1 - 0.5) for i in range(n)]


def test_detect_exhaustion_bearish_climax_fails_to_extend():
    # baseline: highs 100.0-100.4, lows 99.5-99.9 -- climax/confirm bars stay
    # within the baseline's LOW range so only the high side is "new."
    bars = _baseline(5, base_high=100.0) + [
        _bar(5, 200, 105.0, 99.6),   # climax: new high, huge delta, low stays in-range
        _bar(6, 5, 104.5, 100.0),    # confirm: fails to exceed 105.0 -> exhaustion
    ]
    events = detect_exhaustion(bars, climax_z=2.0, lookback=5, confirm_bars=1)
    assert len(events) == 1
    assert events[0].climax_index == 5
    assert events[0].direction == "bearish"
    assert events[0].climax_price == 105.0


def test_detect_exhaustion_no_fire_when_climax_extends():
    bars = _baseline(5, base_high=100.0) + [
        _bar(5, 200, 105.0, 99.6),   # climax: new high, huge delta
        _bar(6, 5, 106.0, 104.0),    # confirm bar EXTENDS beyond 105.0 -> initiative continues, no exhaustion
    ]
    events = detect_exhaustion(bars, climax_z=2.0, lookback=5, confirm_bars=1)
    assert events == []


def test_detect_exhaustion_bullish_climax_fails_to_extend():
    # climax/confirm bars stay within the baseline's HIGH range (<=100.4) so
    # only the low side is "new."
    bars = _baseline(5, base_high=100.0) + [
        _bar(5, -200, 100.3, 94.0),  # climax: new low, huge (negative) delta, high stays in-range
        _bar(6, -5, 99.0, 94.5),     # confirm: fails to undercut 94.0 -> exhaustion
    ]
    events = detect_exhaustion(bars, climax_z=2.0, lookback=5, confirm_bars=1)
    assert len(events) == 1
    assert events[0].direction == "bullish"
    assert events[0].climax_price == 94.0


def test_detect_exhaustion_no_fire_when_volume_not_climactic():
    bars = _baseline(5, base_high=100.0) + [
        _bar(5, 4, 100.6, 99.9),     # new high but unremarkable volume -> not a climax
        _bar(6, 5, 100.5, 100.0),
    ]
    assert detect_exhaustion(bars, climax_z=2.0, lookback=5, confirm_bars=1) == []


def test_detect_exhaustion_insufficient_bars_returns_empty():
    bars = _baseline(3)
    assert detect_exhaustion(bars, climax_z=2.0, lookback=5, confirm_bars=1) == []
