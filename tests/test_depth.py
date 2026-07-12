import struct
from datetime import datetime, timezone

import pytest

from data.depth import (ADD_ASK, ADD_BID, CLEAR_BOOK, DELETE_BID, MODIFY_ASK,
                        Book, DepthUpdate, iter_depth)

_EPOCH = datetime(1899, 12, 30, tzinfo=timezone.utc)


def _depth_bytes(records):
    """records: (micros, cmd, num_orders, raw_price, qty)"""
    header = b"SCDD" + struct.pack("<II", 64, 24) + b"\x00" * 52
    body = b"".join(struct.pack("<qBBHfII", m, c, 0, no, p, q, 0)
                    for m, c, no, p, q in records)
    return header + body


def test_iter_depth_parses_validated_format(tmp_path):
    ts = datetime(2026, 5, 18, 11, 47, 44, tzinfo=timezone.utc)
    micros = int((ts - _EPOCH).total_seconds() * 1_000_000)
    p = tmp_path / "sample.depth"
    # raw price 2919875.0 -> 29198.75 (x0.01, same scale as .scid)
    p.write_bytes(_depth_bytes([(micros, ADD_BID, 3, 2919875.0, 2)]))
    updates = list(iter_depth(p))
    assert len(updates) == 1
    u = updates[0]
    assert u.command == ADD_BID
    assert u.price == pytest.approx(29198.75)
    assert u.quantity == 2
    assert u.num_orders == 3
    assert u.ts.astimezone(timezone.utc) == ts


def test_iter_depth_rejects_bad_magic(tmp_path):
    p = tmp_path / "bad.depth"
    p.write_bytes(b"XXXX" + struct.pack("<II", 64, 24) + b"\x00" * 52)
    with pytest.raises(ValueError):
        list(iter_depth(p))


def test_book_add_modify_delete_and_clear():
    ts = datetime(2026, 5, 18, tzinfo=timezone.utc)
    book = Book(0.25)
    book.apply(DepthUpdate(ts, ADD_BID, 100.00, 5, 1))
    book.apply(DepthUpdate(ts, ADD_BID, 99.75, 8, 2))
    book.apply(DepthUpdate(ts, ADD_ASK, 100.25, 4, 1))
    assert book.best_bid() == pytest.approx(100.00)
    assert book.best_ask() == pytest.approx(100.25)
    assert book.depth_at(99.75) == (8, 0)

    book.apply(DepthUpdate(ts, MODIFY_ASK, 100.25, 9, 3))
    assert book.depth_at(100.25) == (0, 9)

    book.apply(DepthUpdate(ts, DELETE_BID, 100.00, 0, 0))
    assert book.best_bid() == pytest.approx(99.75)

    book.apply(DepthUpdate(ts, CLEAR_BOOK, 0.0, 0, 0))
    assert book.best_bid() is None and book.best_ask() is None
