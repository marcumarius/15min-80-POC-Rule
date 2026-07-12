"""Trade-count (e.g. 800-trade) bar builder with per-bar footprint summaries.

Activity-based bars: every bar is `bar_trades` trades, so |delta|, range and
volume are comparable bar-to-bar regardless of time of day -- the fix for
the measured failure of absorption on minute bars (docs/
phase2_interim_report.md). Bars never span a trading-day boundary.

Per-bar footprint cells are built transiently (numpy, per bar) and reduced
to stacked-imbalance summaries immediately -- full cell retention for ~9
months would be GBs of python objects. Each returned Bar carries two extra
attributes: `buy_stack` / `sell_stack` = the longest consecutive-tick
diagonal-imbalance stack in that bar (0 if none), per config
order_flow.imbalance_ratio / stacked_imbalance_min semantics.

RTH-only output: signals/outcomes run on RTH bars; PD VA / ATR come from
backtest/scid_fast.load_days (full-session, D-011) in a separate pass.
"""
import struct
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np

from config import load_config
from data.types import Bar, FootprintCell
from features.imbalance import detect_stacked_imbalances
from structure.sessions import in_rth, trading_day

_cfg = load_config()
_ET = ZoneInfo("America/New_York")
_EPOCH = datetime(1899, 12, 30, tzinfo=timezone.utc)
_DTYPE = np.dtype([
    ("dt", "<i8"), ("o", "<f4"), ("h", "<f4"), ("l", "<f4"), ("c", "<f4"),
    ("nt", "<u4"), ("tv", "<u4"), ("bv", "<u4"), ("av", "<u4"),
])
PRICE_SCALE = 0.01
_RAW_PER_TICK = 25.0


def _bars_for_day(day_arr, bar_trades, tick_size, ratio, min_stack):
    """Vectorized bar build for ONE day's RTH records (numpy structured array)."""
    n = len(day_arr)
    nbars = n // bar_trades          # drop the final partial bar
    if nbars == 0:
        return []
    price = day_arr["c"].astype(np.float64) * PRICE_SCALE
    ticks = np.rint(day_arr["c"].astype(np.float64) / _RAW_PER_TICK).astype(np.int64)
    bars = []
    for k in range(nbars):
        s, e = k * bar_trades, (k + 1) * bar_trades
        seg_p = price[s:e]
        ts = (_EPOCH + timedelta(microseconds=int(day_arr["dt"][s]))).astimezone(_ET)
        tv = int(day_arr["tv"][s:e].sum(dtype=np.int64))
        bv = int(day_arr["bv"][s:e].sum(dtype=np.int64))
        av = int(day_arr["av"][s:e].sum(dtype=np.int64))
        b = Bar(ts=ts, open=float(seg_p[0]), high=float(seg_p.max()),
                low=float(seg_p.min()), close=float(seg_p[-1]),
                volume=tv, bid_volume=bv, ask_volume=av, delta=av - bv)
        # transient footprint -> stacked-imbalance summary
        seg_t = ticks[s:e]
        u, inv = np.unique(seg_t, return_inverse=True)
        bidsum = np.bincount(inv, weights=day_arr["bv"][s:e]).astype(np.int64)
        asksum = np.bincount(inv, weights=day_arr["av"][s:e]).astype(np.int64)
        cells = [FootprintCell(ts_bucket=b.ts, price=float(t * tick_size),
                                bid_volume=int(bd), ask_volume=int(ak))
                 for t, bd, ak in zip(u.tolist(), bidsum.tolist(), asksum.tolist())]
        stacks = detect_stacked_imbalances(cells, tick_size, ratio=ratio, min_stack=min_stack)
        b.buy_stack = max((st.count for st in stacks if st.direction == "buy"), default=0)
        b.sell_stack = max((st.count for st in stacks if st.direction == "sell"), default=0)
        bars.append(b)
    return bars


def load_trade_bars(path, bar_trades=None):
    """Stream the file once; returns {trading_day: [Bar,...]} of RTH
    trade-count bars with buy_stack/sell_stack footprint summaries."""
    if bar_trades is None:
        bar_trades = _cfg.order_flow.bar_trades
    tick_size = _cfg.meta.tick_size
    ratio = _cfg.order_flow.imbalance_ratio
    min_stack = _cfg.order_flow.stacked_imbalance_min

    out = {}
    cur_day = None
    day_parts = []   # list of numpy record slices for the current day (RTH only)

    def flush():
        if cur_day is None or not day_parts:
            return
        day_arr = np.concatenate(day_parts)
        bars = _bars_for_day(day_arr, bar_trades, tick_size, ratio, min_stack)
        if bars:
            out[cur_day] = bars

    with open(path, "rb") as f:
        if f.read(4) != b"SCID":
            raise ValueError(f"not a .scid file: {path}")
        header_size, record_size = struct.unpack("<II", f.read(8))
        f.seek(header_size)
        while True:
            arr = np.fromfile(f, dtype=_DTYPE, count=5_000_000)
            if arr.size == 0:
                break
            minutes = arr["dt"] // 60_000_000
            # map each unique minute (few thousand/chunk) once, then broadcast
            uniq = np.unique(minutes)
            u_days, u_rth = [], []
            for m in uniq.tolist():
                ts = (_EPOCH + timedelta(minutes=m)).astimezone(_ET)
                u_days.append(trading_day(ts).toordinal())
                u_rth.append(in_rth(ts))
            idx = np.searchsorted(uniq, minutes)
            day_ord = np.asarray(u_days, dtype=np.int64)[idx]
            rth_mask = np.asarray(u_rth, dtype=bool)[idx]
            # walk day segments within the chunk (days change ~once per chunk)
            seg_starts = np.concatenate(([0], np.flatnonzero(np.diff(day_ord)) + 1))
            seg_ends = np.concatenate((seg_starts[1:], [len(arr)]))
            from datetime import date as _date
            for i, j in zip(seg_starts.tolist(), seg_ends.tolist()):
                d = _date.fromordinal(int(day_ord[i]))
                if d != cur_day:
                    flush()
                    cur_day, day_parts = d, []
                seg_mask = rth_mask[i:j]
                if seg_mask.any():
                    day_parts.append(arr[i:j][seg_mask])
    flush()
    return out
