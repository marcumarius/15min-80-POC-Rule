"""MOMO: the six-layer momentum engine's L2-L4 core (MomentumTrade.md).

Replaces buy-the-break with buy-the-pullback:
  ARMED    : acceptance beyond a structural edge (L2 initiative, reuses
             features/acceptance) with no L3 veto in the break window.
  PULLBACK : price retraces toward the broken edge WITHOUT full re-entry
             (holds above/below it), on contracting volume and drying delta.
  TRIGGER  : resumption -- a bar closing back in the trend direction off the
             pullback extreme. Stop = the pullback extreme (structure that
             must hold), NOT the VA edge.

L3 vetoes (windowed from the acceptance bar onward, not trigger-bar-only):
absorption against the move, divergence against, exhaustion against. Any
veto while ARMED/PULLBACK kills the setup for that direction for the day.

L0/L1/L5 are the caller's job (day-type gate unproven -- see interim
report; location/no-man's-land from structure/levels; sizing Phase 6).
UNVALIDATED until batched vs the FOLLOW baseline.
"""
from dataclasses import dataclass, field

from config import load_config
from features.absorption import detect_absorption
from features.acceptance import detect_acceptance
from features.delta import detect_divergence
from features.exhaustion import detect_exhaustion

_cfg = load_config()


@dataclass
class MomoSignal:
    direction: int            # +1 long, -1 short
    ts: object
    bar_index: int
    price: float              # trigger bar close (entry reference)
    stop: float               # pullback extreme (structure that must hold)
    level: float              # the broken edge
    events: list = field(default_factory=list)
    family: str = "MOMO"


def generate_momo_signals(bars, snapshot, tick_size, feature_lookback=20,
                           max_pullback_frac=0.75):
    """One session's bars vs snapshot.pd_va. Pullback must hold beyond
    edge + (1-max_pullback_frac) of the break extension; resumption bar
    closes in trend direction. Emits at most one MOMO per direction/day."""
    vah, val = snapshot.pd_va.get("vah"), snapshot.pd_va.get("val")
    if vah is None or val is None or not bars:
        return []

    absorption = detect_absorption(bars, tick_size, lookback=feature_lookback)
    exhaustion = detect_exhaustion(bars, lookback=feature_lookback)
    divergence = detect_divergence(bars)

    def vetoed(direction, i0, i1):
        against = "bearish" if direction > 0 else "bullish"
        return (any(a.index in range(i0, i1 + 1) and a.direction == against for a in absorption)
                or any(d.index in range(i0, i1 + 1) and d.direction == against for d in divergence)
                or any(x.climax_index in range(i0, i1 + 1) and x.direction == against for x in exhaustion))

    signals = []
    for direction, edge in ((1, vah), (-1, val)):
        state, acc_idx, ext, pb_ext = "idle", None, None, None
        for i, b in enumerate(bars):
            if state == "idle":
                acc = detect_acceptance(bars[:i + 1], level=edge, direction=direction,
                                         lookback=feature_lookback)
                if acc is not None and acc.index == i and not vetoed(direction, max(0, i - 3), i):
                    state, acc_idx = "armed", i
                    ext = b.high if direction > 0 else b.low
                    pb_ext = None
            elif state in ("armed", "pullback"):
                if vetoed(direction, acc_idx, i):
                    state = "dead"
                    continue
                # full re-entry through the edge kills the momentum thesis
                if (direction > 0 and b.close < edge) or (direction < 0 and b.close > edge):
                    state = "dead"
                    continue
                new_ext = b.high if direction > 0 else b.low
                extended = (direction > 0 and new_ext > ext) or (direction < 0 and new_ext < ext)
                floor = edge + (1 - max_pullback_frac) * (ext - edge)  # must hold beyond this
                # a pullback bar FAILS to extend the move and dips against it,
                # measured vs the extreme of PRIOR bars -- comparing against an
                # ext already updated with this bar's own high made every bar
                # a "pullback" (bug caught by test_momo_no_signal_without_pullback)
                pulled = (not extended) and (
                    (b.low < ext and b.low >= min(floor, ext)) if direction > 0
                    else (b.high > ext and b.high <= max(floor, ext)))
                if extended:
                    ext = new_ext
                if state == "armed" and pulled and i > acc_idx:
                    state = "pullback"
                    pb_ext = b.low if direction > 0 else b.high
                elif state == "pullback":
                    cur_pb = b.low if direction > 0 else b.high
                    if (direction > 0 and cur_pb < pb_ext) or (direction < 0 and cur_pb > pb_ext):
                        pb_ext = cur_pb
                    # resumption: close back in trend direction off the pullback
                    resumed = (b.close > bars[i - 1].high) if direction > 0 \
                        else (b.close < bars[i - 1].low)
                    if resumed:
                        signals.append(MomoSignal(direction, b.ts, i, b.close,
                                                   pb_ext, edge))
                        state = "dead"
    return signals
