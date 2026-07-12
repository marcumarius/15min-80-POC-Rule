from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from data.types import Bar
from features.acceptance import detect_acceptance

ET = ZoneInfo("America/New_York")
_T0 = datetime(2026, 7, 8, 9, 30, tzinfo=ET)


def _bar(i, low, high, volume, close=None):
    if close is None:
        close = (high + low) / 2
    return Bar(ts=_T0 + timedelta(minutes=i), open=close, high=high, low=low, close=close,
               volume=volume, bid_volume=0, ask_volume=0, delta=0)


def _baseline(n=5):
    vols = [50, 45, 55, 48, 52]
    # stays at/below the level (99.5-100.0) -- not "beyond" yet
    return [_bar(i, 99.5, 100.0, vols[i % len(vols)]) for i in range(n)]


def test_detect_acceptance_fires_on_first_bar_beyond_level_with_volume():
    bars = _baseline(5) + [
        _bar(5, 100.5, 101.0, 500),   # fully beyond 100.0, huge volume -> acceptance
        _bar(6, 100.8, 101.2, 500),   # would also qualify, but not first
    ]
    event = detect_acceptance(bars, level=100.0, direction=1, min_volume_z=2.0, lookback=5)
    assert event is not None
    assert event.index == 5
    assert event.direction == 1


def test_detect_acceptance_ignores_wick_that_does_not_fully_clear_level():
    bars = _baseline(5) + [
        _bar(5, 99.8, 101.0, 500),   # wicks above 100 but low(99.8) <= level -> not "beyond" for the whole bar
    ]
    assert detect_acceptance(bars, level=100.0, direction=1, min_volume_z=2.0, lookback=5) is None


def test_detect_acceptance_ignores_beyond_level_without_volume_buildup():
    bars = _baseline(5) + [
        _bar(5, 100.5, 101.0, 50),   # beyond level, but unremarkable volume -> no acceptance yet
    ]
    assert detect_acceptance(bars, level=100.0, direction=1, min_volume_z=2.0, lookback=5) is None


def test_detect_acceptance_direction_minus_one_checks_below_level():
    bars = _baseline(5) + [
        _bar(5, 98.0, 98.5, 500),   # fully below 99.0, huge volume -> short-side acceptance
    ]
    event = detect_acceptance(bars, level=99.0, direction=-1, min_volume_z=2.0, lookback=5)
    assert event is not None
    assert event.direction == -1


def test_detect_acceptance_invalid_direction_raises():
    import pytest
    with pytest.raises(ValueError):
        detect_acceptance(_baseline(5), level=100.0, direction=0)
