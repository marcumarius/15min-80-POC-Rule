"""L0 autopsy: split engine economics by each day-type condition INDIVIDUALLY
(present vs absent), combined + per-period sign consistency."""
from datetime import date
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
    ("Scid data/MNQH26_FUT_CME.scid", date(2025, 12, 19), date(2026, 3, 21), "H26"),
    ("Scid data/MNQM6.CME.scid", date(2026, 3, 20), date(2026, 6, 19), "M6"),
    ("Scid data/MNQU6.CME.scid", date(2026, 5, 29), date(2026, 7, 11), "U6"),
]
CONDS = ["open_drive", "gap_holds", "narrow_ib", "value_migrated", "prior_close_on_extreme"]

rows = []  # (period, reasons, family, r)
for path, d0, d1, label in FILES:
    tick = _cfg.meta.tick_size
    days = load_days(path)
    day_list = [days[k] for k in sorted(days)]
    ib_widths = []
    for i in range(2, len(day_list)):
        prior2, prior, today = day_list[i - 2], day_list[i - 1], day_list[i]
        if today.rth_bars:
            ib = today.rth_bars[:60]
            w = max(b.high for b in ib) - min(b.low for b in ib)
        else:
            w = None
        if not (d0 <= today.day < d1) or not today.rth_bars or not prior.vap:
            if w is not None:
                ib_widths.append(w)
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
        for s in generate_signals(today.rth_bars, snap, tick):
            tr = simulate_trade(s, today.rth_bars, atr, tick)
            rows.append((label, set(dt.reasons), s.family, tr.r))


def exp(rs):
    return sum(rs) / len(rs) if rs else None

for cond in CONDS:
    print(f"--- {cond} ---")
    for fam in ("FOLLOW", "FADE"):
        w = [r for _, rs_, f, r in rows if f == fam and cond in rs_]
        wo = [r for _, rs_, f, r in rows if f == fam and cond not in rs_]
        # per-period sign of (with - without)
        signs = []
        for _, _, _, lab in [(0,0,0,l) for l in ("H26","M6","U6")]:
            pw = [r for p, rs_, f, r in rows if p == lab and f == fam and cond in rs_]
            pwo = [r for p, rs_, f, r in rows if p == lab and f == fam and cond not in rs_]
            if pw and pwo:
                signs.append("+" if exp(pw) > exp(pwo) else "-")
            else:
                signs.append("?")
        ew, ewo = exp(w), exp(wo)
        print(f"  {fam:6s}: with n={len(w):3d} exp={ew:+.3f}R | without n={len(wo):3d} "
              f"exp={ewo:+.3f}R | delta={ew-ewo:+.3f} | period signs {''.join(signs)}")
    print(flush=True)
