from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from backtest.outcome import simulate_trade
from data.types import Bar
from signals.engine import Signal

ET = ZoneInfo("America/New_York")
_T0 = datetime(2026, 7, 8, 9, 30, tzinfo=ET)


def _bar(i, low, high, close):
    return Bar(ts=_T0 + timedelta(minutes=i), open=close, high=high, low=low, close=close,
               volume=100, bid_volume=0, ask_volume=0, delta=0)


def _long_signal(bar_index, price, level):
    return Signal("FOLLOW", 1, _T0 + timedelta(minutes=bar_index), bar_index, price, level)


def test_full_stop_out_loses_about_one_r():
    # entry ~100 (+1 tick slip), min-stop floor 15pts -> stop 85.25-ish, then a crash bar
    bars = [_bar(0, 99, 101, 100.0), _bar(1, 80.0, 100.5, 81.0)]
    tr = simulate_trade(_long_signal(0, 100.0, 99.0), bars, atr=100.0, tick_size=0.25)
    assert tr.scaled is False
    assert tr.r < -1.0                # -1R minus stop slippage and commission
    assert tr.r == pytest.approx(-1.09, abs=0.05)


def test_scale_at_tgt1_then_eod_flat_is_positive():
    # rallies through tgt1 (entry+1.5R) and holds to EOD near the high
    bars = [_bar(0, 99, 101, 100.0)] + [_bar(i, 100 + 3 * i, 102 + 3 * i, 101 + 3 * i) for i in range(1, 12)]
    tr = simulate_trade(_long_signal(0, 100.0, 99.0), bars, atr=100.0, tick_size=0.25)
    assert tr.scaled is True
    assert tr.r > 1.0                 # half banked at 1.5R + runner gain


def test_scale_then_breakeven_stop_keeps_banked_half():
    # hits tgt1 then collapses back through breakeven -> keep ~0.75R minus costs.
    # bar1 CLOSES back near entry so the ATR trail (close - 0.10*ATR) stays
    # below breakeven and the runner exits at BE, not a ratcheted trail.
    bars = [_bar(0, 99, 101, 100.0),
            _bar(1, 100.0, 125.0, 101.0),   # tgt1 (entry+1.5R = ~122.75) tagged, closes weak
            _bar(2, 90.0, 101.0, 91.0)]     # crash through breakeven
    tr = simulate_trade(_long_signal(0, 100.0, 99.0), bars, atr=100.0, tick_size=0.25)
    assert tr.scaled is True
    assert 0.2 < tr.r < 0.8           # banked half minus runner BE-stop slippage and commission


def test_pessimistic_same_bar_stop_before_target():
    # one bar touches BOTH stop and tgt1 -> stop assumed first, full loss
    bars = [_bar(0, 99, 101, 100.0), _bar(1, 80.0, 130.0, 120.0)]
    tr = simulate_trade(_long_signal(0, 100.0, 99.0), bars, atr=100.0, tick_size=0.25)
    assert tr.scaled is False
    assert tr.r < -1.0
