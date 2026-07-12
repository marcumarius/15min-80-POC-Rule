"""Trade-bar batch: PD VA/ATR from the minute-bar pass (load_days), signals +
outcomes on 800-trade RTH bars with footprint stack summaries. Reports the
three front-month periods separately; FOLLOW additionally split by whether a
stacked imbalance in the trade direction appeared on/near the trigger bar."""
import sys
from datetime import date
from collections import defaultdict

from config import load_config
from backtest.outcome import simulate_trade
from backtest.runner import daily_atr_from_days
from backtest.scid_fast import load_days
from backtest.tradebars import load_trade_bars
from signals.engine import generate_signals
from structure.levels import StructuralSnapshot
from structure.value_area import value_area

_cfg = load_config()

FILES = [
    ("Scid data/MNQH26_FUT_CME.scid", date(2025, 12, 19), date(2026, 3, 21), "H26 front (Dec19-Mar20)"),
    ("Scid data/MNQM6.CME.scid", date(2026, 3, 20), date(2026, 6, 19), "M6 front (Mar20-Jun18)"),
    ("Scid data/MNQU6.CME.scid", date(2026, 5, 29), date(2026, 7, 11), "U6 (May29-Jul10)"),
]


def stats(rs, tag):
    if not rs:
        print(f"  {tag}: n=0")
        return
    wins = [r for r in rs if r > 0]
    gl = -sum(r for r in rs if r <= 0)
    gw = sum(wins)
    pf = gw / gl if gl > 0 else float("inf")
    peak = dd = cum = 0.0
    for r in rs:
        cum += r
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    print(f"  {tag}: n={len(rs)} win%={100*len(wins)/len(rs):.1f} PF={pf:.2f} "
          f"exp={sum(rs)/len(rs):+.3f}R totR={sum(rs):+.2f} maxDD={dd:.2f}R")


def run_file(path, d0, d1, label):
    tick = _cfg.meta.tick_size
    days = load_days(path)
    tbars = load_trade_bars(path)
    day_list = [days[k] for k in sorted(days)]
    results = []
    for i in range(1, len(day_list)):
        prior, today = day_list[i - 1], day_list[i]
        if not (d0 <= today.day < d1) or today.day not in tbars or not prior.vap:
            continue
        va = value_area(prior.vap, tick, _cfg.structural.va_percent)
        if va["poc"] is None:
            continue
        atr = daily_atr_from_days(day_list, i - 1, _cfg.filters.atr_period)
        if atr <= 0:
            continue
        snap = StructuralSnapshot(
            trading_date=today.day, pd_va=va,
            ib={"high": None, "low": None, "mid": None},
            weekly={"vpoc": None, "pw_high": None, "pw_low": None},
            overnight={"high": None, "low": None},
            prior_day={"open": None, "high": prior.full_high,
                       "low": prior.full_low, "close": prior.full_close})
        bars = tbars[today.day]
        for s in generate_signals(bars, snap, tick):
            tr = simulate_trade(s, bars, atr, tick)
            # stacked imbalance in trade direction on trigger bar or 2 before
            stack = 0
            for j in range(max(0, s.bar_index - 2), s.bar_index + 1):
                b = bars[j]
                stack = max(stack, b.buy_stack if s.direction > 0 else b.sell_stack)
            results.append((today.day, s, tr, stack))

    print(f"=== {label} | 800-trade bars ===")
    stats([tr.r for _, s, tr, _st in results], "RAW ALL      ")
    stats([tr.r for _, s, tr, _st in results if s.family == "FADE"], "FADE         ")
    fol = [(tr.r, st) for _, s, tr, st in results if s.family == "FOLLOW"]
    stats([r for r, _ in fol], "FOLLOW       ")
    stats([r for r, st in fol if st >= 3], "FOLLOW+stack ")
    stats([r for r, st in fol if st < 3], "FOLLOW nostack")
    ev_counts = defaultdict(int)
    for _, s, _, _ in results:
        for e in s.events:
            ev_counts[type(e).__name__.replace("Event", "")] += 1
    print("  trigger events:", dict(ev_counts))
    print(flush=True)


if __name__ == "__main__":
    for f, d0, d1, label in FILES:
        run_file(f, d0, d1, label)
