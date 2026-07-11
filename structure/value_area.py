"""True volume-at-price value area (POC/VAH/VAL), 70% expansion.

Phase 1 deliverable (section 3.3) and Decision D-009: use TRUE VAP, never a
1-minute approximation. Acceptance: reproduce Sierra Chart VA within tick
tolerance -- so bins are sized in ticks (tick_size), not rounded to whole
points. Mirrors the legacy ACSIL study's `ComputeProfile` tie-breaking
exactly: POC ties favor the lower price (first strict max in ascending scan);
expansion ties favor the upper neighbor.
"""
from collections import defaultdict
from typing import Iterable


def _price_to_ticks(price: float, tick_size: float) -> int:
    return round(price / tick_size)


def volume_at_price(cells: Iterable, tick_size: float) -> dict:
    """Aggregate footprint cells into a {price_in_ticks: total_volume} map."""
    vap = defaultdict(float)
    for cell in cells:
        tks = _price_to_ticks(cell.price, tick_size)
        vap[tks] += cell.bid_volume + cell.ask_volume
    return dict(vap)


def value_area(vap: dict, tick_size: float, va_percent: float = 0.70) -> dict:
    """Compute POC/VAH/VAL from a {price_in_ticks: volume} map.

    Expands out from the POC one adjacent bin at a time, always taking the
    heavier of the two neighbors, until `va_percent` of total volume is
    enclosed -- the standard TPO/volume-profile value-area algorithm.
    """
    empty = {"poc": None, "vah": None, "val": None}
    if not vap or tick_size <= 0:
        return empty

    total = sum(vap.values())
    if total <= 0:
        return empty

    rows = sorted(vap.items())  # [(price_in_ticks, volume), ...] ascending

    poc_idx, poc_vol = 0, -1.0
    for i, (_, vol) in enumerate(rows):
        if vol > poc_vol:
            poc_vol, poc_idx = vol, i

    target = total * va_percent
    acc = rows[poc_idx][1]
    up = dn = poc_idx
    while acc < target and (up < len(rows) - 1 or dn > 0):
        can_up = up < len(rows) - 1
        can_dn = dn > 0
        up_vol = rows[up + 1][1] if can_up else -1.0
        dn_vol = rows[dn - 1][1] if can_dn else -1.0
        if can_up and (not can_dn or up_vol >= dn_vol):
            up += 1
            acc += rows[up][1]
        elif can_dn:
            dn -= 1
            acc += rows[dn][1]
        else:
            break

    return {
        "poc": rows[poc_idx][0] * tick_size,
        "vah": rows[up][0] * tick_size,
        "val": rows[dn][0] * tick_size,
    }


def value_area_from_footprint(cells: Iterable, tick_size: float, va_percent: float = 0.70) -> dict:
    """Convenience entry point: footprint cells -> {poc, vah, val} in one call."""
    return value_area(volume_at_price(cells, tick_size), tick_size, va_percent)
