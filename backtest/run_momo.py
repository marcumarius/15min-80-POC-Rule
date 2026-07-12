"""MOMO (pullback/retest, MomentumTrade.md L2-L4) vs FOLLOW (buy-the-break)
head-to-head on minute bars across the three front-month periods."""
from datetime import date

from config import load_config
from backtest.outcome import simulate_trade
from backtest.runner import daily_atr_from_days
from backtest.scid_fast import load_days
from signals.engine import generate_signals
from signals.momentum import generate_momo_signals
from structure.levels import StructuralSnapshot
from structure.value_area import value_area

_cfg = load_config()
FILES = [
    ("Scid data/MNQH26_FUT_CME.scid", date(2025, 12, 19), date(2026, 3, 21), "H26 front"),
    ("Scid data/MNQM6.CME.scid", date(2026, 3, 20), date(2026, 6, 19), "M6 front"),
    ("Scid data/MNQU6.CME.scid", date(2026, 5, 29), date(2026, 7, 11), "U6"),
]


def stats(rs, tag):
    if not rs:
        print(f"  {tag}: n=0"); return
    wins = [r for r in rs if r > 0]
    gl = -sum(r for r in rs if r <= 0); gw = sum(wins)
    pf = gw / gl if gl > 0 else float("inf")
    peak = dd = cum = 0.0
    for r in rs:
        cum += r; peak = max(peak, cum); dd = max(dd, peak - cum)
    print(f"  {tag}: n={len(rs)} win%={100*len(wins)/len(rs):.1f} PF={pf:.2f} "
          f"exp={sum(rs)/len(rs):+.3f}R totR={sum(rs):+.2f} maxDD={dd:.2f}R")


combined = {"MOMO": [], "FOLLOW": []}
for path, d0, d1, label in FILES:
    tick = _cfg.meta.tick_size
    days = load_days(path)
    day_list = [days[k] for k in sorted(days)]
    momo, follow = [], []
    for i in range(1, len(day_list)):
        prior, today = day_list[i - 1], day_list[i]
        if not (d0 <= today.day < d1) or not today.rth_bars or not prior.vap:
            continue
        va = value_area(prior.vap, tick, _cfg.structural.va_percent)
        if va["poc"] is None:
            continue
        atr = daily_atr_from_days(day_list, i - 1, _cfg.filters.atr_period)
        if atr <= 0:
            continue
        snap = StructuralSnapshot(trading_date=today.day, pd_va=va,
            ib={"high": None, "low": None, "mid": None},
            weekly={"vpoc": None, "pw_high": None, "pw_low": None},
            overnight={"high": None, "low": None},
            prior_day={"open": None, "high": prior.full_high,
                       "low": prior.full_low, "close": prior.full_close})
        for s in generate_momo_signals(today.rth_bars, snap, tick):
            momo.append(simulate_trade(s, today.rth_bars, atr, tick).r)
        for s in generate_signals(today.rth_bars, snap, tick):
            if s.family == "FOLLOW":
                follow.append(simulate_trade(s, today.rth_bars, atr, tick).r)
    print(f"=== {label} | MOMO (pullback) vs FOLLOW (break) ===")
    stats(momo, "MOMO  ")
    stats(follow, "FOLLOW")
    combined["MOMO"] += momo
    combined["FOLLOW"] += follow
    print(flush=True)

print("=== COMBINED (9 months) ===")
stats(combined["MOMO"], "MOMO  ")
stats(combined["FOLLOW"], "FOLLOW")
