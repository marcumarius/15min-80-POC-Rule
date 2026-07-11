import struct
from datetime import datetime, timedelta, timezone

import pytest

from data.loaders import (
    _scdatetime_to_et,
    classify_aggressor,
    load_footprint,
    load_ticks,
    ticks_to_footprint,
)
from data.types import Tick


def test_classify_aggressor_buy_sell_unknown():
    assert classify_aggressor(price=101.0, bid=100.75, ask=101.0) == "buy"
    assert classify_aggressor(price=100.75, bid=100.75, ask=101.0) == "sell"
    assert classify_aggressor(price=100.85, bid=100.75, ask=101.0) == "unknown"


def test_load_ticks_rithmic_csv_dedupes_and_sorts(tmp_path):
    p = tmp_path / "ticks.csv"
    p.write_text(
        "Date,Time,Price,Volume,Bid,Ask\n"
        "2026-07-09,09:30:00,100.25,3,100.00,100.25\n"
        "2026-07-09,09:30:01,100.00,2,100.00,100.25\n"
        "2026-07-09,09:30:00,100.25,3,100.00,100.25\n"  # exact duplicate of row 1
    )
    ticks = list(load_ticks(p))
    assert len(ticks) == 2
    assert ticks[0].ts < ticks[1].ts
    assert ticks[0].aggressor == "buy"   # price == ask
    assert ticks[1].aggressor == "sell"  # price == bid


def test_load_ticks_unrecognized_extension_raises(tmp_path):
    p = tmp_path / "ticks.xyz"
    p.write_text("nonsense")
    with pytest.raises(ValueError):
        load_ticks(p)


def test_scdatetime_epoch_roundtrip():
    # 2 days after the OLE epoch (1899-12-30 UTC) == 1900-01-01 UTC.
    et = _scdatetime_to_et(2.0)
    assert et.astimezone(timezone.utc).date().isoformat() == "1900-01-01"


def test_load_scid_ticks_parser_mechanics(tmp_path):
    """Round-trips a hand-built .scid file against the documented
    s_IntradayFileHeader/s_IntradayRecord layout. This validates the
    parser's own logic, NOT that the layout matches a real Sierra Chart
    export -- no sample file exists to check that against (see the
    UNVALIDATED warning in data/loaders.py's module docstring)."""
    header_size = 56
    header = struct.pack("<I", header_size) + b"\x00" * (header_size - 4)
    epoch = datetime(1899, 12, 30, tzinfo=timezone.utc)
    ts = datetime(2026, 7, 9, 13, 30, 0, tzinfo=timezone.utc)
    raw_dt = (ts - epoch).total_seconds() / 86400.0
    # datetime, O, H, L, C, NumTrades, TotalVolume, BidVolume, AskVolume
    record = struct.pack("<dffffIIII", raw_dt, 100.25, 100.25, 100.25, 100.25, 1, 3, 0, 3)
    p = tmp_path / "sample.scid"
    p.write_bytes(header + record)

    ticks = list(load_ticks(p))
    assert len(ticks) == 1
    assert ticks[0].price == pytest.approx(100.25)
    assert ticks[0].volume == 3
    assert ticks[0].aggressor == "buy"  # AskVolume(3) > BidVolume(0)


def test_load_footprint_csv_sorted_by_ts_then_price(tmp_path):
    p = tmp_path / "footprint.csv"
    p.write_text(
        "ts_bucket,price,bid_volume,ask_volume\n"
        "2026-07-09T09:30:00,100.25,3,5\n"
        "2026-07-09T09:30:00,100.00,2,1\n"
    )
    cells = list(load_footprint(p))
    assert [c.price for c in cells] == [100.00, 100.25]


def test_load_footprint_depth_not_implemented(tmp_path):
    p = tmp_path / "sample.depth"
    p.write_bytes(b"\x00")
    with pytest.raises(NotImplementedError):
        load_footprint(p)


def test_ticks_to_footprint_splits_by_aggressor_and_drops_unknown():
    tz = timezone(timedelta(hours=-4))
    ticks = [
        Tick(ts=datetime(2026, 7, 9, 9, 30, 0, tzinfo=tz), price=100.25, volume=5, aggressor="buy"),
        Tick(ts=datetime(2026, 7, 9, 9, 30, 5, tzinfo=tz), price=100.25, volume=3, aggressor="sell"),
        Tick(ts=datetime(2026, 7, 9, 9, 30, 10, tzinfo=tz), price=100.25, volume=100, aggressor="unknown"),
    ]
    cells = list(ticks_to_footprint(ticks, tick_size=0.25, bucket_seconds=1800))
    assert len(cells) == 1
    assert cells[0].ask_volume == 5
    assert cells[0].bid_volume == 3
