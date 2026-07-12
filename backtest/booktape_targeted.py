"""Targeted book+tape check: does the RESTING BOOK show genuine absorption
at times/prices the trade-based engine already flagged as turning points?

Faster than data/depth.py's iter_depth for whole-day scans (83M+ records):
reads raw structured arrays directly, applies book updates with minimal
per-record Python overhead, and only evaluates absorption episodes/prints
detail inside the requested time windows.
"""
import struct
import sys
from datetime import datetime, timedelta, timezone

from zoneinfo import ZoneInfo

import numpy as np

_ET = ZoneInfo("America/New_York")
_EPOCH = datetime(1899, 12, 30, tzinfo=timezone.utc)
_DTYPE = np.dtype([("dt", "<i8"), ("cmd", "u1"), ("flags", "u1"),
                   ("norders", "<u2"), ("price", "<f4"), ("qty", "<u4"),
                   ("res", "<u4")])
PRICE_SCALE = 0.01
ADD_BID, ADD_ASK, MODIFY_BID, MODIFY_ASK, DELETE_BID, DELETE_ASK = 2, 3, 4, 5, 6, 7
CLEAR = 1


def scan_windows(depth_path, tick_size, windows, chunk=10_000_000):
    """windows: list of (start_dt_et, end_dt_et). Returns per-window list of
    (ts, side, price, qty, num_orders) book-update events inside the window,
    plus best bid/ask snapshots at window boundaries for context."""
    bids, asks = {}, {}
    out = {i: [] for i in range(len(windows))}
    win_bounds = [(w[0].astimezone(timezone.utc), w[1].astimezone(timezone.utc)) for w in windows]

    with open(depth_path, "rb") as f:
        if f.read(4) != b"SCDD":
            raise ValueError("bad magic")
        hs, rs = struct.unpack("<II", f.read(8))
        f.seek(hs)
        n_done = 0
        while True:
            arr = np.fromfile(f, dtype=_DTYPE, count=chunk)
            if arr.size == 0:
                break
            # cheap pre-filter: skip full python loop for chunks entirely
            # outside every window (common case for an 83M-record day when
            # we only care about ~40 minutes of it)
            chunk_t0 = _EPOCH + timedelta(microseconds=int(arr["dt"][0]))
            chunk_t1 = _EPOCH + timedelta(microseconds=int(arr["dt"][-1]))
            relevant = any(not (chunk_t1 < w0 or chunk_t0 > w1) for w0, w1 in win_bounds)

            dt_arr, cmd_arr, no_arr, price_arr, qty_arr = (
                arr["dt"], arr["cmd"], arr["norders"], arr["price"], arr["qty"])
            for i in range(len(arr)):
                cmd = cmd_arr[i]
                price = float(price_arr[i]) * PRICE_SCALE
                tks = round(price / tick_size)
                if cmd == CLEAR:
                    bids.clear(); asks.clear()
                elif cmd == ADD_BID or cmd == MODIFY_BID:
                    bids[tks] = int(qty_arr[i])
                elif cmd == ADD_ASK or cmd == MODIFY_ASK:
                    asks[tks] = int(qty_arr[i])
                elif cmd == DELETE_BID:
                    bids.pop(tks, None)
                elif cmd == DELETE_ASK:
                    asks.pop(tks, None)

                if relevant:
                    ts_utc = _EPOCH + timedelta(microseconds=int(dt_arr[i]))
                    for wi, (w0, w1) in enumerate(win_bounds):
                        if w0 <= ts_utc <= w1:
                            ts_et = ts_utc.astimezone(_ET)
                            out[wi].append((ts_et, cmd, price, int(qty_arr[i]), int(no_arr[i])))
            n_done += len(arr)
            if not relevant and chunk_t0 > max(w1 for _, w1 in win_bounds):
                break
    return out


def best(levels, tick_size, is_bid):
    if not levels:
        return None
    tks = max(levels) if is_bid else min(levels)
    return tks * tick_size, levels[tks]


if __name__ == "__main__":
    day = sys.argv[1] if len(sys.argv) > 1 else "2026-07-08"
    path = f"depth/MNQU26_FUT_CME.{day}.depth"
    windows = [
        (datetime(2026, 7, 8, 11, 15, tzinfo=_ET), datetime(2026, 7, 8, 11, 35, tzinfo=_ET), "session-low window (11:25 ET)"),
        (datetime(2026, 7, 8, 12, 7, tzinfo=_ET), datetime(2026, 7, 8, 12, 27, tzinfo=_ET), "FADE-trigger window (12:17 ET)"),
    ]
    results = scan_windows(path, 0.25, [(w[0], w[1]) for w in windows])
    for i, (w0, w1, label) in enumerate(windows):
        evs = results[i]
        print(f"=== {label}: {len(evs)} book updates in [{w0.strftime('%H:%M')}-{w1.strftime('%H:%M')}] ===")
        if not evs:
            continue
        # summarize: for each price, track total qty added/modified over the window
        # (a level whose size keeps refreshing back up after trading through it = absorption)
        by_price_bid, by_price_ask = {}, {}
        for ts, cmd, price, qty, no in evs:
            if cmd in (ADD_BID, MODIFY_BID):
                by_price_bid.setdefault(price, []).append((ts, qty))
            elif cmd in (ADD_ASK, MODIFY_ASK):
                by_price_ask.setdefault(price, []).append((ts, qty))
        top_bid = sorted(by_price_bid.items(), key=lambda kv: -len(kv[1]))[:5]
        top_ask = sorted(by_price_ask.items(), key=lambda kv: -len(kv[1]))[:5]
        print("  most-refreshed BID levels (price: #updates, qty sequence):")
        for price, upd in top_bid:
            print(f"    {price:.2f}: {len(upd)} updates, qty {[q for _, q in upd[:15]]}")
        print("  most-refreshed ASK levels:")
        for price, upd in top_ask:
            print(f"    {price:.2f}: {len(upd)} updates, qty {[q for _, q in upd[:15]]}")
