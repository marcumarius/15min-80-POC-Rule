"""Trade outcome simulation: the D-006 1.5R scale-and-trail hybrid with
D-008 costs. Turns a Signal + the bars after it into a result in R.

Model (documented so results are interpretable, per CLAUDE.md rule 5):
  Entry : signal bar close +/- entry_slippage_ticks in the trade direction.
  Stop  : structural -- at the signal's VA edge (level) -/+ a buffer of
          max(0.08 * ATR, 8 ticks), the legacy DrawGuides buffer; widened to
          min_stop_pts if closer (sizing sanity floor).
  R     : |entry - stop| in points.
  Tgt1  : entry + dir * tgt1_R * R. On touch: bank scale_out_fraction at the
          limit (no slippage on a resting limit), stop -> breakeven, trail on.
  Trail : ratcheting max(swing extreme of last 3 bars, close -/+ 0.10*ATR),
          never below breakeven -- mirrors the legacy trail exactly.
  Stops : filled with stop_slippage_ticks against us (stop-market realism).
  Same-bar ambiguity: if a bar touches both stop and target, the STOP is
          assumed first (pessimistic -- never flatter the result).
  EOD   : any remainder exits at the last bar's close (no overnight holds).
  Costs : commission_round_trip dollars per contract, converted to points
          via point_value and charged once per unit.

Result R = net points / R. This is a per-signal outcome model for comparing
trigger quality -- NOT a portfolio simulation (no sizing, no compounding,
no prop-drawdown logic; those are Phase 6).
"""
from dataclasses import dataclass
from datetime import datetime

from config import load_config

_cfg = load_config()


@dataclass
class TradeResult:
    family: str
    direction: int
    entry_ts: datetime
    entry: float
    stop: float
    risk_pts: float
    exit_ts: datetime
    scaled: bool              # did tgt1 get hit?
    net_pts: float            # per contract-unit, after slippage + commission
    r: float                  # net_pts / risk_pts


def simulate_trade(signal, bars: list, atr: float, tick_size: float) -> TradeResult:
    """Simulate one signal on `bars` (the same bar list the engine saw);
    entry at the close of bars[signal.bar_index], managed to end of list."""
    d = signal.direction
    entry_slip = _cfg.costs.entry_slippage_ticks * tick_size
    stop_slip = _cfg.costs.stop_slippage_ticks * tick_size
    commission_pts = _cfg.costs.commission_round_trip / _cfg.meta.point_value
    scale_frac = _cfg.management.scale_out_fraction
    tgt1_r = _cfg.management.tgt1_R
    min_stop = _cfg.management.min_stop_pts
    atr_floor = _cfg.management.runner_trail["atr_floor"]

    entry = signal.price + d * entry_slip
    explicit_stop = getattr(signal, "stop", None)
    if explicit_stop is not None:
        # MOMO-style signals carry their own structural stop (the pullback
        # extreme -- "the structure that must hold", MomentumTrade.md L6);
        # a small buffer beyond it, min-stop floor still applies.
        stop = explicit_stop - d * 2 * tick_size
    else:
        buffer = max(0.08 * atr, 8 * tick_size)
        stop = signal.level - d * buffer
        # cap at max_stop_atr x ATR: on gap days the structural edge can be
        # hundreds of points away, distorting R (interim report issue 1) --
        # take the TIGHTER of structural and ATR-capped.
        atr_stop = entry - d * _cfg.management.max_stop_atr * atr
        if d > 0:
            stop = max(stop, atr_stop)
        else:
            stop = min(stop, atr_stop)
    if abs(entry - stop) < min_stop:
        stop = entry - d * min_stop
    risk = abs(entry - stop)
    tgt1 = entry + d * tgt1_r * risk

    scaled = False
    banked = 0.0              # points banked by the tgt1 scale, weighted
    trail = stop
    exit_ts = bars[-1].ts
    remainder_exit = None

    for i in range(signal.bar_index + 1, len(bars)):
        b = bars[i]
        stop_now = trail if scaled else stop
        stop_hit = (b.low <= stop_now) if d > 0 else (b.high >= stop_now)
        tgt_hit = (b.high >= tgt1) if d > 0 else (b.low <= tgt1)

        if stop_hit:  # pessimistic: stop before target on ambiguous bars
            remainder_exit = stop_now - d * stop_slip
            exit_ts = b.ts
            break
        if not scaled and tgt_hit:
            banked = scale_frac * (tgt1 - entry) * d
            scaled = True
            trail = entry  # breakeven
        if scaled:
            lows = [bars[j].low for j in range(max(signal.bar_index, i - 2), i + 1)]
            highs = [bars[j].high for j in range(max(signal.bar_index, i - 2), i + 1)]
            swing = min(lows) if d > 0 else max(highs)
            atr_stop = b.close - d * atr_floor * atr
            cand = max(swing, atr_stop) if d > 0 else min(swing, atr_stop)
            if d > 0:
                trail = max(trail, cand)
            else:
                trail = min(trail, cand)

    if remainder_exit is None:
        remainder_exit = bars[-1].close   # EOD flat

    remainder_frac = (1.0 - scale_frac) if scaled else 1.0
    net = banked + remainder_frac * (remainder_exit - entry) * d - commission_pts
    return TradeResult(signal.family, d, signal.ts, entry, stop, risk,
                       exit_ts, scaled, net, net / risk if risk > 0 else 0.0)
