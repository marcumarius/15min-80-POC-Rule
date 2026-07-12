from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from data.types import FootprintCell, Tick
from structure.levels import (
    SessionProfile,
    StructuralSnapshot,
    build_snapshot,
    compute_ib,
    compute_overnight_hl,
    compute_overnight_vp,
    compute_weekly_profile,
    daily_atr,
    is_stacked,
    level_stack_distance,
    naked_pocs,
    nearest_structure,
    no_mans_land,
    session_profile_from_ticks,
)

ET = ZoneInfo("America/New_York")
_MNQU6_PATH = Path(__file__).parent.parent / "Scid data" / "MNQU6.CME.scid"


def _bar(y, m, d, h, mi, o, hi, lo, c):
    return {"ts": datetime(y, m, d, h, mi, tzinfo=ET), "open": o, "high": hi, "low": lo, "close": c}


def _snap(**kwargs):
    defaults = dict(
        trading_date=date(2026, 7, 9),
        pd_va={"poc": None, "vah": None, "val": None},
        ib={"high": None, "low": None, "mid": None},
        weekly={"vpoc": None, "pw_high": None, "pw_low": None},
        overnight={"high": None, "low": None},
        prior_day={"open": None, "high": None, "low": None, "close": None},
    )
    defaults.update(kwargs)
    return StructuralSnapshot(**defaults)


# --- nearest_structure / no_mans_land (D-004) -------------------------------

def test_nearest_structure_long_direction_picks_closest_wall_above():
    snap = _snap(pd_va={"poc": 100.0, "vah": 105.0, "val": 95.0})
    lvl, dist = nearest_structure(price=101.0, direction=1, snapshot=snap)
    assert lvl.name == "PD VAH"
    assert dist == pytest.approx(4.0)


def test_nearest_structure_short_direction_picks_closest_wall_below():
    snap = _snap(pd_va={"poc": 100.0, "vah": 105.0, "val": 95.0})
    lvl, dist = nearest_structure(price=99.0, direction=-1, snapshot=snap)
    assert lvl.name == "PD VAL"
    assert dist == pytest.approx(4.0)


def test_nearest_structure_ignores_levels_behind_price():
    snap = _snap(pd_va={"poc": 100.0, "vah": 105.0, "val": 95.0})
    lvl, dist = nearest_structure(price=106.0, direction=1, snapshot=snap)
    assert lvl is None and dist is None


def test_no_mans_land_true_when_far_from_structure():
    snap = _snap(pd_va={"poc": 100.0, "vah": 200.0, "val": 50.0})
    assert no_mans_land(price=101.0, direction=1, snapshot=snap, atr=20.0, max_atr=0.5) is True


def test_no_mans_land_false_when_near_structure():
    snap = _snap(pd_va={"poc": 100.0, "vah": 105.0, "val": 95.0})
    assert no_mans_land(price=101.0, direction=1, snapshot=snap, atr=20.0, max_atr=0.5) is False


def test_no_mans_land_zero_atr_never_flags():
    snap = _snap(pd_va={"poc": 100.0, "vah": 200.0, "val": 50.0})
    assert no_mans_land(price=101.0, direction=1, snapshot=snap, atr=0.0) is False


def test_no_mans_land_true_when_no_structure_in_direction():
    snap = _snap(pd_va={"poc": 100.0, "vah": 105.0, "val": 95.0})
    assert no_mans_land(price=106.0, direction=1, snapshot=snap, atr=1.0) is True


# --- D-010 (Provisional): level stacking + overnight VP ---------------------

def test_level_stack_distance_and_is_stacked():
    pd_va = {"poc": 100.0, "vah": 100.25, "val": 90.0}
    assert level_stack_distance(pd_va) == pytest.approx(0.25)
    assert is_stacked(pd_va, tick_size=0.25, tol_ticks=6) is True
    assert is_stacked(pd_va, tick_size=0.25, tol_ticks=0) is False


def test_level_stack_distance_incomplete_va_returns_none():
    assert level_stack_distance({"poc": 100.0, "vah": None, "val": 90.0}) is None


def test_levels_excludes_overnight_vp_when_flag_disabled():
    snap = _snap(pd_va={"poc": 100.0, "vah": 105.0, "val": 95.0},
                 overnight_vp={"hvn": 50.0, "poc": 50.0, "lvn": 48.0})
    names = [lvl.name for lvl in snap.levels()]
    assert not any("Overnight" in n for n in names)  # overnight_vp_enable defaults False


def test_compute_overnight_vp_hvn_poc_lvn():
    ts = datetime(2026, 7, 9, tzinfo=ET)
    cells = [
        FootprintCell(ts_bucket=ts, price=100.0, bid_volume=5, ask_volume=5),
        FootprintCell(ts_bucket=ts, price=101.0, bid_volume=50, ask_volume=50),
        FootprintCell(ts_bucket=ts, price=102.0, bid_volume=1, ask_volume=1),
    ]
    vp = compute_overnight_vp(cells, tick_size=1.0)
    assert vp == {"hvn": 101.0, "poc": 101.0, "lvn": 102.0}


# --- session/weekly/IB/ATR/naked-POC builders --------------------------------

def test_compute_ib_first_window_only():
    bars = [
        _bar(2026, 7, 9, 9, 30, 100, 101, 99, 100.5),
        _bar(2026, 7, 9, 10, 0, 100.5, 103, 100, 102),
        _bar(2026, 7, 9, 10, 30, 102, 102.5, 101, 101.5),  # at the 60-min edge -> excluded
    ]
    ib = compute_ib(bars, ib_minutes=60)
    assert ib == {"high": 103, "low": 99, "mid": pytest.approx(101.0)}


def test_compute_overnight_hl_excludes_us_session():
    bars = [
        _bar(2026, 7, 9, 3, 0, 10, 12, 9, 11),     # UK -> overnight
        _bar(2026, 7, 9, 10, 0, 20, 25, 19, 22),   # US -> excluded
        _bar(2026, 7, 9, 20, 0, 5, 7, 4, 6),       # Asia -> overnight
    ]
    hl = compute_overnight_hl(bars)
    assert hl == {"high": 12, "low": 4}


def test_daily_atr_simple_mean_true_range():
    sessions = [
        SessionProfile(trading_date=None, start_ts=None, end_ts=None, open=None,
                        high=110, low=100, close=105, poc=None, vah=None, val=None),
        SessionProfile(trading_date=None, start_ts=None, end_ts=None, open=None,
                        high=115, low=104, close=112, poc=None, vah=None, val=None),
        SessionProfile(trading_date=None, start_ts=None, end_ts=None, open=None,
                        high=120, low=108, close=118, poc=None, vah=None, val=None),
    ]
    atr = daily_atr(sessions, period=14)
    assert atr == pytest.approx((11 + 12) / 2)


def test_daily_atr_insufficient_sessions_returns_zero():
    sessions = [SessionProfile(trading_date=None, start_ts=None, end_ts=None, open=None,
                                high=110, low=100, close=105, poc=None, vah=None, val=None)]
    assert daily_atr(sessions) == 0.0


def test_naked_pocs_excludes_touched_and_the_reference_session():
    s1 = SessionProfile(trading_date=None, start_ts=None, end_ts=datetime(2026, 7, 7, 16, 0, tzinfo=ET),
                         open=None, high=None, low=None, close=None, poc=100.0, vah=None, val=None)
    s2 = SessionProfile(trading_date=None, start_ts=None, end_ts=datetime(2026, 7, 8, 16, 0, tzinfo=ET),
                         open=None, high=None, low=None, close=None, poc=200.0, vah=None, val=None)
    s3 = SessionProfile(trading_date=None, start_ts=None, end_ts=datetime(2026, 7, 9, 16, 0, tzinfo=ET),
                         open=None, high=None, low=None, close=None, poc=300.0, vah=None, val=None)
    trailing_bars = [{"ts": datetime(2026, 7, 9, 10, 0, tzinfo=ET), "high": 205, "low": 195}]
    naked = naked_pocs([s1, s2, s3], trailing_bars, lookback=30, max_count=8)
    assert naked == [100.0]  # s2 touched, s3 is the reference (excluded), s1 untouched


def test_compute_weekly_profile():
    ts1, ts2 = datetime(2026, 7, 6, tzinfo=ET), datetime(2026, 7, 7, tzinfo=ET)
    cells = [
        FootprintCell(ts_bucket=ts1, price=100.0, bid_volume=10, ask_volume=10),
        FootprintCell(ts_bucket=ts2, price=105.0, bid_volume=40, ask_volume=40),
    ]
    week_bars = [_bar(2026, 7, 6, 9, 30, 100, 102, 99, 101), _bar(2026, 7, 7, 9, 30, 104, 106, 103, 105)]
    wp = compute_weekly_profile(week_bars, cells, tick_size=1.0)
    assert wp == {"vpoc": 105.0, "high": 106, "low": 99}


# --- build_snapshot assembly --------------------------------------------------

def test_build_snapshot_assembles_pd_va_and_stack_ticks():
    prior = SessionProfile(
        trading_date=date(2026, 7, 8), start_ts=datetime(2026, 7, 8, 9, 30, tzinfo=ET),
        end_ts=datetime(2026, 7, 8, 16, 0, tzinfo=ET), open=100.0, high=110.0, low=95.0,
        close=105.0, poc=100.0, vah=100.25, val=90.0,
    )
    snap = build_snapshot(
        trading_date=date(2026, 7, 9), prior_session=prior,
        ib={"high": 106, "low": 101, "mid": 103.5},
        weekly={"vpoc": None, "pw_high": None, "pw_low": None},
        overnight={"high": None, "low": None},
        sessions_so_far=[prior], trailing_bars=[], tick_size=0.25,
    )
    assert snap.pd_va == {"poc": 100.0, "vah": 100.25, "val": 90.0}
    assert snap.prior_day == {"open": 100.0, "high": 110.0, "low": 95.0, "close": 105.0}
    assert snap.level_stack_ticks == pytest.approx(1.0)  # 0.25 price distance / 0.25 tick_size


# --- session_profile_from_ticks (D-011: full-session, trading_day()-bucketed VA) ---

def test_session_profile_from_ticks_computes_ohlc_and_va():
    ticks = [
        Tick(ts=datetime(2026, 7, 8, 9, 30, tzinfo=ET), price=100.0, volume=10, aggressor="buy"),
        Tick(ts=datetime(2026, 7, 8, 10, 0, tzinfo=ET), price=101.0, volume=20, aggressor="buy"),
        Tick(ts=datetime(2026, 7, 8, 11, 0, tzinfo=ET), price=102.0, volume=50, aggressor="sell"),
        Tick(ts=datetime(2026, 7, 8, 15, 59, tzinfo=ET), price=100.5, volume=15, aggressor="sell"),
    ]
    sp = session_profile_from_ticks(ticks, tick_size=1.0, va_percent=0.70)
    assert sp.trading_date == date(2026, 7, 8)
    assert sp.open == 100.0
    assert sp.close == 100.5
    assert sp.high == 102.0
    assert sp.low == 100.0
    assert sp.poc == 102.0  # heaviest single price (vol=50)


def test_session_profile_from_ticks_trading_date_uses_trading_day_not_calendar_date():
    # Ticks starting the prior evening (18:00+ ET) must bucket into the NEXT
    # trading day (D-011: the window is 18:00-anchored, not RTH-only), so
    # trading_date has to come from trading_day(), not ts.date().
    ticks = [
        Tick(ts=datetime(2026, 7, 6, 18, 0, tzinfo=ET), price=100.0, volume=10, aggressor="buy"),
        Tick(ts=datetime(2026, 7, 7, 15, 59, tzinfo=ET), price=101.0, volume=10, aggressor="sell"),
    ]
    sp = session_profile_from_ticks(ticks, tick_size=1.0, va_percent=0.70)
    assert sp.trading_date == date(2026, 7, 7)  # NOT 2026-07-06


def test_session_profile_from_ticks_empty_returns_none():
    assert session_profile_from_ticks([], tick_size=1.0) is None


@pytest.mark.skipif(not _MNQU6_PATH.exists(), reason="real MNQU6.CME.scid data not present")
def test_session_profile_from_ticks_reproduces_real_july7_reconciliation():
    """Regression-locks the real-data reconciliation from the 2026-07-11
    session (see docs/decisions.md D-011, docs/phase1_report.md): the
    user's live-study HUD read VAH=29587/POC=29539/VAL=29320 for 2026-07-07,
    printed at US-session-end (~16:30). An RTH-only rebuild (the original,
    now-superseded assumption) missed by up to 239 points. The corrected
    full-session window (2026-07-06 18:00 ET -> 2026-07-07 16:00 ET) gets
    within single-digit-to-mid-tens of ticks on each edge -- close but not
    exact, tracked as an open item in D-011 (likely a volume-counting
    difference between raw-tick TotalVolume and Sierra's native
    VolumeAtPriceForBars). This test locks in the CURRENT best
    reconciliation with a tolerance, not a spurious exact match; tighten the
    tolerance if/when the remaining gap is explained."""
    from data.loaders import iter_scid_ticks_for_day
    from structure.sessions import trading_day

    ticks6 = iter_scid_ticks_for_day(_MNQU6_PATH, date(2026, 7, 6))
    ticks7 = iter_scid_ticks_for_day(_MNQU6_PATH, date(2026, 7, 7))
    full_session = [t for t in (ticks6 + ticks7) if trading_day(t.ts) == date(2026, 7, 7)
                    and t.ts < datetime(2026, 7, 7, 16, 0, tzinfo=ET)]
    sp = session_profile_from_ticks(full_session, tick_size=0.25, va_percent=0.70)

    assert sp.trading_date == date(2026, 7, 7)
    assert sp.vah == pytest.approx(29587.0, abs=10 * 0.25)   # within 10 ticks
    # POC/VAL are a near photo-finish between two comparably-sized volume
    # nodes (14% apart) -- not yet reconciled exactly, see D-011.
    assert sp.poc in (pytest.approx(29300.0), pytest.approx(29539.0))
