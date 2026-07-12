"""Batch backtest runner: walk every trading day in a .scid file, build the
prior-day snapshot (D-011 full-session VA), fire the FOLLOW/FADE engine on
RTH 1-minute bars, simulate each signal with the D-006/D-008 outcome model,
and report honest per-family economics.

Usage:  python -m backtest.runner "Scid data/MNQU6.CME.scid"

Raw, unfiltered first pass BY DESIGN: no no-man's-land filter (D-004), no
conflict veto (D-003) -- those are measured as overlays afterwards, not
baked in, so we can see what the raw triggers are worth. Not OOS, not
regime-split, one contract series: this is the FIRST honest look, not the
Phase 7 validation.
"""
import sys
from datetime import date

from config import load_config
from backtest.outcome import simulate_trade
from backtest.scid_fast import load_days
from signals.engine import generate_signals
from structure.levels import StructuralSnapshot
from structure.value_area import value_area

_cfg = load_config()


def daily_atr_from_days(day_list, idx, period):
    """Simple mean True Range over the trailing `period` days before idx,
    from full-session H/L/C (same definition as structure/levels.daily_atr)."""
    trs = []
    for k in range(max(1, idx - period), idx + 1):
        cur, prev = day_list[k], day_list[k - 1]
        if None in (cur.full_high, cur.full_low, prev.full_close):
            continue
        tr = max(cur.full_high - cur.full_low,
                 abs(cur.full_high - prev.full_close),
                 abs(cur.full_low - prev.full_close))
        trs.append(tr)
    return sum(trs) / len(trs) if trs else 0.0


def run(path):
    tick_size = _cfg.meta.tick_size
    va_pct = _cfg.structural.va_percent
    atr_period = _cfg.filters.atr_period

    print(f"loading {path} ...")
    days = load_days(path)
    day_list = [days[k] for k in sorted(days)]
    print(f"{len(day_list)} trading days: {day_list[0].day} -> {day_list[-1].day}")

    results = []
    for i in range(1, len(day_list)):
        prior, today = day_list[i - 1], day_list[i]
        if not today.rth_bars or not prior.vap:
            continue
        va = value_area(prior.vap, tick_size, va_pct)
        if va["poc"] is None:
            continue
        snap = StructuralSnapshot(
            trading_date=today.day, pd_va=va,
            ib={"high": None, "low": None, "mid": None},
            weekly={"vpoc": None, "pw_high": None, "pw_low": None},
            overnight={"high": None, "low": None},
            prior_day={"open": None, "high": prior.full_high,
                       "low": prior.full_low, "close": prior.full_close},
        )
        atr = daily_atr_from_days(day_list, i - 1, atr_period)
        if atr <= 0:
            continue
        rth_open = today.rth_bars[0].open
        day_ctx = {
            "rth_open": rth_open, "atr": atr, **va,
            # regime prior available AT THE OPEN, no hindsight: did today
            # open inside or outside prior-day value? (auction theory:
            # outside-open = potential trend day, inside = rotational)
            "open_outside_value": rth_open > va["vah"] or rth_open < va["val"],
        }
        signals = generate_signals(today.rth_bars, snap, tick_size)
        for s in signals:
            tr = simulate_trade(s, today.rth_bars, atr, tick_size)
            results.append((today.day, s, tr, day_ctx))

    _report(results, day_list[0].day, day_list[-1].day)
    return results


def _report(results, first_day, last_day):
    print(f"\n=== RAW signal economics | {first_day} -> {last_day} | "
          f"costs modeled (D-008), 1.5R hybrid (D-006), no filters ===")
    for fam in ("FOLLOW", "FADE", "ALL"):
        rs = [tr.r for (_, s, tr, _c) in results if fam == "ALL" or s.family == fam]
        if not rs:
            print(f"{fam:6s}: n=0")
            continue
        wins = [r for r in rs if r > 0]
        losses = [r for r in rs if r <= 0]
        gross_w = sum(wins)
        gross_l = -sum(losses)
        pf = (gross_w / gross_l) if gross_l > 0 else float("inf")
        # max drawdown on the cumulative R curve, trade order = chronological
        peak = dd = cum = 0.0
        for r in rs:
            cum += r
            peak = max(peak, cum)
            dd = max(dd, peak - cum)
        print(f"{fam:6s}: n={len(rs):3d}  win%={100*len(wins)/len(rs):5.1f}  "
              f"PF={pf:5.2f}  exp={sum(rs)/len(rs):+6.3f}R  totR={sum(rs):+7.2f}  maxDD={dd:6.2f}R")
    print("\nPer-signal log:")
    for day, s, tr, _c in results:
        print(f"  {day} {s.ts.strftime('%H:%M')}  {s.family:6s} "
              f"{'L' if s.direction>0 else 'S'}  entry={tr.entry:9.2f} stop={tr.stop:9.2f} "
              f"risk={tr.risk_pts:5.1f}p  {'scaled' if tr.scaled else '      '}  r={tr.r:+6.2f}  "
              f"[{', '.join(type(e).__name__.replace('Event','') for e in s.events)}]")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "Scid data/MNQU6.CME.scid")
