"""Tick/footprint ingestion (Rithmic exports, Sierra .scid/.depth).

Phase 1 deliverable (docs/phase1_foundation_engine.md section 3.1).
ET-align, deduplicate, sort; DST-safe; preserve per-price bid/ask volume.

*** UNVALIDATED ***: no sample .scid, .depth, or Rithmic export exists in
this repo. The .scid parser below follows Sierra Chart's documented
s_IntradayFileHeader/s_IntradayRecord binary layout (56-byte header read via
its own HeaderSize field, 40-byte fixed records), and assumes UTC-stamped
records per Sierra's documented default. Per CLAUDE.md's "evidence before
trust" rule, do not treat this as ground truth until it has reproduced a
known day's OHLC against Sierra Chart's own display -- see the timezone-bleed
warning in docs/phase1_foundation_engine.md section 5.
"""
import csv
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator
from zoneinfo import ZoneInfo

from data.types import FootprintCell, Tick

_ET = ZoneInfo("America/New_York")
_SCDATETIME_EPOCH = datetime(1899, 12, 30, tzinfo=timezone.utc)  # OLE Automation date epoch

_SCID_RECORD_FMT = "<dffffIIII"  # datetime, O,H,L,C, NumTrades, TotalVolume, BidVolume, AskVolume
_SCID_RECORD_SIZE = struct.calcsize(_SCID_RECORD_FMT)


def _scdatetime_to_et(raw: float) -> datetime:
    """SCDateTime -> tz-aware ET. Sierra stores the integer part as days
    since 1899-12-30 and the fractional part as time-of-day, in UTC."""
    utc_dt = _SCDATETIME_EPOCH + timedelta(days=raw)
    return utc_dt.astimezone(_ET)


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


def _load_scid_ticks(path: Path) -> list:
    """Parse a Sierra Chart .scid file (per-tick storage) into Ticks.

    Each 40-byte record's OHLC are all equal to the trade price when the
    chart is configured for tick-level (not time-bar) storage; BidVolume vs
    AskVolume classify the aggressor directly, so classify_aggressor() is not
    needed here -- Sierra has already done that split at write time.
    """
    ticks = []
    with open(path, "rb") as f:
        header_size = struct.unpack("<I", f.read(4))[0]
        f.seek(header_size)
        while True:
            chunk = f.read(_SCID_RECORD_SIZE)
            if len(chunk) < _SCID_RECORD_SIZE:
                break
            raw_dt, _o, _h, _l, close, _num_trades, total_vol, bid_vol, ask_vol = \
                struct.unpack(_SCID_RECORD_FMT, chunk)
            ts = _scdatetime_to_et(raw_dt)
            if ask_vol >= bid_vol:
                aggressor = "buy" if ask_vol > 0 else "unknown"
            else:
                aggressor = "sell" if bid_vol > 0 else "unknown"
            ticks.append(Tick(ts=ts, price=close, volume=total_vol, aggressor=aggressor))
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
