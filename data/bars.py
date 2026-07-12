"""Tick -> bar aggregation. Generic resampling, not an order-flow feature
itself -- features/ consumes these bars, this module only builds them.

Bars are context/plotting/feature-input only, never a trigger (CLAUDE.md
D-007) -- the whole rebuild exists to trigger on ticks/footprint events, not
on bar closes.
"""
from datetime import datetime
from typing import Iterable, Iterator

from data.types import Bar, Tick


def ticks_to_bars(ticks: Iterable[Tick], bar_seconds: int) -> Iterator[Bar]:
    """Aggregate ticks into fixed-duration time bars with OHLCV + delta.

    "unknown"-aggressor volume counts toward total `volume` but not toward
    `bid_volume`/`ask_volume`/`delta` -- consistent with
    data/loaders.py::ticks_to_footprint()'s handling of the same case
    (adding it to both sides would double-count; adding to neither
    under-counts delta but keeps it directionally honest).
    """
    bucket = None
    o = h = l = c = None
    volume = bid_volume = ask_volume = 0

    def flush():
        return Bar(ts=bucket, open=o, high=h, low=l, close=c, volume=volume,
                    bid_volume=bid_volume, ask_volume=ask_volume,
                    delta=ask_volume - bid_volume)

    for t in ticks:
        b = int(t.ts.timestamp() // bar_seconds) * bar_seconds
        b_ts = datetime.fromtimestamp(b, tz=t.ts.tzinfo)
        if bucket is not None and b_ts != bucket:
            yield flush()
            o = h = l = c = None
            volume = bid_volume = ask_volume = 0
        bucket = b_ts
        if o is None:
            o = h = l = t.price
        h = max(h, t.price)
        l = min(l, t.price)
        c = t.price
        volume += t.volume
        if t.aggressor == "buy":
            ask_volume += t.volume
        elif t.aggressor == "sell":
            bid_volume += t.volume

    if bucket is not None:
        yield flush()
