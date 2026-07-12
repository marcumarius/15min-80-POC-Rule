from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from data.types import Bar
from features.delta import cumulative_delta, detect_divergence

ET = ZoneInfo("America/New_York")
_T0 = datetime(2026, 7, 8, 9, 30, tzinfo=ET)


def _bar(i, o, h, l, c, delta):
    return Bar(ts=_T0 + timedelta(minutes=i), open=o, high=h, low=l, close=c,
               volume=abs(delta) + 10, bid_volume=0, ask_volume=0, delta=delta)


def test_cumulative_delta_running_sum():
    bars = [_bar(0, 100, 101, 99, 100, 10), _bar(1, 100, 102, 99, 101, -5), _bar(2, 101, 103, 100, 102, 20)]
    assert cumulative_delta(bars) == [10, 5, 25]


def test_detect_divergence_bearish_new_high_cvd_flat():
    bars = [
        _bar(0, 100, 100, 99, 100, 10),
        _bar(1, 100, 101, 99, 101, 10),
        _bar(2, 101, 102, 100, 102, 10),
        _bar(3, 102, 103, 101, 102, 0),   # new high (103 > 102) but delta flat -> cvd doesn't confirm
    ]
    events = detect_divergence(bars, lookback=3)
    assert len(events) == 1
    assert events[0].direction == "bearish"
    assert events[0].index == 3
    assert events[0].price == 103


def test_detect_divergence_no_fire_when_cvd_confirms():
    bars = [
        _bar(0, 100, 100, 99, 100, 10),
        _bar(1, 100, 101, 99, 101, 10),
        _bar(2, 101, 102, 100, 102, 10),
        _bar(3, 102, 103, 101, 102, 15),  # new high AND cvd makes a new high too -> confirmed, no divergence
    ]
    assert detect_divergence(bars, lookback=3) == []


def test_detect_divergence_bullish_new_low_cvd_flat():
    bars = [
        _bar(0, 100, 101, 100, 100, -10),
        _bar(1, 99, 100, 99, 99, -10),
        _bar(2, 98, 99, 98, 98, -10),
        _bar(3, 97, 98, 97, 97, 0),   # new low (97 < 98) but delta flat -> cvd doesn't confirm
    ]
    events = detect_divergence(bars, lookback=3)
    assert len(events) == 1
    assert events[0].direction == "bullish"
    assert events[0].price == 97


def test_detect_divergence_insufficient_bars_returns_empty():
    bars = [_bar(0, 100, 101, 99, 100, 10), _bar(1, 100, 102, 99, 101, 10)]
    assert detect_divergence(bars, lookback=3) == []
