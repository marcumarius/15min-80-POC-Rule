"""Fast sequential .scid reader for batch backtests: one streaming numpy
pass over the whole file -> per-trading-day VAP dicts + 1-minute bars,
instead of a ~25s binary-searched extraction per day.

Format facts (validated byte-level against the user's real MNQU6 file,
2026-07-11 -- see data/loaders.py and docs/phase1_report.md §3):
  "SCID" magic, <II header/record size, records = <qffffIIII
  (int64-microsecond datetime since 1899-12-30 UTC, O/H/L/C float32 scaled
  x100, NumTrades/TotalVolume/BidVolume/AskVolume uint32).

Differences vs the per-tick path (data/loaders.py + data/bars.py), stated
so nobody hunts a "bug" later:
  - Bar bid/ask volume here sums each record's BidVolume/AskVolume fields
    directly instead of attributing the record's TOTAL volume to whichever
    side dominates. For single-sided records (the norm in this feed,
    av+bv == tv) the two are identical; for mixed records this path is the
    MORE accurate one.
  - Trade price is the record's Close (same as the per-tick path).

Trading-day bucketing is the 18:00-ET boundary (sessions.trading_day), and
the daily VAP is FULL-session per D-011. Both are applied at minute
resolution -- exact, because 18:00:00 and 09:30/16:00 are minute boundaries.
"""
import struct
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np

from data.types import Bar
from structure.sessions import in_rth, trading_day

_ET = ZoneInfo("America/New_York")
_EPOCH = datetime(1899, 12, 30, tzinfo=timezone.utc)

_DTYPE = np.dtype([
    ("dt", "<i8"), ("o", "<f4"), ("h", "<f4"), ("l", "<f4"), ("c", "<f4"),
    ("nt", "<u4"), ("tv", "<u4"), ("bv", "<u4"), ("av", "<u4"),
])

PRICE_SCALE = 0.01           # raw float -> price (see config meta.scid_price_scale)
_RAW_PER_TICK = 25.0          # 0.25 tick / 0.01 scale, in raw price units


class DayData:
    """One trading day's aggregates: full-session VAP + OHLC, RTH minute bars."""
    __slots__ = ("day", "vap", "full_high", "full_low", "full_close", "rth_bars")

    def __init__(self, day):
        self.day = day
        self.vap = {}             # price-in-ticks -> total volume (FULL session, D-011)
        self.full_high = None
        self.full_low = None
        self.full_close = None
        self.rth_bars = []


def _minute_to_et(minute_idx: int) -> datetime:
    return (_EPOCH + timedelta(minutes=int(minute_idx))).astimezone(_ET)


def load_days(path, chunk_records: int = 5_000_000) -> dict:
    """Stream the file once; returns {trading_day: DayData}, days in file order."""
    days: dict = {}
    pending = None   # partial minute group carried across a chunk boundary

    def flush_group(minute_idx, o, h, l, c, tv, bv, av, tick_prices, tick_vols):
        ts = _minute_to_et(minute_idx)
        day = trading_day(ts)
        dd = days.get(day)
        if dd is None:
            dd = days[day] = DayData(day)
        # full-session aggregates (D-011 window == the whole trading day)
        dd.full_high = h if dd.full_high is None else max(dd.full_high, h)
        dd.full_low = l if dd.full_low is None else min(dd.full_low, l)
        dd.full_close = c
        u, inv = np.unique(tick_prices, return_inverse=True)
        sums = np.bincount(inv, weights=tick_vols)
        for tk, v in zip(u.tolist(), sums.tolist()):
            dd.vap[tk] = dd.vap.get(tk, 0.0) + v
        if in_rth(ts):
            dd.rth_bars.append(Bar(ts=ts, open=o, high=h, low=l, close=c,
                                   volume=int(tv), bid_volume=int(bv), ask_volume=int(av),
                                   delta=int(av) - int(bv)))

    with open(path, "rb") as f:
        magic = f.read(4)
        if magic != b"SCID":
            raise ValueError(f"not a .scid file: {path}")
        header_size, record_size = struct.unpack("<II", f.read(8))
        if record_size != _DTYPE.itemsize:
            raise ValueError(f"unexpected record size {record_size}")
        f.seek(header_size)

        while True:
            arr = np.fromfile(f, dtype=_DTYPE, count=chunk_records)
            if arr.size == 0:
                break
            minutes = arr["dt"] // 60_000_000
            price = arr["c"].astype(np.float64) * PRICE_SCALE
            ticks = np.rint(arr["c"].astype(np.float64) / _RAW_PER_TICK).astype(np.int64)
            tv = arr["tv"].astype(np.float64)

            starts = np.flatnonzero(np.diff(minutes)) + 1
            starts = np.concatenate(([0], starts))
            ends = np.concatenate((starts[1:], [len(minutes)]))

            for s, e in zip(starts.tolist(), ends.tolist()):
                m = int(minutes[s])
                seg_p = price[s:e]
                g = {
                    "m": m, "o": float(seg_p[0]), "h": float(seg_p.max()),
                    "l": float(seg_p.min()), "c": float(seg_p[-1]),
                    "tv": float(tv[s:e].sum()),
                    "bv": float(arr["bv"][s:e].sum(dtype=np.int64)),
                    "av": float(arr["av"][s:e].sum(dtype=np.int64)),
                    "ticks": ticks[s:e], "tick_vols": tv[s:e],
                }
                if pending is not None and pending["m"] == m:
                    pending["h"] = max(pending["h"], g["h"])
                    pending["l"] = min(pending["l"], g["l"])
                    pending["c"] = g["c"]
                    for k in ("tv", "bv", "av"):
                        pending[k] += g[k]
                    pending["ticks"] = np.concatenate((pending["ticks"], g["ticks"]))
                    pending["tick_vols"] = np.concatenate((pending["tick_vols"], g["tick_vols"]))
                    continue
                if pending is not None:
                    flush_group(pending["m"], pending["o"], pending["h"], pending["l"],
                                pending["c"], pending["tv"], pending["bv"], pending["av"],
                                pending["ticks"], pending["tick_vols"])
                pending = g

    if pending is not None:
        flush_group(pending["m"], pending["o"], pending["h"], pending["l"],
                    pending["c"], pending["tv"], pending["bv"], pending["av"],
                    pending["ticks"], pending["tick_vols"])
    return days
