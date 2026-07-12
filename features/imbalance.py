"""Footprint diagonal imbalances and stacked imbalances -- aggressive
initiative crossing the spread, price-level by price-level.

Phase 3 deliverable. config order_flow.imbalance_ratio / stacked_imbalance_min.

A "buy" imbalance at price P: ask volume at P is disproportionate vs bid
volume one tick BELOW (P - tick) -- diagonal comparison, since a resting
seller at P-tick and an aggressive buyer lifting at P are the two sides of
the same crossed trade in a footprint ladder. A "sell" imbalance mirrors it:
bid volume at P vs ask volume one tick ABOVE.
"""
from dataclasses import dataclass
from typing import Optional

from config import load_config

_cfg = load_config()


@dataclass
class ImbalanceLevel:
    price: float
    ratio: float
    direction: str    # "buy" | "sell"


@dataclass
class StackedImbalance:
    direction: str
    price_low: float
    price_high: float
    count: int
    levels: list


def _diagonal_ratio(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return float("inf") if numerator > 0 else 0.0
    return numerator / denominator


def detect_imbalances(cells: list, tick_size: float, ratio: Optional[float] = None) -> list:
    """`cells` must be the FootprintCells for ONE bar/bucket (same
    ts_bucket) -- one cell per price. Returns ImbalanceLevels sorted by
    price, ascending."""
    if ratio is None:
        ratio = _cfg.order_flow.imbalance_ratio
    by_price = {round(c.price / tick_size): c for c in cells}

    results = []
    for tks in sorted(by_price):
        cell = by_price[tks]
        below = by_price.get(tks - 1)
        above = by_price.get(tks + 1)
        if below is not None:
            r = _diagonal_ratio(cell.ask_volume, below.bid_volume)
            if r >= ratio:
                results.append(ImbalanceLevel(cell.price, r, "buy"))
        if above is not None:
            r = _diagonal_ratio(cell.bid_volume, above.ask_volume)
            if r >= ratio:
                results.append(ImbalanceLevel(cell.price, r, "sell"))
    return results


def detect_stacked_imbalances(cells: list, tick_size: float, ratio: Optional[float] = None,
                               min_stack: Optional[int] = None) -> list:
    """Consecutive-tick imbalances in the same direction, >= min_stack long
    -- a stack (not a single print) confirms directional conviction."""
    if min_stack is None:
        min_stack = _cfg.order_flow.stacked_imbalance_min
    levels = detect_imbalances(cells, tick_size, ratio)

    stacks = []
    for direction in ("buy", "sell"):
        dir_levels = sorted((l for l in levels if l.direction == direction), key=lambda l: l.price)
        run = []
        for lvl in dir_levels:
            tks = round(lvl.price / tick_size)
            if run and round(run[-1].price / tick_size) == tks - 1:
                run.append(lvl)
            else:
                if len(run) >= min_stack:
                    stacks.append(StackedImbalance(direction, run[0].price, run[-1].price, len(run), list(run)))
                run = [lvl]
        if len(run) >= min_stack:
            stacks.append(StackedImbalance(direction, run[0].price, run[-1].price, len(run), list(run)))
    return stacks
