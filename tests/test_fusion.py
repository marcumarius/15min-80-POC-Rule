"""Phase 5 fusion decision tests -- gate/veto/conflict/conviction logic."""
from datetime import datetime
from zoneinfo import ZoneInfo

from fusion.decision import Decision, FusionSession, HIGH, SKIP, TAKE
from signals.engine import Signal
from structure.daytype import DayType

ET = ZoneInfo("America/New_York")
_TS = datetime(2026, 7, 8, 10, 45, tzinfo=ET)

ALL_ON = {"d013_follow_gate": True, "d013_fade_gap_veto": True,
          "d013_narrow_ib_follow_veto": True, "live_conflict_veto": True}
ALL_OFF = {"d013_follow_gate": False, "d013_fade_gap_veto": False,
           "d013_narrow_ib_follow_veto": False, "live_conflict_veto": False}


class _Ev:
    pass


def _sig(family, direction, n_events=1):
    return Signal(family, direction, _TS, 10, 100.0, 99.0, [_Ev() for _ in range(n_events)])


def test_follow_gated_off_without_open_drive():
    s = FusionSession(DayType(0, []), cfg=ALL_ON)
    d = s.decide(_sig("FOLLOW", 1))
    assert d.action == SKIP
    assert "D-013" in d.rationale[0]


def test_follow_taken_on_open_drive_day():
    s = FusionSession(DayType(1, ["open_drive"]), cfg=ALL_ON)
    d = s.decide(_sig("FOLLOW", 1, n_events=2))
    assert d.action == TAKE
    assert d.conviction == HIGH   # regime-aligned + 2 events


def test_fade_vetoed_on_gap_holds_day():
    s = FusionSession(DayType(1, ["gap_holds"]), cfg=ALL_ON)
    d = s.decide(_sig("FADE", -1))
    assert d.action == SKIP


def test_narrow_ib_vetoes_follow():
    s = FusionSession(DayType(2, ["open_drive", "narrow_ib"]), cfg=ALL_ON)
    d = s.decide(_sig("FOLLOW", 1))
    assert d.action == SKIP


def test_live_conflict_veto_blocks_opposing_second_signal():
    s = FusionSession(DayType(1, ["open_drive"]), cfg=ALL_ON)
    assert s.decide(_sig("FOLLOW", 1)).action == TAKE
    d = s.decide(_sig("FADE", -1))
    assert d.action == SKIP
    assert "D-003" in d.rationale[0]


def test_skipped_signal_still_counts_for_conflict_state():
    # a FOLLOW gated off by D-013 still SIGNALS direction -- a later opposing
    # FADE must still see the conflict (the information existed live)
    s = FusionSession(DayType(0, []), cfg=ALL_ON)
    assert s.decide(_sig("FOLLOW", 1)).action == SKIP        # gated, but seen
    assert s.decide(_sig("FADE", -1)).action == SKIP          # conflict veto


def test_all_flags_off_takes_everything():
    s = FusionSession(DayType(0, []), cfg=ALL_OFF)
    assert s.decide(_sig("FOLLOW", 1)).action == TAKE
    assert s.decide(_sig("FADE", -1)).action == TAKE          # no conflict veto either
