"""Phase 5 decision fusion (skeleton): regime -> structure -> trigger ->
conflict, in that order (D-002), collapsed into one go/no-go + conviction.

Consumes: a Signal (from signals/engine or signals/momentum), the day's
DayType (structure/daytype, computed once at IB completion), and the
session's conflict state (which directions have already fired today).
Emits a Decision with the full rationale attached -- every skip and every
conviction level is traceable to a named rule, mirroring the "no bare
arrows" visual-layer principle.

All D-013 rules are config flags, DEFAULT OFF (Provisional, in-sample --
dev rule 10). The live conflict veto (D-003) defaults on. With all D-013
flags enabled this module reproduces the gated system measured 2026-07-12:
n=98, 59.2% win, PF 1.93, +0.352R (in-sample upper bound; see
docs/phase2_interim_report.md).
"""
from dataclasses import dataclass, field

from config import load_config

_cfg = load_config()

TAKE, SKIP = "TAKE", "SKIP"
HIGH, MODERATE, LOW = "HIGH", "MODERATE", "LOW"


@dataclass
class Decision:
    action: str               # TAKE | SKIP
    conviction: str            # HIGH | MODERATE | LOW (only meaningful on TAKE)
    rationale: list = field(default_factory=list)


class FusionSession:
    """One trading day's decision state. Feed it every candidate signal in
    chronological order; it tracks conflict state internally."""

    def __init__(self, day_type=None, cfg=None):
        self.day_type = day_type
        self.reasons = set(day_type.reasons) if day_type is not None else set()
        self.seen_directions = set()
        self.f = cfg if cfg is not None else _cfg.fusion

    def decide(self, signal) -> Decision:
        why = []

        # ---- L0 regime gates (D-013, flag-only) -------------------------
        if signal.family == "FOLLOW":
            if self.f["d013_follow_gate"] and "open_drive" not in self.reasons:
                self.seen_directions.add(signal.direction)
                return Decision(SKIP, LOW, ["no open drive: FOLLOW gated off (D-013)"])
            if self.f["d013_narrow_ib_follow_veto"] and "narrow_ib" in self.reasons:
                self.seen_directions.add(signal.direction)
                return Decision(SKIP, LOW, ["narrow IB day: FOLLOW vetoed (D-013)"])
            if "open_drive" in self.reasons:
                why.append("open drive day (D-013 regime pass)")
        elif signal.family == "FADE":
            if self.f["d013_fade_gap_veto"] and "gap_holds" in self.reasons:
                self.seen_directions.add(signal.direction)
                return Decision(SKIP, LOW, ["gap holding: FADE vetoed (D-013)"])
            if "gap_holds" not in self.reasons:
                why.append("no held gap against the fade (D-013 regime pass)")

        # ---- conflict (D-003, live formulation) --------------------------
        if self.f["live_conflict_veto"] and -signal.direction in self.seen_directions:
            self.seen_directions.add(signal.direction)
            return Decision(SKIP, LOW, ["opposing signal already fired today (D-003 live veto)"])
        self.seen_directions.add(signal.direction)

        # ---- conviction (L5: confluence sizes, never magnitude D-005) ----
        why.append(f"trigger: {', '.join(type(e).__name__.replace('Event', '') for e in signal.events)}"
                   if getattr(signal, "events", None) else "trigger event")
        aligned = ("open_drive" in self.reasons and signal.family == "FOLLOW") or \
                  ("gap_holds" not in self.reasons and signal.family == "FADE")
        n_events = len(getattr(signal, "events", []) or [])
        if aligned and n_events >= 2:
            conviction = HIGH
        elif aligned or n_events >= 2:
            conviction = MODERATE
        else:
            conviction = LOW
        return Decision(TAKE, conviction, why)
