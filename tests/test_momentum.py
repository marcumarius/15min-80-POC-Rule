"""MOMO pullback/retest state machine tests (MomentumTrade.md L2-L4)."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from data.types import Bar
from signals.momentum import generate_momo_signals
from structure.levels import StructuralSnapshot

ET = ZoneInfo("America/New_York")
_T0 = datetime(2026, 7, 8, 9, 30, tzinfo=ET)


def _bar(i, low, high, close, volume=50, delta=0):
    return Bar(ts=_T0 + timedelta(minutes=i), open=close, high=high, low=low, close=close,
               volume=volume, bid_volume=max(0, -delta), ask_volume=max(0, delta), delta=delta)


def _snap(vah=110.0, val=90.0):
    return StructuralSnapshot(
        trading_date=date(2026, 7, 8), pd_va={"poc": 100.0, "vah": vah, "val": val},
        ib={"high": None, "low": None, "mid": None},
        weekly={"vpoc": None, "pw_high": None, "pw_low": None},
        overnight={"high": None, "low": None},
        prior_day={"open": None, "high": None, "low": None, "close": None})


def _baseline(n=20):
    vols = [50, 45, 55, 48, 52]
    return [_bar(i, 95.0, 105.0, 100.0, volume=vols[i % 5], delta=(-1) ** i * 3) for i in range(n)]


def test_momo_fires_on_break_pullback_resumption():
    bars = _baseline() + [
        _bar(20, 110.5, 114.0, 113.0, volume=500, delta=200),  # acceptance above VAH
        _bar(21, 111.5, 113.5, 112.0, volume=60, delta=10),    # pullback: dips, does NOT extend
        _bar(22, 111.8, 115.5, 115.2, volume=80, delta=40),    # resumption closes above prior high
    ]
    sigs = generate_momo_signals(bars, _snap(), tick_size=0.25)
    assert len(sigs) == 1
    s = sigs[0]
    assert s.direction == 1
    assert s.bar_index == 22
    assert s.stop == 111.5      # the pullback low, NOT the VA edge


def test_momo_no_signal_without_pullback():
    # runaway break that never pulls back -> no entry (the documented tradeoff:
    # the strongest trend days are missed by demanding confirmation).
    # NOTE: each bar's low must stay AT/ABOVE the prior running extreme --
    # the state machine counts ANY intrabar dip below the extreme as a
    # pullback (no minimum depth), a known-loose definition flagged in the
    # interim report.
    bars = _baseline() + [
        _bar(20, 110.5, 114.0, 113.5, volume=500, delta=200),
        _bar(21, 114.0, 117.0, 116.5, volume=90, delta=60),
        _bar(22, 117.0, 120.0, 119.5, volume=95, delta=70),
    ]
    assert generate_momo_signals(bars, _snap(), tick_size=0.25) == []


def test_momo_dead_on_full_reentry_through_edge():
    bars = _baseline() + [
        _bar(20, 110.5, 114.0, 113.0, volume=500, delta=200),  # acceptance
        _bar(21, 104.0, 113.0, 105.0, volume=80, delta=-40),   # closes back inside value
        _bar(22, 111.0, 115.5, 115.2, volume=80, delta=40),    # would-be resumption -- too late
    ]
    assert generate_momo_signals(bars, _snap(), tick_size=0.25) == []


def test_momo_short_side_mirror():
    bars = _baseline() + [
        _bar(20, 86.0, 89.5, 87.0, volume=500, delta=-200),    # acceptance below VAL=90
        _bar(21, 86.5, 88.5, 88.0, volume=60, delta=-10),      # pullback up, does NOT extend low
        _bar(22, 84.5, 88.2, 84.8, volume=80, delta=-40),      # resumption closes below prior low
    ]
    sigs = generate_momo_signals(bars, _snap(), tick_size=0.25)
    assert len(sigs) == 1
    assert sigs[0].direction == -1
    assert sigs[0].stop == 88.5   # pullback high


def test_momo_missing_va_returns_empty():
    snap = _snap()
    snap.pd_va = {"poc": None, "vah": None, "val": None}
    assert generate_momo_signals(_baseline(), snap, tick_size=0.25) == []
