"""L0 measurement: split minute-bar engine economics by day-type score
(computed at IB completion, no hindsight) across the three periods."""
from datetime import date, timedelta
from collections import defaultdict

from config import load_config
from backtest.outcome import simulate_trade
from backtest.runner import daily_atr_from_days
from backtest.scid_fast import load_days
from signals.engine import generate_signals
from structure.daytype import classify_day
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
    print(f"  {tag}: n={len(rs)} win%={100*len(wins)/len(rs):.1f} PF={pf:.2f} "
          f"exp={sum(rs)/len(rs):+.3f}R totR={sum(rs):+.2f}")


all_rows = []
for path, d0, d1, label in FILES:
    tick = _cfg.meta.tick_size
    days = load_days(path)
    day_list = [days[k] for k in sorted(days)]
    ib_widths = []
    for i in range(2, len(day_list)):
        prior2, prior, today = day_list[i - 2], day_list[i - 1], day_list[i]
        if not (d0 <= today.day < d1) or not today.rth_bars or not prior.vap:
            # still track IB widths for the trailing average
            if today.rth_bars:
                ib = today.rth_bars[:60]
                ib_widths.append(max(b.high for b in ib) - min(b.low for b in ib))
            continue
        va = value_area(prior.vap, tick, _cfg.structural.va_percent)
        va2 = value_area(prior2.vap, tick, _cfg.structural.va_percent) if prior2.vap else {}
        if va["poc"] is None:
            continue
        atr = daily_atr_from_days(day_list, i - 1, _cfg.filters.atr_period)
        if atr <= 0:
            continue
        ib_bars = today.rth_bars[:60]
        avg_ib = sum(ib_widths[-20:]) / len(ib_widths[-20:]) if ib_widths else 0.0
        prior_day = {"open": None, "high": prior.full_high, "low": prior.full_low,
                     "close": prior.full_close}
        dt = classify_day(ib_bars, prior_day, va, va2, atr, avg_ib)
        ib_widths.append(max(b.high for b in ib_bars) - min(b.low for b in ib_bars))
        snap = StructuralSnapshot(trading_date=today.day, pd_va=va,
            ib={"high": None, "low": None, "mid": None},
            weekly={"vpoc": None, "pw_high": None, "pw_low": None},
            overnight={"high": None, "low": None}, prior_day=prior_day)
        for s in generate_signals(today.rth_bars, snap, tick):
            tr = simulate_trade(s, today.rth_bars, atr, tick)
            all_rows.append((label, dt.score, s.family, tr.r))

for label in [f[3] for f in FILES] + ["COMBINED"]:
    rows = [r for r in all_rows if label == "COMBINED" or r[0] == label]
    print(f"=== {label} | day-type score split (score at IB completion) ===")
    for fam in ("FOLLOW", "FADE"):
        lo = [r for _, sc, f, r in rows if f == fam and sc <= 1]
        hi = [r for _, sc, f, r in rows if f == fam and sc >= 2]
        stats(hi, f"{fam} score>=2")
        stats(lo, f"{fam} score<=1")
    print(flush=True)
