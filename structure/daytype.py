"""L0 regime gate (MomentumTrade.md): "can today even trend?"

Evaluated ONCE at IB completion (open + first ib_minutes of RTH bars) --
everything here is knowable at that moment, no hindsight. Returns a
trend-capability score built from the five pass conditions in
MomentumTrade.md L0. The score is reported in buckets by the batch; no
hard cutoff is baked in until the split is measured (dev rule 10).
"""
from dataclasses import dataclass, field

from config import load_config

_cfg = load_config()


@dataclass
class DayType:
    score: int                 # 0..5, count of trend-capable conditions met
    reasons: list = field(default_factory=list)


def classify_day(rth_bars_ib, prior_day: dict, pd_va: dict, prior2_va: dict,
                  atr: float, avg_ib_width: float) -> DayType:
    """`rth_bars_ib`: today's RTH minute bars up to IB completion only.
    `prior_day`: {open, high, low, close} of the PD reference session.
    `pd_va` / `prior2_va`: value areas of the prior and day-before-prior
    sessions (for value migration). `avg_ib_width`: trailing mean IB width.
    """
    d = DayType(0)
    if not rth_bars_ib or atr <= 0:
        return d
    open_p = rth_bars_ib[0].open
    last = rth_bars_ib[-1]

    # 1. open drive: first ~15 minutes travel one-directionally
    k = min(15, len(rth_bars_ib))
    seg = rth_bars_ib[:k]
    hi = max(b.high for b in seg)
    lo = min(b.low for b in seg)
    travel = seg[-1].close - open_p
    if abs(travel) > 0.15 * atr and (hi - lo) > 0 and \
            ((travel > 0 and seg[-1].close > hi - 0.25 * (hi - lo)) or
             (travel < 0 and seg[-1].close < lo + 0.25 * (hi - lo))):
        d.score += 1
        d.reasons.append("open_drive")

    # 2. gap that holds: meaningful gap vs prior close, unfilled at IB end
    pc = prior_day.get("close")
    if pc:
        gap = open_p - pc
        if abs(gap) > 0.3 * atr:
            filled = (min(b.low for b in rth_bars_ib) <= pc) if gap > 0 \
                else (max(b.high for b in rth_bars_ib) >= pc)
            if not filled:
                d.score += 1
                d.reasons.append("gap_holds")

    # 3. narrow IB (relative): narrow initial balance breaks out more easily
    ib_width = max(b.high for b in rth_bars_ib) - min(b.low for b in rth_bars_ib)
    if avg_ib_width > 0 and ib_width < 0.8 * avg_ib_width:
        d.score += 1
        d.reasons.append("narrow_ib")

    # 4. value migration: prior VA separated from day-before-prior VA
    if all(pd_va.get(x) is not None for x in ("vah", "val")) and \
            all(prior2_va.get(x) is not None for x in ("vah", "val")):
        if pd_va["val"] > prior2_va["vah"] or pd_va["vah"] < prior2_va["val"]:
            d.score += 1
            d.reasons.append("value_migrated")

    # 5. prior day closed on its extreme (top/bottom 20% of its range)
    ph, pl = prior_day.get("high"), prior_day.get("low")
    if pc and ph and pl and ph > pl:
        pos = (pc - pl) / (ph - pl)
        if pos > 0.8 or pos < 0.2:
            d.score += 1
            d.reasons.append("prior_close_on_extreme")

    return d
