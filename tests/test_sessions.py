from datetime import datetime
from zoneinfo import ZoneInfo

from structure.sessions import in_rth, session_of, trading_day

ET = ZoneInfo("America/New_York")


def _et(y, m, d, h, mi=0, s=0):
    return datetime(y, m, d, h, mi, s, tzinfo=ET)


def test_trading_day_before_boundary_same_date():
    ts = _et(2026, 7, 9, 10, 0)
    assert trading_day(ts) == ts.date()


def test_trading_day_after_boundary_rolls_forward():
    ts = _et(2026, 7, 9, 18, 30)
    assert trading_day(ts).isoformat() == "2026-07-10"


def test_trading_day_exactly_at_boundary_rolls_forward():
    ts = _et(2026, 7, 9, 18, 0, 0)
    assert trading_day(ts).isoformat() == "2026-07-10"


def test_sunday_reopen_maps_to_monday():
    # 2026-07-05 is a Sunday; 18:00+ ET is the futures reopen for Monday.
    ts = _et(2026, 7, 5, 19, 0)
    td = trading_day(ts)
    assert td.isoformat() == "2026-07-06"
    assert td.isoweekday() == 1


def test_session_of_us():
    assert session_of(_et(2026, 7, 9, 10, 0)) == "us"
    assert session_of(_et(2026, 7, 9, 9, 30, 0)) == "us"


def test_session_of_uk():
    assert session_of(_et(2026, 7, 9, 5, 0)) == "uk"
    assert session_of(_et(2026, 7, 9, 3, 0, 0)) == "uk"


def test_session_of_asia_wraps_midnight():
    assert session_of(_et(2026, 7, 9, 20, 0)) == "asia"   # before midnight
    assert session_of(_et(2026, 7, 9, 1, 0)) == "asia"    # after midnight


def test_session_of_post_close_gap_falls_to_asia():
    # 16:00-18:00 ET has no dedicated bucket in the 3-category contract.
    assert session_of(_et(2026, 7, 9, 17, 0)) == "asia"


def test_in_rth_window_boundaries():
    assert in_rth(_et(2026, 7, 9, 9, 30, 0)) is True
    assert in_rth(_et(2026, 7, 9, 9, 29, 59)) is False
    assert in_rth(_et(2026, 7, 9, 16, 0, 0)) is False
    assert in_rth(_et(2026, 7, 9, 15, 59, 59)) is True


def test_in_rth_consistent_across_dst_regimes():
    winter = _et(2026, 1, 15, 9, 30, 0)  # EST, UTC-5
    summer = _et(2026, 7, 15, 9, 30, 0)  # EDT, UTC-4
    assert winter.utcoffset() != summer.utcoffset()
    assert in_rth(winter) is True
    assert in_rth(summer) is True


def test_in_rth_across_spring_forward_transition_day():
    # 2026-03-08: US DST spring-forward (2am -> 3am ET).
    before_open = _et(2026, 3, 8, 9, 29, 59)
    at_open = _et(2026, 3, 8, 9, 30, 0)
    assert in_rth(before_open) is False
    assert in_rth(at_open) is True


def test_in_rth_across_fall_back_transition_day():
    # 2026-11-01: US DST fall-back (2am -> 1am ET, repeated hour).
    at_open = _et(2026, 11, 1, 9, 30, 0)
    assert in_rth(at_open) is True
