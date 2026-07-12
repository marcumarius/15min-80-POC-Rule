"""FOLLOW/FADE state machine tests -- synthetic bars against a hand-built
snapshot, asserting signals fire on ORDER-FLOW EVENTS and never on bare
price action (the D-007 requirement)."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from data.types import Bar
from signals.engine import generate_signals
from structure.levels import StructuralSnapshot

ET = ZoneInfo("America/New_York")
_T0 = datetime(2026, 7, 8, 9, 30, tzinfo=ET)


def _bar(i, low, high, close, volume=50, delta=0):
    return Bar(ts=_T0 + timedelta(minutes=i), open=close, high=high, low=low, close=close,
               volume=volume, bid_volume=max(0, -delta), ask_volume=max(0, delta), delta=delta)


def _snap(vah=110.0, val=90.0, poc=100.0):
    return StructuralSnapshot(
        trading_date=date(2026, 7, 8),
        pd_va={"poc": poc, "vah": vah, "val": val},
        ib={"high": None, "low": None, "mid": None},
        weekly={"vpoc": None, "pw_high": None, "pw_low": None},
        overnight={"high": None, "low": None},
        prior_day={"open": None, "high": None, "low": None, "close": None},
    )


def _inside_baseline(n, volume=50):
    # rotating quietly inside value (95-105), varied volume for stable z-baseline
    vols = [volume, volume - 5, volume + 5, volume - 2, volume + 2]
    return [_bar(i, 95.0, 105.0, 100.0, volume=vols[i % 5], delta=(-1) ** i * 3) for i in range(n)]


def test_follow_fires_on_acceptance_beyond_vah():
    bars = _inside_baseline(20) + [
        _bar(20, 110.5, 112.0, 111.5, volume=500, delta=200),   # fully above VAH + huge volume = acceptance
    ]
    signals = generate_signals(bars, _snap(), tick_size=0.25)
    follows = [s for s in signals if s.family == "FOLLOW"]
    assert len(follows) == 1
    assert follows[0].direction == 1
    assert follows[0].bar_index == 20
    assert any(type(e).__name__ == "AcceptanceEvent" for e in follows[0].events)


def test_follow_does_not_fire_on_breakout_without_volume():
    bars = _inside_baseline(20) + [
        _bar(20, 110.5, 112.0, 111.5, volume=50, delta=5),   # beyond VAH but NO volume anomaly
        _bar(21, 110.5, 112.5, 112.0, volume=48, delta=5),   # ...and the old engine would have
        _bar(22, 110.5, 113.0, 112.5, volume=52, delta=5),   # fired here on "3 closes above"
    ]
    signals = generate_signals(bars, _snap(), tick_size=0.25)
    assert [s for s in signals if s.family == "FOLLOW"] == []


def test_fade_fires_on_reentry_with_absorption_at_extreme():
    bars = _inside_baseline(20) + [
        _bar(20, 110.5, 112.0, 111.5, volume=60, delta=30),    # excursion above VAH
        _bar(21, 111.8, 112.2, 112.0, volume=400, delta=350),  # heavy buying, price stalls -> bearish absorption
        _bar(22, 104.0, 111.0, 105.0, volume=80, delta=-40),   # re-entry into value -> FADE short
    ]
    signals = generate_signals(bars, _snap(), tick_size=0.25)
    fades = [s for s in signals if s.family == "FADE"]
    assert len(fades) == 1
    assert fades[0].direction == -1
    assert fades[0].bar_index == 22
    assert len(fades[0].events) >= 1


def test_fade_does_not_fire_on_bare_reentry():
    # This is the legacy trigger's exact firing condition -- re-entry with no
    # order-flow failure evidence must NOT fire in the rebuild.
    bars = _inside_baseline(20) + [
        _bar(20, 110.5, 112.0, 111.5, volume=55, delta=10),   # quiet excursion above VAH
        _bar(21, 104.0, 111.0, 105.0, volume=52, delta=-5),   # quiet re-entry ("first close back inside")
    ]
    signals = generate_signals(bars, _snap(), tick_size=0.25)
    assert [s for s in signals if s.family == "FADE"] == []


def test_no_signals_when_price_never_leaves_value():
    signals = generate_signals(_inside_baseline(30), _snap(), tick_size=0.25)
    assert signals == []


def test_signal_why_is_traceable():
    bars = _inside_baseline(20) + [
        _bar(20, 110.5, 112.0, 111.5, volume=500, delta=200),
    ]
    signals = generate_signals(bars, _snap(), tick_size=0.25)
    assert len(signals) == 1
    why = signals[0].why()
    assert "FOLLOW" in why and "Acceptance" in why   # the event NAME is in the rationale


def test_missing_value_area_returns_no_signals():
    snap = _snap()
    snap.pd_va = {"poc": None, "vah": None, "val": None}
    bars = _inside_baseline(10)
    assert generate_signals(bars, snap, tick_size=0.25) == []
