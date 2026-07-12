"""Book+tape absorption lab (Jan H26 days: same-contract depth + trades).

TRUE absorption: a price level that absorbs MULTIPLES of its displayed
resting size without breaking -- iceberg/refresh behavior invisible in
traded-volume data. Episode logic (per price level, at the touch):

  - sell aggression hitting the BEST BID at P accumulates ep.traded
  - ep.max_rest tracks the largest displayed bid qty seen at P
  - if best bid drops below P -> level BROKE, episode dies
  - fire (once) when ep.traded >= absorb_ratio * ep.max_rest and
    ep.traded >= min_traded while the level still holds
  mirror for buy aggression at the best ask.

Outcome check: price `horizon` later vs event price, in the absorption
direction (bid absorption -> expect UP). Lab-grade: n is small, this is a
feature viability check, not economics.
"""
import sys
from datetime import date, timedelta

from data.depth import (ADD_ASK, ADD_BID, CLEAR_BOOK, DELETE_ASK, DELETE_BID,
                        MODIFY_ASK, MODIFY_BID, Book, iter_depth)
from data.loaders import iter_scid_ticks_for_day
from structure.sessions import in_rth

TICK = 0.25
ABSORB_RATIO = 4.0     # traded >= 4x max displayed size at the level
MIN_TRADED = 15        # contracts; CALIBRATED 2026-07-12 on real MNQH26 book:
                        # median episode traded=2, p90=6, p99=16 (400k-trade sample) --
                        # the original 300 was picked blind and never fired once.
HORIZON_MIN = 15


class Ep:
    __slots__ = ("traded", "max_rest", "fired")
    def __init__(self):
        self.traded = 0; self.max_rest = 0; self.fired = False


def run(depth_path, scid_path, day):
    trades = [t for t in iter_scid_ticks_for_day(scid_path, day) if in_rth(t.ts)]
    print(f"{day}: {len(trades)} RTH trades")
    book = Book(TICK)
    di = iter_depth(depth_path)
    upd = next(di, None)
    bid_eps, ask_eps = {}, {}
    events = []
    for tr in trades:
        while upd is not None and upd.ts <= tr.ts:
            book.apply(upd)
            tks = round(upd.price / TICK)
            if upd.command in (ADD_BID, MODIFY_BID) and tks in bid_eps:
                ep = bid_eps[tks]
                ep.max_rest = max(ep.max_rest, upd.quantity)
            elif upd.command in (ADD_ASK, MODIFY_ASK) and tks in ask_eps:
                ep = ask_eps[tks]
                ep.max_rest = max(ep.max_rest, upd.quantity)
            upd = next(di, None)
        bb, ba = book.best_bid(), book.best_ask()
        if bb is None or ba is None:
            continue
        bb_t, ba_t = round(bb / TICK), round(ba / TICK)
        # kill episodes whose level broke
        for tks in [k for k in bid_eps if k > bb_t]:
            del bid_eps[tks]
        for tks in [k for k in ask_eps if k < ba_t]:
            del ask_eps[tks]
        p_t = round(tr.price / TICK)
        if tr.aggressor == "sell" and p_t == bb_t:
            ep = bid_eps.setdefault(p_t, Ep())
            ep.traded += tr.volume
            ep.max_rest = max(ep.max_rest, book.bids.get(p_t, (0, 0))[0], 1)
            if not ep.fired and ep.traded >= MIN_TRADED and ep.traded >= ABSORB_RATIO * ep.max_rest:
                ep.fired = True
                events.append((tr.ts, tr.price, "bullish", ep.traded, ep.max_rest))
        elif tr.aggressor == "buy" and p_t == ba_t:
            ep = ask_eps.setdefault(p_t, Ep())
            ep.traded += tr.volume
            ep.max_rest = max(ep.max_rest, book.asks.get(p_t, (0, 0))[0], 1)
            if not ep.fired and ep.traded >= MIN_TRADED and ep.traded >= ABSORB_RATIO * ep.max_rest:
                ep.fired = True
                events.append((tr.ts, tr.price, "bearish", ep.traded, ep.max_rest))

    # outcome check
    print(f"{len(events)} true-absorption events")
    wins = 0; moves = []
    for ts, price, direction, traded, rest in events:
        cutoff = ts + timedelta(minutes=HORIZON_MIN)
        later = [t.price for t in trades if ts < t.ts <= cutoff]
        if not later:
            continue
        end = later[-1]
        mv = (end - price) if direction == "bullish" else (price - end)
        moves.append(mv)
        if mv > 0:
            wins += 1
        print(f"  {ts.strftime('%H:%M:%S')} {direction:8s} @{price:.2f} "
              f"traded={traded} maxrest={rest} ratio={traded/max(rest,1):.1f} "
              f"-> {HORIZON_MIN}m move {mv:+.2f}")
    if moves:
        print(f"\nhit rate {100*wins/len(moves):.0f}% ({wins}/{len(moves)}), "
              f"mean {HORIZON_MIN}m move {sum(moves)/len(moves):+.2f} pts")


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else "2026-01-13"
    y, m, dd = map(int, d.split("-"))
    run(f"depth/MNQH26_FUT_CME.{d}.depth", "Scid data/MNQH26_FUT_CME.scid", date(y, m, dd))
