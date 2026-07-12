"""Event-based FOLLOW/FADE trigger state machine (Phase 2).

Replaces the legacy time-based triggers (D-007): no "N consecutive closes,"
no clock windows as triggers. Time may GATE (the caller chooses which
session's bars to feed in) but never TRIGGER.

The machine walks bars in order against a frozen prior-day value area
(StructuralSnapshot.pd_va) and emits Signal candidates when an order-flow
EVENT confirms the structural setup:

FOLLOW (initiative continuation beyond value)
  Armed  : price trades fully beyond VAH (long) / VAL (short).
  Trigger: trade-and-rest acceptance beyond the edge (features/acceptance)
           AND no fresh absorption against the move on the trigger bar's
           side. Intent per CLAUDE.md §1.3: initiative confirmed, not a
           close count.

FADE (80% Rule mean reversion after a failed excursion)
  Armed  : price trades fully beyond a VA edge (the excursion).
  Trigger: price re-enters value AND the excursion has been shown to FAIL
           by at least one order-flow event at the extreme -- absorption
           against the excursion, delta/CVD divergence into the extreme, or
           exhaustion of the excursion's initiative. Re-entry alone (the
           legacy "first close back inside") is NOT enough.

Every Signal carries the event(s) that fired it, so a human or the Phase 5
fusion engine can always see WHY -- no bare arrows (visual-layer design rule).

REV is deliberately absent: per CLAUDE.md §1.3's ordering note it comes
after FOLLOW/FADE are validated.

NOT YET VALIDATED as an edge -- this is machinery. Economics (win rate,
expectancy, costs) are Phase 7's job; nothing here has been backtested yet
and no default here should be trusted as tuned (dev rule: evidence before
trust).
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from config import load_config
from features.absorption import detect_absorption
from features.acceptance import detect_acceptance
from features.delta import detect_divergence
from features.exhaustion import detect_exhaustion

_cfg = load_config()


@dataclass
class Signal:
    family: str               # "FOLLOW" | "FADE"
    direction: int             # +1 long, -1 short
    ts: datetime
    bar_index: int
    price: float               # close of the trigger bar
    level: float               # the VA edge the setup keyed off
    events: list = field(default_factory=list)   # the order-flow events that fired it

    def why(self) -> str:
        """One-line human-readable rationale -- every marker traceable."""
        names = ", ".join(type(e).__name__.replace("Event", "") for e in self.events)
        side = "LONG" if self.direction > 0 else "SHORT"
        return f"{self.family} {side} @ {self.price} (level {self.level}): {names}"


def _fully_beyond(bar, level: float, direction: int) -> bool:
    return bar.low > level if direction > 0 else bar.high < level


def _back_inside(bar, vah: float, val: float) -> bool:
    return val < bar.close < vah


def generate_signals(bars: list, snapshot, tick_size: float,
                      feature_lookback: int = 20,
                      extra_fade_evidence: list = None) -> list:
    """Run the FOLLOW/FADE state machine over `bars` (one session, in order)
    against snapshot.pd_va. Returns Signals in firing order.

    The caller owns session gating (which bars to pass) and any downstream
    filtering (no-man's-land D-004, conflict veto D-003) -- this module only
    answers "did a structural setup get order-flow confirmation, and by
    which event?"

    `extra_fade_evidence`: optional ts-stamped events from a FINER bar basis
    (e.g. absorption detected on 800-trade bars -- unmeasurable on minute
    bars, see interim report). Each needs `.ts` (tz-aware) and `.direction`
    ("bullish"/"bearish"). Matched into the FADE failure-evidence window by
    TIME (excursion-extreme bar's ts through the re-entry bar's ts), same
    direction convention as the native detectors.
    """
    vah, val = snapshot.pd_va.get("vah"), snapshot.pd_va.get("val")
    if vah is None or val is None or not bars:
        return []

    # Feature passes over the whole session (indices align with `bars`).
    absorption = detect_absorption(bars, tick_size, lookback=feature_lookback)
    exhaustion = detect_exhaustion(bars, lookback=feature_lookback)
    divergence = detect_divergence(bars)
    absorption_by_idx = {}
    for e in absorption:
        absorption_by_idx.setdefault(e.index, []).append(e)

    signals = []
    # Per-direction state: None -> "armed" (excursion seen) -> fired-once.
    follow_state = {1: None, -1: None}
    fade_state = {1: None, -1: None}    # key = direction of the FADE trade itself
    excursion_extreme_idx = {1: None, -1: None}   # trade-direction-keyed excursion bookkeeping

    for i, bar in enumerate(bars):
        for direction, edge in ((1, vah), (-1, val)):
            fade_dir = -direction   # excursion beyond VAH -> FADE is short, and mirror

            # ---- arm on excursion (full bar beyond the edge) ----
            if _fully_beyond(bar, edge, direction):
                if follow_state[direction] is None:
                    follow_state[direction] = "armed"
                if fade_state[fade_dir] is None:
                    fade_state[fade_dir] = "armed"
                # track the excursion's most extreme bar for event matching
                prev = excursion_extreme_idx[fade_dir]
                if prev is None or (direction > 0 and bar.high > bars[prev].high) \
                        or (direction < 0 and bar.low < bars[prev].low):
                    excursion_extreme_idx[fade_dir] = i

            # ---- FOLLOW trigger: acceptance beyond the edge, no absorption against ----
            if follow_state[direction] == "armed":
                acc = detect_acceptance(bars[:i + 1], level=edge, direction=direction,
                                         lookback=feature_lookback)
                if acc is not None and acc.index == i:
                    against = [a for a in absorption_by_idx.get(i, [])
                               if (direction > 0 and a.direction == "bearish")
                               or (direction < 0 and a.direction == "bullish")]
                    if not against:
                        signals.append(Signal("FOLLOW", direction, bar.ts, i, bar.close,
                                              edge, [acc]))
                        follow_state[direction] = "fired"

            # ---- FADE trigger: re-entry + evidence the excursion FAILED ----
            if fade_state[fade_dir] == "armed" and _back_inside(bar, vah, val):
                ext_idx = excursion_extreme_idx[fade_dir]
                failure_events = []
                if ext_idx is not None:
                    window = range(ext_idx, i + 1)
                    # finer-bar evidence (e.g. 800t absorption), matched by TIME
                    if extra_fade_evidence:
                        t0, t1 = bars[ext_idx].ts, bar.ts
                        want = "bearish" if fade_dir < 0 else "bullish"
                        for ev in extra_fade_evidence:
                            if t0 <= ev.ts <= t1 and ev.direction == want:
                                failure_events.append(ev)
                    # absorption against the excursion at/after its extreme
                    for j in window:
                        for a in absorption_by_idx.get(j, []):
                            if (fade_dir < 0 and a.direction == "bearish") \
                                    or (fade_dir > 0 and a.direction == "bullish"):
                                failure_events.append(a)
                    # divergence into the extreme (bearish div supports FADE short, mirror long)
                    for d in divergence:
                        if d.index in window and \
                                ((fade_dir < 0 and d.direction == "bearish")
                                 or (fade_dir > 0 and d.direction == "bullish")):
                            failure_events.append(d)
                    # exhaustion of the excursion's initiative
                    for x in exhaustion:
                        if x.climax_index in window and \
                                ((fade_dir < 0 and x.direction == "bearish")
                                 or (fade_dir > 0 and x.direction == "bullish")):
                            failure_events.append(x)
                if failure_events:
                    signals.append(Signal("FADE", fade_dir, bar.ts, i, bar.close,
                                          edge, failure_events))
                    fade_state[fade_dir] = "fired"

    return signals
