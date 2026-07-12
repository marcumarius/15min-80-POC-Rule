from datetime import datetime
from zoneinfo import ZoneInfo

from data.types import FootprintCell
from features.imbalance import detect_imbalances, detect_stacked_imbalances

ET = ZoneInfo("America/New_York")
_TS = datetime(2026, 7, 8, 9, 30, tzinfo=ET)


def _cell(price, bid, ask):
    return FootprintCell(ts_bucket=_TS, price=price, bid_volume=bid, ask_volume=ask)


def _stacked_buy_ladder():
    # 100.25/100.50/100.75 each qualify as a "buy" diagonal imbalance
    # (ask >= 3x the bid one tick below); 100.00 and 101.00 don't, capping
    # the stack at exactly 3.
    return [
        _cell(100.00, bid=10, ask=5),
        _cell(100.25, bid=2, ask=40),   # vs bid@100.00=10 -> ratio 4
        _cell(100.50, bid=3, ask=50),   # vs bid@100.25=2  -> ratio 25
        _cell(100.75, bid=1, ask=45),   # vs bid@100.50=3  -> ratio 15
        _cell(101.00, bid=8, ask=2),    # vs bid@100.75=1  -> ratio 2, doesn't qualify
    ]


def test_detect_imbalances_flags_buy_diagonal():
    levels = detect_imbalances(_stacked_buy_ladder(), tick_size=0.25, ratio=3.0)
    buy_prices = sorted(l.price for l in levels if l.direction == "buy")
    assert buy_prices == [100.25, 100.50, 100.75]
    assert all(l.direction != "sell" for l in levels)


def test_detect_imbalances_zero_denominator_is_infinite_ratio():
    cells = [_cell(100.00, bid=0, ask=0), _cell(100.25, bid=0, ask=5)]
    levels = detect_imbalances(cells, tick_size=0.25, ratio=3.0)
    assert len(levels) == 1
    assert levels[0].price == 100.25 and levels[0].ratio == float("inf")


def test_detect_imbalances_no_data_at_adjacent_price_skips():
    cells = [_cell(100.25, bid=1, ask=100)]  # no cell at 100.00 to compare against
    assert detect_imbalances(cells, tick_size=0.25, ratio=3.0) == []


def test_detect_stacked_imbalances_forms_one_stack_of_three():
    stacks = detect_stacked_imbalances(_stacked_buy_ladder(), tick_size=0.25, ratio=3.0, min_stack=3)
    assert len(stacks) == 1
    s = stacks[0]
    assert s.direction == "buy"
    assert s.price_low == 100.25
    assert s.price_high == 100.75
    assert s.count == 3


def test_detect_stacked_imbalances_below_threshold_forms_no_stack():
    stacks = detect_stacked_imbalances(_stacked_buy_ladder(), tick_size=0.25, ratio=3.0, min_stack=4)
    assert stacks == []
