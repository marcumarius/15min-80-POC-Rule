"""Sierra Chart .depth market-depth file parser + order-book reconstruction.

Format VALIDATED 2026-07-12 against the user's real depth recordings
(MNQM26 2026-05-18, MNQH26 2026-01-12..19), byte-level:
  header: "SCDD" magic, u32 HeaderSize (64), u32 RecordSize (24), u16 version
  record: <qBBHfII = DateTime (int64 MICROSECONDS since 1899-12-30 UTC --
          same epoch/unit as .scid), Command u8, Flags u8, NumOrders u16,
          Price f32 (x100 scaled, same as .scid), Quantity u32, Reserved u32
  commands: 1=CLEAR_BOOK, 2=ADD_BID, 3=ADD_ASK, 4=MODIFY_BID, 5=MODIFY_ASK,
            6=DELETE_BID, 7=DELETE_ASK

This is the RESTING book (bookmap layer) -- what .scid can never show.
Enables true absorption detection: watching liquidity refresh at a level
under aggression instead of inferring it from traded volume alone.
"""
import struct
from datetime import datetime, timedelta, timezone
from typing import Iterator, NamedTuple
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")
_EPOCH = datetime(1899, 12, 30, tzinfo=timezone.utc)
_FMT = struct.Struct("<qBBHfII")
_PRICE_SCALE = 0.01

CLEAR_BOOK, ADD_BID, ADD_ASK, MODIFY_BID, MODIFY_ASK, DELETE_BID, DELETE_ASK = range(1, 8)


class DepthUpdate(NamedTuple):
    ts: datetime          # tz-aware ET
    command: int
    price: float
    quantity: int
    num_orders: int


def iter_depth(path) -> Iterator[DepthUpdate]:
    """Stream depth updates from a .depth file, ET-converted, in file order."""
    with open(path, "rb") as f:
        if f.read(4) != b"SCDD":
            raise ValueError(f"not a .depth file: {path}")
        header_size, record_size = struct.unpack("<II", f.read(8))
        if record_size != _FMT.size:
            raise ValueError(f"unexpected .depth record size {record_size}")
        f.seek(header_size)
        while True:
            chunk = f.read(_FMT.size)
            if len(chunk) < _FMT.size:
                break
            dt, cmd, _flags, num_orders, price, qty, _res = _FMT.unpack(chunk)
            ts = (_EPOCH + timedelta(microseconds=dt)).astimezone(_ET)
            yield DepthUpdate(ts, cmd, price * _PRICE_SCALE, qty, num_orders)


class Book:
    """Maintains the resting book from a DepthUpdate stream. Prices keyed in
    ticks to avoid float-equality bugs."""

    def __init__(self, tick_size: float):
        self.tick_size = tick_size
        self.bids: dict = {}   # price_ticks -> (quantity, num_orders)
        self.asks: dict = {}

    def apply(self, u: DepthUpdate):
        tks = round(u.price / self.tick_size)
        if u.command == CLEAR_BOOK:
            self.bids.clear()
            self.asks.clear()
        elif u.command in (ADD_BID, MODIFY_BID):
            self.bids[tks] = (u.quantity, u.num_orders)
        elif u.command in (ADD_ASK, MODIFY_ASK):
            self.asks[tks] = (u.quantity, u.num_orders)
        elif u.command == DELETE_BID:
            self.bids.pop(tks, None)
        elif u.command == DELETE_ASK:
            self.asks.pop(tks, None)

    def best_bid(self):
        return max(self.bids) * self.tick_size if self.bids else None

    def best_ask(self):
        return min(self.asks) * self.tick_size if self.asks else None

    def depth_at(self, price: float):
        """(bid_qty, ask_qty) resting at a price, 0 if none."""
        tks = round(price / self.tick_size)
        return (self.bids.get(tks, (0, 0))[0], self.asks.get(tks, (0, 0))[0])
