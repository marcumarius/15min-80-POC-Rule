"""Structural snapshot + no-man's-land distance.

Phase 1 deliverable (section 3.4). Builds PD VA, IB, weekly VPOC + PW H/L,
overnight H/L, prior-day OHLC, naked POCs, VWAP +/- SD anchor, daily ATR.
no_mans_land() implements Decision D-004 (distance-to-structure filter).

D-010 (Provisional, docs/decisions.md): overnight (Asia+UK) volume profile
and PD POC-to-VA-edge "stacking" are flag-only additions -- computed only
when asked for, never a hard filter, and excluded from levels() unless
`overnight_vp_enable` is set.
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Iterable, Optional

from config import load_config
from data.types import Level
from structure.sessions import session_of
from structure.value_area import value_area, volume_at_price

_cfg = load_config()


@dataclass
class SessionProfile:
    """One RTH session's OHLC + true value area. The per-day building block
    that StructuralSnapshot assembles prior-day references from."""
    trading_date: date
    start_ts: datetime
    end_ts: datetime
    open: float
    high: float
    low: float
    close: float
    poc: Optional[float]
    vah: Optional[float]
    val: Optional[float]


@dataclass
class StructuralSnapshot:
    trading_date: date
    pd_va: dict                                # {poc, vah, val}
    ib: dict                                    # {high, low, mid}
    weekly: dict                                # {vpoc, pw_high, pw_low}
    overnight: dict                             # {high, low}
    prior_day: dict                             # {open, high, low, close}
    naked_pocs: list = field(default_factory=list)
    vwap_anchor_ts: Optional[datetime] = None
    atr_daily: float = 0.0
    overnight_vp: Optional[dict] = None         # D-010, flag-only: {hvn, poc, lvn}
    level_stack_ticks: Optional[float] = None   # D-010, flag-only

    def levels(self) -> list:
        """Flatten every populated structural reference into Level records,
        for nearest_structure()/no_mans_land() distance queries."""
        out = []
        for label, key in (("PD POC", "poc"), ("PD VAH", "vah"), ("PD VAL", "val")):
            if self.pd_va.get(key) is not None:
                out.append(Level(label, self.pd_va[key], "va"))
        for label, key in (("IB High", "high"), ("IB Low", "low")):
            if self.ib.get(key) is not None:
                out.append(Level(label, self.ib[key], "ib"))
        for label, key in (("Weekly VPOC", "vpoc"), ("PW High", "pw_high"), ("PW Low", "pw_low")):
            if self.weekly.get(key) is not None:
                out.append(Level(label, self.weekly[key], "weekly"))
        for i, poc in enumerate(self.naked_pocs):
            out.append(Level(f"Naked POC {i}", poc, "session"))
        if _cfg.structural.overnight_vp_enable and self.overnight_vp:
            for label, key in (("Overnight HVN", "hvn"), ("Overnight POC", "poc"), ("Overnight LVN", "lvn")):
                if self.overnight_vp.get(key) is not None:
                    out.append(Level(label, self.overnight_vp[key], "overnight_vp"))
        return out


# ---------------------------------------------------------------------------
# Session-level builders (pure functions; wire real bars/cells through these)
# ---------------------------------------------------------------------------

def compute_session_profile(bars: list, cells: Iterable, tick_size: float,
                             va_percent: float = 0.70) -> Optional[SessionProfile]:
    """Build one session's OHLC + true VA from its bars and footprint cells.
    `bars` are ascending dicts with ts/open/high/low/close; `cells` are this
    session's FootprintCell records (any price outside `bars`' range is
    the caller's bug, not this function's problem -- no session filtering
    happens here, pass in exactly the cells that belong to the session)."""
    if not bars:
        return None
    va = value_area(volume_at_price(cells, tick_size), tick_size, va_percent)
    return SessionProfile(
        trading_date=bars[0]["ts"].date(),
        start_ts=bars[0]["ts"],
        end_ts=bars[-1]["ts"],
        open=bars[0]["open"],
        high=max(b["high"] for b in bars),
        low=min(b["low"] for b in bars),
        close=bars[-1]["close"],
        poc=va["poc"], vah=va["vah"], val=va["val"],
    )


def compute_ib(bars: list, ib_minutes: Optional[int] = None) -> dict:
    """Initial Balance high/low/mid from the first `ib_minutes` of a
    session's bars. Context only -- never a trigger (CLAUDE.md D-007)."""
    if not bars:
        return {"high": None, "low": None, "mid": None}
    if ib_minutes is None:
        ib_minutes = _cfg.structural.ib_minutes
    start = bars[0]["ts"]
    cutoff = start.timestamp() + ib_minutes * 60
    window = [b for b in bars if b["ts"].timestamp() < cutoff]
    if not window:
        window = bars[:1]
    hi = max(b["high"] for b in window)
    lo = min(b["low"] for b in window)
    return {"high": hi, "low": lo, "mid": (hi + lo) / 2.0}


def compute_overnight_hl(bars: list) -> dict:
    """High/low over the Asia+UK portion of a trading day's bars (everything
    classified as not-'us' by session_of)."""
    on_bars = [b for b in bars if session_of(b["ts"]) != "us"]
    if not on_bars:
        return {"high": None, "low": None}
    return {"high": max(b["high"] for b in on_bars), "low": min(b["low"] for b in on_bars)}


def compute_weekly_profile(week_bars: list, week_cells: Iterable, tick_size: float) -> dict:
    """Weekly high/low + volume-weighted VPOC across a Monday-anchored week."""
    if not week_bars:
        return {"vpoc": None, "high": None, "low": None}
    vap = volume_at_price(week_cells, tick_size)
    vpoc = None
    if vap:
        rows = sorted(vap.items())
        best_idx, best_vol = 0, -1.0
        for i, (_, vol) in enumerate(rows):
            if vol > best_vol:
                best_vol, best_idx = vol, i
        vpoc = rows[best_idx][0] * tick_size
    return {
        "vpoc": vpoc,
        "high": max(b["high"] for b in week_bars),
        "low": min(b["low"] for b in week_bars),
    }


def daily_atr(sessions: list, period: Optional[int] = None) -> float:
    """Simple (non-Wilder) mean True Range over the trailing `period`
    completed sessions -- matches the legacy ACSIL study's ATR exactly
    (a plain running average, not an EMA)."""
    if period is None:
        period = _cfg.filters.atr_period
    usable = [s for s in sessions if s.high is not None and s.low is not None]
    if len(usable) < 2:
        return 0.0
    window = usable[-(period + 1):]
    trs = []
    for prev, cur in zip(window, window[1:]):
        tr = max(
            cur.high - cur.low,
            abs(cur.high - prev.close),
            abs(cur.low - prev.close),
        )
        trs.append(tr)
    return sum(trs) / len(trs) if trs else 0.0


def naked_pocs(sessions: list, trailing_bars: list, lookback: int = 30,
                max_count: int = 8) -> list:
    """Untested prior-session POCs (never touched by a later bar). `sessions`
    is every completed session up to and including the current PD reference;
    the reference itself is excluded from naked-POC candidacy (it's already
    exposed separately as pd_va). Scans the `lookback` sessions before that,
    newest first, and returns up to `max_count` naked POC prices."""
    candidates = sessions[:-1][-lookback:]
    result = []
    for session in reversed(candidates):
        if session.poc is None:
            continue
        touched = any(b["low"] <= session.poc <= b["high"]
                      for b in trailing_bars if b["ts"] > session.end_ts)
        if not touched:
            result.append(session.poc)
        if len(result) >= max_count:
            break
    return result


def compute_overnight_vp(cells: Iterable, tick_size: float) -> Optional[dict]:
    """D-010 (Provisional): overnight (Asia+UK) volume profile HVN/POC/LVN.
    HVN and POC coincide (both the max-volume price); LVN is the
    minimum-volume price still inside the traded range. Flag-only -- see
    docs/decisions.md D-010."""
    vap = volume_at_price(cells, tick_size)
    if not vap:
        return None
    rows = sorted(vap.items())
    poc_idx, poc_vol = 0, -1.0
    lvn_idx, lvn_vol = 0, float("inf")
    for i, (_, vol) in enumerate(rows):
        if vol > poc_vol:
            poc_vol, poc_idx = vol, i
        if vol < lvn_vol:
            lvn_vol, lvn_idx = vol, i
    poc_price = rows[poc_idx][0] * tick_size
    return {"hvn": poc_price, "poc": poc_price, "lvn": rows[lvn_idx][0] * tick_size}


def level_stack_distance(pd_va: dict) -> Optional[float]:
    """D-010 (Provisional): distance in price between PD POC and its nearest
    VA edge. Small values flag a lopsided value area (POC hugging VAH/VAL
    rather than centered) -- a candidate conviction booster for REV, not a
    standalone trigger. Returns None if the value area is incomplete."""
    poc, vah, val = pd_va.get("poc"), pd_va.get("vah"), pd_va.get("val")
    if poc is None or vah is None or val is None:
        return None
    return min(abs(vah - poc), abs(poc - val))


def is_stacked(pd_va: dict, tick_size: float, tol_ticks: Optional[float] = None) -> bool:
    """D-010 (Provisional): True if PD POC sits within `tol_ticks` of a VA edge."""
    if tol_ticks is None:
        tol_ticks = _cfg.structural.level_stack_tol_ticks
    dist = level_stack_distance(pd_va)
    if dist is None or tick_size <= 0:
        return False
    return dist <= tol_ticks * tick_size


# ---------------------------------------------------------------------------
# Snapshot assembly + distance queries
# ---------------------------------------------------------------------------

def build_snapshot(trading_date: date, prior_session: SessionProfile, ib: dict,
                    weekly: dict, overnight: dict, sessions_so_far: list,
                    trailing_bars: list, vwap_anchor_ts: Optional[datetime] = None,
                    overnight_vp: Optional[dict] = None, tick_size: Optional[float] = None) -> StructuralSnapshot:
    """Assemble a StructuralSnapshot for `trading_date` from its prior-day
    reference session plus the supporting aggregates. Callers own wiring raw
    ticks/bars through the builders above (loaders.py -> sessions.py ->
    value_area.py -> these functions); this just glues the pieces together."""
    if tick_size is None:
        tick_size = _cfg.meta.tick_size
    pd_va = {"poc": prior_session.poc, "vah": prior_session.vah, "val": prior_session.val}
    return StructuralSnapshot(
        trading_date=trading_date,
        pd_va=pd_va,
        ib=ib,
        weekly=weekly,
        overnight=overnight,
        prior_day={"open": prior_session.open, "high": prior_session.high,
                   "low": prior_session.low, "close": prior_session.close},
        naked_pocs=naked_pocs(sessions_so_far, trailing_bars),
        vwap_anchor_ts=vwap_anchor_ts,
        atr_daily=daily_atr(sessions_so_far),
        overnight_vp=overnight_vp,
        level_stack_ticks=(level_stack_distance(pd_va) / tick_size
                            if level_stack_distance(pd_va) is not None else None),
    )


def nearest_structure(price: float, direction: int, snapshot: StructuralSnapshot):
    """Nearest structural level *in the trade direction* (walls ahead, not
    behind). direction > 0 looks above price (long context); direction < 0
    looks below. Returns (Level, distance_pts) or (None, None)."""
    candidates = []
    for lvl in snapshot.levels():
        d = (lvl.price - price) if direction > 0 else (price - lvl.price)
        if d > 0:
            candidates.append((d, lvl))
    if not candidates:
        return None, None
    d, lvl = min(candidates, key=lambda x: x[0])
    return lvl, d


def no_mans_land(price: float, direction: int, snapshot: StructuralSnapshot,
                  atr: float, max_atr: Optional[float] = None) -> bool:
    """D-004: True if the nearest structure in `direction` is farther than
    `max_atr` (default from config) times the daily ATR -- price is in the
    void, not near a wall."""
    if max_atr is None:
        max_atr = _cfg.filters.no_mans_land_atr
    if atr <= 0:
        return False
    _, dist = nearest_structure(price, direction, snapshot)
    if dist is None:
        return True  # no structure at all in this direction -> treat as no-man's-land
    return dist > max_atr * atr
