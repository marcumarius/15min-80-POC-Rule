"""Acceptance: price has TRADED beyond a level AND BUILT volume there --
replaces the legacy study's "N consecutive closes" streak counter (D-007).

Phase 3 deliverable. config order_flow.acceptance (method: trade_and_rest,
trade_and_rest_min_volume_z). This is the concrete fix for the late-signal /
signal-into-support-resistance problem CLAUDE.md documents: the old counter
only fired after N bar closes had already elapsed the wrong way once,
guaranteeing lag; this fires on the first bar where price is genuinely
resting beyond the level with anomalous (not just any) volume behind it.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from config import load_config
from features._stats import rolling_zscore

_cfg = load_config()


@dataclass
class AcceptanceEvent:
    index: int
    ts: datetime
    direction: int    # +1 = accepted ABOVE level | -1 = accepted BELOW level
    level: float
    price: float
    volume_z: float


def detect_acceptance(bars: list, level: float, direction: int,
                       min_volume_z: Optional[float] = None, lookback: int = 20):
    """First bar where price TRADED beyond `level` in `direction` for its
    entire range (not a wick -- low > level for direction=+1, high < level
    for direction=-1) AND built anomalous volume (z-score vs the trailing
    `lookback` bars >= min_volume_z). Returns the first qualifying
    AcceptanceEvent, or None if acceptance hasn't happened yet in `bars`.
    """
    if min_volume_z is None:
        # `acceptance` is a nested mapping in params.yaml (method + threshold),
        # so it resolves to a plain dict rather than a dotted Section.
        min_volume_z = _cfg.order_flow.acceptance["trade_and_rest_min_volume_z"]
    if direction not in (1, -1):
        raise ValueError(f"direction must be +1 or -1, got {direction!r}")

    volumes = [b.volume for b in bars]
    for i, b in enumerate(bars):
        beyond = (b.low > level) if direction == 1 else (b.high < level)
        if not beyond:
            continue
        z = rolling_zscore(volumes, i, lookback)
        if z >= min_volume_z:
            return AcceptanceEvent(i, b.ts, direction, level, b.close, z)
    return None
