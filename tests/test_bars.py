from datetime import datetime
from zoneinfo import ZoneInfo

from data.bars import ticks_to_bars
from data.types import Tick

ET = ZoneInfo("America/New_York")


def _tick(h, m, s, price, volume, aggressor):
    return Tick(ts=datetime(2026, 7, 8, h, m, s, tzinfo=ET), price=price, volume=volume, aggressor=aggressor)


def test_ticks_to_bars_aggregates_ohlcv_and_delta():
    ticks = [
        _tick(9, 30, 0, 100.0, 5, "buy"),
        _tick(9, 30, 10, 101.0, 3, "buy"),
        _tick(9, 30, 20, 99.5, 4, "sell"),
        _tick(9, 30, 29, 100.5, 2, "sell"),
    ]
    bars = list(ticks_to_bars(ticks, bar_seconds=30))
    assert len(bars) == 1
    b = bars[0]
    assert b.open == 100.0
    assert b.high == 101.0
    assert b.low == 99.5
    assert b.close == 100.5
    assert b.volume == 14
    assert b.ask_volume == 8   # buy volume
    assert b.bid_volume == 6   # sell volume
    assert b.delta == 2        # 8 - 6


def test_ticks_to_bars_splits_by_bucket():
    ticks = [
        _tick(9, 30, 0, 100.0, 1, "buy"),
        _tick(9, 30, 29, 100.0, 1, "buy"),
        _tick(9, 30, 30, 101.0, 1, "sell"),   # next 30s bucket
        _tick(9, 30, 59, 101.0, 1, "sell"),
    ]
    bars = list(ticks_to_bars(ticks, bar_seconds=30))
    assert len(bars) == 2
    assert bars[0].volume == 2 and bars[0].delta == 2
    assert bars[1].volume == 2 and bars[1].delta == -2


def test_ticks_to_bars_unknown_aggressor_in_volume_not_delta():
    ticks = [
        _tick(9, 30, 0, 100.0, 5, "buy"),
        _tick(9, 30, 1, 100.0, 100, "unknown"),
    ]
    bars = list(ticks_to_bars(ticks, bar_seconds=30))
    assert bars[0].volume == 105   # total includes unknown
    assert bars[0].ask_volume == 5
    assert bars[0].bid_volume == 0
    assert bars[0].delta == 5      # unknown volume doesn't inflate delta either side


def test_ticks_to_bars_empty_yields_nothing():
    assert list(ticks_to_bars([], bar_seconds=30)) == []
