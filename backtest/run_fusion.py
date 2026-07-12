"""End-to-end fusion verification: same pipeline as run_gated but decisions
made by fusion.decision.FusionSession (all D-013 flags ON for this test).
Expected to be close to the run_gated result; the one deliberate difference
is that fusion counts gated-off signals toward conflict state."""
from datetime import date

from config import load_config
from backtest.outcome import simulate_trade
from backtest.runner import daily_atr_from_days
from backtest.scid_fast import load_days
from fusion.decision import FusionSession, TAKE
from signals.engine import generate_signals
from structure.daytype import classify_day
from structure.levels import StructuralSnapshot
from structure.value_area import value_area

_cfg = load_config()
FLAGS = {"d013_follow_gate": True, "d013_fade_gap_veto": True,
         "d013_narrow_ib_follow_veto": False, "live_conflict_veto": True}
FILES = [
    ("Scid data/MNQH26_FUT_CME.scid", date(2025, 12, 19), date(2026, 3, 21), "H26"),
    ("Scid data/MNQM6.CME.scid", date(2026, 3, 20), date(2026, 6, 19), "M6"),
    ("Scid data/MNQU6.CME.scid", date(2026, 5, 29), date(2026, 7, 11), "U6"),
]

taken = []   # (period, conviction, r)
for path, d0, d1, label in FILES:
    tick = _cfg.meta.tick_size
    days = load_days(path)
    day_list = [days[k] for k in sorted(days)]
    ib_widths = []
    for i in range(2, len(day_list)):
        prior2, prior, today = day_list[i - 2], day_list[i - 1], day_list[i]
        w = None
        if today.rth_bars:
            ib = today.rth_bars[:60]
            w = max(b.high for b in ib) - min(b.low for b in ib)
        if not (d0 <= today.day < d1) or not today.rth_bars or not prior.vap:
            if w is not None: ib_widths.append(w)
            continue
        va = value_area(prior.vap, tick, _cfg.structural.va_percent)
        va2 = value_area(prior2.vap, tick, _cfg.structural.va_percent) if prior2.vap else {}
        if va["poc"] is None:
            ib_widths.append(w); continue
        atr = daily_atr_from_days(day_list, i - 1, _cfg.filters.atr_period)
        if atr <= 0:
            ib_widths.append(w); continue
        avg_ib = sum(ib_widths[-20:]) / len(ib_widths[-20:]) if ib_widths else 0.0
        prior_day = {"open": None, "high": prior.full_high, "low": prior.full_low,
                     "close": prior.full_close}
        dt = classify_day(today.rth_bars[:60], prior_day, va, va2, atr, avg_ib)
        ib_widths.append(w)
        snap = StructuralSnapshot(trading_date=today.day, pd_va=va,
            ib={"high": None, "low": None, "mid": None},
            weekly={"vpoc": None, "pw_high": None, "pw_low": None},
            overnight={"high": None, "low": None}, prior_day=prior_day)
        session = FusionSession(dt, cfg=FLAGS)
        for s in sorted(generate_signals(today.rth_bars, snap, tick), key=lambda x: x.ts):
            decision = session.decide(s)
            if decision.action == TAKE:
                tr = simulate_trade(s, today.rth_bars, atr, tick)
                taken.append((label, decision.conviction, tr.r))


def stats(vals, tag):
    if not vals: print(f"  {tag}: n=0"); return
    wins = [v for v in vals if v > 0]
    gl = -sum(v for v in vals if v <= 0); gw = sum(wins)
    pf = gw / gl if gl > 0 else float("inf")
    peak = dd = cum = 0.0
    for v in vals:
        cum += v; peak = max(peak, cum); dd = max(dd, peak - cum)
    print(f"  {tag}: n={len(vals)} win%={100*len(wins)/len(vals):.1f} PF={pf:.2f} "
          f"exp={sum(vals)/len(vals):+.3f}R totR={sum(vals):+.2f} maxDD={dd:.2f}R")


print("=== FUSION-DECIDED SYSTEM (D-013 gates + live veto, skipped-counts-for-conflict) ===")
stats([r for _, _, r in taken], "ALL TAKEN")
for label in ("H26", "M6", "U6"):
    stats([r for p, _, r in taken if p == label], label)
for conv in ("HIGH", "MODERATE", "LOW"):
    stats([r for _, c, r in taken if c == conv], f"conviction {conv}")
