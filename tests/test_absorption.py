from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from data.types import Bar
from features.absorption import detect_absorption

ET = ZoneInfo("America/New_York")
_T0 = datetime(2026, 7, 8, 9, 30, tzinfo=ET)


def _bar(i, delta, high, low, close=None):
    if close is None:
        close = (high + low) / 2
    return Bar(ts=_T0 + timedelta(minutes=i), open=close, high=high, low=low, close=close,
               volume=abs(delta) + 10, bid_volume=0, ask_volume=0, delta=delta)


def _baseline(n=5):
    # small, varied deltas -> a non-degenerate mean/stdev for the z-score baseline
    deltas = [5, -3, 4, -2, 3]
    return [_bar(i, deltas[i % len(deltas)], 100 + i * 0.25, 100 + i * 0.25 - 0.25) for i in range(n)]


def test_detect_absorption_flags_heavy_delta_with_price_stall():
    bars = _baseline(5) + [
        _bar(5, 200, 100.25, 100.0),  # heavy buying, tiny range -> stalled -> bearish absorption
    ]
    events = detect_absorption(bars, tick_size=0.25, vol_z=2.0, stall_ticks=3, lookback=5)
    assert len(events) == 1
    assert events[0].index == 5
    assert events[0].direction == "bearish"   # heavy buying absorbed by sellers


def test_detect_absorption_bullish_direction_on_heavy_selling():
    bars = _baseline(5) + [
        _bar(5, -200, 100.25, 100.0),  # heavy selling, tiny range -> stalled -> bullish absorption
    ]
    events = detect_absorption(bars, tick_size=0.25, vol_z=2.0, stall_ticks=3, lookback=5)
    assert len(events) == 1
    assert events[0].direction == "bullish"   # heavy selling absorbed by buyers


def test_detect_absorption_no_flag_when_price_actually_moves():
    bars = _baseline(5) + [
        _bar(5, 200, 110.0, 100.0),  # heavy buying, but a real 40-tick range -> not a stall
    ]
    events = detect_absorption(bars, tick_size=0.25, vol_z=2.0, stall_ticks=3, lookback=5)
    assert events == []


def test_detect_absorption_no_flag_when_volume_not_anomalous():
    bars = _baseline(5) + [
        _bar(5, 4, 100.25, 100.0),  # in line with baseline, no anomaly
    ]
    events = detect_absorption(bars, tick_size=0.25, vol_z=2.0, stall_ticks=3, lookback=5)
    assert events == []
