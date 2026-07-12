import struct
from datetime import date, datetime, timedelta, timezone

import pytest

from data.loaders import (
    _scdatetime_to_et,
    classify_aggressor,
    iter_scid_ticks_for_day,
    load_footprint,
    load_ticks,
    ticks_to_footprint,
)
from data.types import Tick

_MICROS_PER_DAY = 86_400_000_000


def _make_scid_bytes(records: list) -> bytes:
    """records: list of (raw_dt_micros, close_raw, num_trades, total_vol, bid_vol, ask_vol)."""
    header = b"SCID" + struct.pack("<II", 56, 40) + b"\x00" * (56 - 12)
    body = b"".join(
        struct.pack("<qffffIIII", raw_dt, 0.0, close, close, close, num_tr, vol, bid, ask)
        for raw_dt, close, num_tr, vol, bid, ask in records
    )
    return header + body


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
    et = _scdatetime_to_et(2 * _MICROS_PER_DAY)
    assert et.astimezone(timezone.utc).date().isoformat() == "1900-01-01"


def test_load_scid_ticks_parser_mechanics(tmp_path):
    """Round-trips a hand-built .scid file against the VALIDATED format
    (see data/loaders.py module docstring): 4-byte "SCID" magic + HeaderSize/
    RecordSize fields, int64-microsecond datetime, price scaled by
    meta.scid_price_scale (0.01)."""
    epoch = datetime(1899, 12, 30, tzinfo=timezone.utc)
    ts = datetime(2026, 7, 9, 13, 30, 0, tzinfo=timezone.utc)
    raw_dt = int((ts - epoch).total_seconds() * 1_000_000)
    real_price = 100.25
    raw_close = real_price / 0.01  # inverse of meta.scid_price_scale
    p = tmp_path / "sample.scid"
    p.write_bytes(_make_scid_bytes([(raw_dt, raw_close, 1, 3, 0, 3)]))

    ticks = list(load_ticks(p))
    assert len(ticks) == 1
    assert ticks[0].price == pytest.approx(100.25)
    assert ticks[0].volume == 3
    assert ticks[0].aggressor == "buy"  # AskVolume(3) > BidVolume(0)


def test_load_scid_ticks_rejects_bad_magic(tmp_path):
    p = tmp_path / "notscid.scid"
    p.write_bytes(b"XXXX" + struct.pack("<II", 56, 40) + b"\x00" * 44)
    with pytest.raises(ValueError, match="magic"):
        list(load_ticks(p))


def test_load_scid_ticks_real_record_regression():
    """Golden-record regression test: these are the exact 40 bytes of the
    FIRST record in the user's real MNQU6.CME.scid file (2026-07-11 byte-
    level validation session -- see docs/phase1_report.md). Locks in the
    corrected format so a future refactor can't silently reintroduce the
    magic-header or datetime-type bugs this session found and fixed."""
    from data.loaders import _record_to_tick

    real_bytes = bytes.fromhex(
        "e80dd70d222c0e0000000000e0b43a4accaf3a4ae0b43a4a01000000010000000000000001000000"
    )
    assert len(real_bytes) == 40
    tick = _record_to_tick(real_bytes, price_scale=0.01)
    assert tick.ts == datetime(2026, 5, 29, 0, 0, 46, 657000, tzinfo=timezone.utc).astimezone(
        tick.ts.tzinfo
    )
    assert tick.price == pytest.approx(30590.00)
    assert tick.volume == 1
    assert tick.aggressor == "buy"  # AskVolume=1, BidVolume=0 in the real record


def test_iter_scid_ticks_for_day_isolates_target_date(tmp_path):
    epoch = datetime(1899, 12, 30, tzinfo=timezone.utc)

    def micros(y, m, d, h, mi, s):
        return int((datetime(y, m, d, h, mi, s, tzinfo=timezone.utc) - epoch).total_seconds() * 1_000_000)

    # 3 UTC days of records; ET is UTC-4/5 so day boundaries shift slightly,
    # but each record here sits well inside its ET day regardless of offset.
    records = [
        (micros(2026, 7, 8, 14, 0, 0), 100.00 / 0.01, 1, 1, 0, 1),
        (micros(2026, 7, 8, 15, 0, 0), 100.25 / 0.01, 1, 1, 0, 1),
        (micros(2026, 7, 9, 14, 0, 0), 101.00 / 0.01, 1, 2, 2, 0),
        (micros(2026, 7, 9, 15, 0, 0), 101.25 / 0.01, 1, 1, 1, 0),
        (micros(2026, 7, 9, 16, 0, 0), 101.50 / 0.01, 1, 1, 0, 1),
        (micros(2026, 7, 10, 14, 0, 0), 102.00 / 0.01, 1, 1, 0, 1),
    ]
    p = tmp_path / "multi_day.scid"
    p.write_bytes(_make_scid_bytes(records))

    ticks = iter_scid_ticks_for_day(p, date(2026, 7, 9), price_scale=0.01)
    assert len(ticks) == 3
    assert [t.price for t in ticks] == pytest.approx([101.00, 101.25, 101.50])
    assert all(t.ts.date() == date(2026, 7, 9) for t in ticks)


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
