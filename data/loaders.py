"""Tick/footprint ingestion (Rithmic exports, Sierra .scid/.depth).

Phase 1 deliverable (docs/phase1_foundation_engine.md section 3.1).
ET-align, deduplicate, sort; DST-safe; preserve per-price bid/ask volume.

VALIDATED 2026-07-11 against the user's real MNQU6.CME.scid file (byte-level
inspection, see docs/phase1_report.md). Two assumptions in an earlier draft
of this parser were WRONG and are fixed here:

1. There is a 4-byte "SCID" magic signature before the header fields --
   HeaderSize is NOT the first 4 bytes of the file, it's the next 4 (the
   original code read the magic bytes as an int and got a nonsense
   "header size" of over a billion).
2. The per-record DateTime field is an **int64 of microseconds** since
   1899-12-30 00:00:00 UTC, not an 8-byte double of days. Reading it as a
   double produced a denormalized near-zero value; the int64 interpretation
   produces clean, monotonically increasing, sub-second-resolution
   timestamps that match real trading hours.
3. Price is stored scaled: raw_float / 100.0 == real price. Confirmed by
   consecutive Close diffs in real data always being exact multiples of 25
   raw units, i.e. exact multiples of MNQ's 0.25 tick size once divided by
   100 -- see `meta.scid_price_scale` in config/params.yaml.
"""
import csv
import os
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator, Optional
from zoneinfo import ZoneInfo

from data.types import FootprintCell, Tick

_ET = ZoneInfo("America/New_York")
_SCDATETIME_EPOCH = datetime(1899, 12, 30, tzinfo=timezone.utc)  # OLE Automation date epoch

_SCID_MAGIC = b"SCID"
# datetime(int64 microseconds), O,H,L,C(float32), NumTrades,TotalVolume,BidVolume,AskVolume(uint32)
_SCID_RECORD_FMT = "<qffffIIII"
_SCID_RECORD_SIZE = struct.calcsize(_SCID_RECORD_FMT)


def _scdatetime_to_et(raw_micros: int) -> datetime:
    """SCDateTime (int64 microseconds since 1899-12-30 UTC) -> tz-aware ET."""
    utc_dt = _SCDATETIME_EPOCH + timedelta(microseconds=raw_micros)
    return utc_dt.astimezone(_ET)


def _read_scid_header(f) -> tuple:
    """Read and validate the s_IntradayFileHeader; returns (header_size, record_size)."""
    magic = f.read(4)
    if magic != _SCID_MAGIC:
        raise ValueError(f"not a .scid file (expected {_SCID_MAGIC!r} magic, got {magic!r})")
    header_size, record_size = struct.unpack("<II", f.read(8))
    if record_size != _SCID_RECORD_SIZE:
        raise ValueError(f"unexpected .scid record size {record_size} (expected {_SCID_RECORD_SIZE})")
    return header_size, record_size


def classify_aggressor(price: float, bid: float, ask: float) -> str:
    """Standard tick rule: trade at/above the ask is buy-initiated, at/below
    the bid is sell-initiated, otherwise unknown (traded inside the spread
    or no quote context available)."""
    if ask and price >= ask:
        return "buy"
    if bid and price <= bid:
        return "sell"
    return "unknown"


def _dedupe_sort(ticks: list) -> list:
    seen = set()
    out = []
    for t in sorted(ticks, key=lambda t: t.ts):
        key = (t.ts, t.price, t.volume)
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def _price_scale() -> float:
    from config import load_config
    return load_config().meta.scid_price_scale


def _record_to_tick(chunk: bytes, price_scale: float) -> Tick:
    raw_dt, _o, _h, _l, close, _num_trades, total_vol, bid_vol, ask_vol = \
        struct.unpack(_SCID_RECORD_FMT, chunk)
    ts = _scdatetime_to_et(raw_dt)
    # NumTrades/O/H/L are unreliable for per-trade records in real exports
    # (Open is frequently 0 or uninitialized garbage) -- Close is the trade
    # price and BidVolume/AskVolume already encode the aggressor side.
    if ask_vol >= bid_vol:
        aggressor = "buy" if ask_vol > 0 else "unknown"
    else:
        aggressor = "sell" if bid_vol > 0 else "unknown"
    return Tick(ts=ts, price=close * price_scale, volume=total_vol, aggressor=aggressor)


def _load_scid_ticks(path: Path) -> list:
    """Parse an ENTIRE Sierra Chart .scid file into Ticks.

    Only safe for small files -- this buffers every record as a Tick object
    in memory. A single actively-traded futures contract can be tens of
    millions of records (e.g. ~51M for the MNQU6 contract this was validated
    against); for anything that size use iter_scid_ticks_for_day() instead,
    which binary-searches to the target day instead of reading the whole file.
    """
    price_scale = _price_scale()
    ticks = []
    with open(path, "rb") as f:
        header_size, record_size = _read_scid_header(f)
        f.seek(header_size)
        while True:
            chunk = f.read(record_size)
            if len(chunk) < record_size:
                break
            ticks.append(_record_to_tick(chunk, price_scale))
    return _dedupe_sort(ticks)


def _record_ts_at(f, header_size: int, record_size: int, idx: int) -> datetime:
    f.seek(header_size + idx * record_size)
    raw_micros = struct.unpack("<q", f.read(8))[0]
    return _scdatetime_to_et(raw_micros)


def _bisect_day_start(f, header_size: int, record_size: int, n_records: int, target_date) -> int:
    """First record index whose ET date is >= target_date (records are
    append-only / time-sorted, so this is a valid binary search)."""
    lo, hi = 0, n_records
    while lo < hi:
        mid = (lo + hi) // 2
        if _record_ts_at(f, header_size, record_size, mid).date() < target_date:
            lo = mid + 1
        else:
            hi = mid
    return lo


def iter_scid_ticks_for_day(path, target_date, price_scale: Optional[float] = None) -> list:
    """Extract just one ET calendar date's ticks from a large .scid file.

    Binary-searches the (time-sorted) record array for the day's start/end
    byte offsets instead of reading the whole file -- the only practical way
    to pull a single day out of a multi-GB, tens-of-millions-of-records
    contract file. Returns a deduplicated, time-sorted list (safe to buffer
    for a single day's volume; do not use this pattern across a multi-month
    range without re-adding true streaming).
    """
    if price_scale is None:
        price_scale = _price_scale()
    with open(path, "rb") as f:
        header_size, record_size = _read_scid_header(f)
        n_records = (os.path.getsize(path) - header_size) // record_size

        start_idx = _bisect_day_start(f, header_size, record_size, n_records, target_date)
        end_idx = _bisect_day_start(f, header_size, record_size, n_records,
                                     target_date + timedelta(days=1))

        f.seek(header_size + start_idx * record_size)
        ticks = []
        for _ in range(end_idx - start_idx):
            chunk = f.read(record_size)
            if len(chunk) < record_size:
                break
            ticks.append(_record_to_tick(chunk, price_scale))
    return _dedupe_sort(ticks)


def _load_rithmic_csv_ticks(path: Path, tz: ZoneInfo = _ET) -> list:
    """Parse a Rithmic tick export CSV. Expected columns (case-insensitive):
    Date, Time, Price, Volume, and optionally Bid/Ask (for classify_aggressor)
    or an explicit Aggressor/Side column. Adjust column names here once a
    real export's header is available -- this schema is a best guess, not
    verified against a live Rithmic file."""
    ticks = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        cols = {c.lower(): c for c in reader.fieldnames or []}

        def col(*names):
            for n in names:
                if n in cols:
                    return cols[n]
            return None

        c_ts = col("timestamp", "datetime")
        c_date, c_time = col("date"), col("time")
        c_price = col("price", "last")
        c_vol = col("volume", "size")
        c_bid, c_ask = col("bid"), col("ask")
        c_side = col("aggressor", "side")

        for row in reader:
            if c_ts:
                ts = datetime.fromisoformat(row[c_ts])
            else:
                ts = datetime.fromisoformat(f"{row[c_date]} {row[c_time]}")
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=tz)
            else:
                ts = ts.astimezone(tz)
            price = float(row[c_price])
            volume = int(float(row[c_vol]))
            if c_side:
                aggressor = row[c_side].strip().lower()
                aggressor = {"b": "buy", "s": "sell"}.get(aggressor, aggressor)
                if aggressor not in ("buy", "sell"):
                    aggressor = "unknown"
            elif c_bid and c_ask:
                aggressor = classify_aggressor(price, float(row[c_bid]), float(row[c_ask]))
            else:
                aggressor = "unknown"
            ticks.append(Tick(ts=ts, price=price, volume=volume, aggressor=aggressor))
    return _dedupe_sort(ticks)


def load_ticks(path) -> Iterable[Tick]:
    """Load ticks from a Sierra .scid file or a Rithmic CSV export,
    dispatching on file extension. Returns ET-aligned, deduplicated,
    time-sorted Ticks."""
    path = Path(path)
    if path.suffix.lower() == ".scid":
        return _load_scid_ticks(path)
    if path.suffix.lower() in (".csv", ".txt"):
        return _load_rithmic_csv_ticks(path)
    raise ValueError(f"load_ticks: unrecognized extension {path.suffix!r} for {path}")


def _load_footprint_csv(path: Path, tz: ZoneInfo = _ET) -> list:
    """Parse a bar-level footprint export CSV with columns: ts_bucket, price,
    bid_volume, ask_volume (case-insensitive). This is the intermediate
    format for a manually exported or pre-aggregated footprint; it does not
    attempt to parse Sierra's raw .depth market-depth files (see
    load_footprint's docstring)."""
    cells = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        cols = {c.lower(): c for c in reader.fieldnames or []}
        c_ts = cols.get("ts_bucket") or cols.get("timestamp")
        c_price = cols["price"]
        c_bid = cols["bid_volume"]
        c_ask = cols["ask_volume"]
        for row in reader:
            ts = datetime.fromisoformat(row[c_ts])
            ts = ts.replace(tzinfo=tz) if ts.tzinfo is None else ts.astimezone(tz)
            cells.append(FootprintCell(
                ts_bucket=ts,
                price=float(row[c_price]),
                bid_volume=int(float(row[c_bid])),
                ask_volume=int(float(row[c_ask])),
            ))
    return sorted(cells, key=lambda c: (c.ts_bucket, c.price))


def load_footprint(path) -> Iterable[FootprintCell]:
    """Load footprint cells (per-price bid/ask volume), preserving per-price
    granularity -- do NOT collapse to OHLC before Phase 3 needs it.

    Supports a bar-level CSV export (ts_bucket, price, bid_volume,
    ask_volume). Sierra's raw .depth market-depth format is NOT implemented:
    it has no single stable, publicly documented byte layout across Sierra
    versions, and guessing one would risk silently wrong footprint data --
    worse than refusing. Export footprint to CSV from Sierra (or build it
    from .scid ticks via classify_aggressor + price binning) until a real
    .depth sample is available to reverse-engineer against.
    """
    path = Path(path)
    if path.suffix.lower() in (".csv", ".txt"):
        return _load_footprint_csv(path)
    if path.suffix.lower() == ".depth":
        raise NotImplementedError(
            ".depth binary parsing is not implemented -- no documented format "
            "and no sample file to validate against. Export footprint to CSV, "
            "or derive it from .scid ticks (see ticks_to_footprint())."
        )
    raise ValueError(f"load_footprint: unrecognized extension {path.suffix!r} for {path}")


def ticks_to_footprint(ticks: Iterable[Tick], tick_size: float,
                        bucket_seconds: int = 1800) -> Iterator[FootprintCell]:
    """Derive footprint cells directly from ticks when no separate footprint
    export exists: bins each tick into a (time_bucket, price) cell and
    accumulates its volume on the bid or ask side per its aggressor."""
    from collections import defaultdict

    agg = defaultdict(lambda: [0, 0])  # (bucket_ts, price_ticks) -> [bid_vol, ask_vol]
    for t in ticks:
        bucket_epoch = int(t.ts.timestamp() // bucket_seconds) * bucket_seconds
        bucket_ts = datetime.fromtimestamp(bucket_epoch, tz=t.ts.tzinfo)
        price_ticks = round(t.price / tick_size)
        cell = agg[(bucket_ts, price_ticks)]
        if t.aggressor == "sell":
            cell[0] += t.volume
        elif t.aggressor == "buy":
            cell[1] += t.volume
        # "unknown" aggressor volume is dropped from the bid/ask split but
        # would double-count total volume if added to both sides.
    for (bucket_ts, price_ticks), (bid_vol, ask_vol) in sorted(agg.items()):
        yield FootprintCell(ts_bucket=bucket_ts, price=price_ticks * tick_size,
                             bid_volume=bid_vol, ask_volume=ask_vol)
