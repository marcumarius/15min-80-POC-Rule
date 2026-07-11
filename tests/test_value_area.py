from datetime import datetime, timezone

import pytest

from data.types import FootprintCell
from structure.value_area import value_area, value_area_from_footprint, volume_at_price


def test_value_area_known_asymmetric_distribution():
    vap = {100: 10, 101: 20, 102: 50, 103: 15, 104: 5}
    result = value_area(vap, tick_size=1.0, va_percent=0.70)
    assert result == {"poc": 102.0, "vah": 102.0, "val": 101.0}


def test_value_area_tie_break_favors_up_on_expansion():
    vap = {100: 5, 101: 20, 102: 50, 103: 20, 104: 5}
    result = value_area(vap, tick_size=1.0, va_percent=0.70)
    # acc=50 at POC(102); up(20) vs dn(20) tie -> expand up first, matching
    # the legacy ComputeProfile tie-break (upVol >= dnVol takes up).
    assert result == {"poc": 102.0, "vah": 103.0, "val": 102.0}


def test_value_area_poc_tie_break_favors_lower_price():
    vap = {100: 50, 101: 50, 102: 10}
    result = value_area(vap, tick_size=1.0, va_percent=1.0)
    assert result["poc"] == 100.0  # ascending scan: first strict max wins ties


def test_value_area_empty_map_returns_none_fields():
    assert value_area({}, tick_size=1.0) == {"poc": None, "vah": None, "val": None}


def test_value_area_invalid_tick_size_returns_none_fields():
    assert value_area({100: 10}, tick_size=0.0) == {"poc": None, "vah": None, "val": None}


def test_volume_at_price_aggregates_bid_and_ask_across_cells():
    ts = datetime(2026, 7, 9, tzinfo=timezone.utc)
    cells = [
        FootprintCell(ts_bucket=ts, price=100.25, bid_volume=3, ask_volume=4),
        FootprintCell(ts_bucket=ts, price=100.25, bid_volume=1, ask_volume=2),
        FootprintCell(ts_bucket=ts, price=100.50, bid_volume=5, ask_volume=5),
    ]
    vap = volume_at_price(cells, tick_size=0.25)
    assert vap[round(100.25 / 0.25)] == 10
    assert vap[round(100.50 / 0.25)] == 10


def test_value_area_from_footprint_end_to_end():
    ts = datetime(2026, 7, 9, tzinfo=timezone.utc)
    cells = [
        FootprintCell(ts_bucket=ts, price=100.0, bid_volume=5, ask_volume=5),
        FootprintCell(ts_bucket=ts, price=101.0, bid_volume=10, ask_volume=10),
        FootprintCell(ts_bucket=ts, price=102.0, bid_volume=25, ask_volume=25),
    ]
    result = value_area_from_footprint(cells, tick_size=1.0, va_percent=0.70)
    assert result["poc"] == 102.0
