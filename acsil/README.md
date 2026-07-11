# ACSIL (Sierra Chart live study) — Phase 8

The C++ study/DLL that faithfully executes ONLY validated logic on the live feed.
The study is an executor, not a place to invent signals.

## `legacy/`

`legacy/PriorDayNY_ValueArea_80PctRule.cpp` is the **pre-rebuild** study — the actual
time-based-trigger implementation that Decision D-007 (`docs/decisions.md`) replaces.
Kept for reference only; not built or ported as-is. Notable pieces:

- FADE/FOLLOW trigger (`PriorDayNY_ValueArea_80PctRule.cpp:629-638`): a consecutive-close
  streak counter (`cIn`/`cAb`/`cBe`) on a chart hardcoded to 30-minute bars (line 4). The
  streak resets to zero on any single close the wrong way, so both the 30-min bar-close
  floor and the streak-reset compound into the lag D-007 describes. FADE fires only once
  price has already closed back inside value for N bars — by then it's often already near
  POC (the target). FOLLOW fires only after N closes beyond VAH/VAL — by then price has
  often already reached the next wall (IB high/low, weekly VPOC). This is the concrete
  mechanism behind "late signals" and "signals straight into support/resistance."
- REV's rejection detector (`DetectRej`, lines 91-132) is **not** built the same way — it's
  a bar-level proxy for absorption/exhaustion (touch-count + wick-rejection + a
  momentum-dying check + break-back confirmation), just derived from OHLC instead of true
  footprint bid/ask volume. Worth treating as a design skeleton for Phase 3's real
  absorption/exhaustion features rather than discarding.

Carry-forward ACSIL gotchas (CLAUDE.md section 6.8):
- `Input::GetString()` returns `const char*` (use `strlen`, not `GetLength`).
- HUD/marker text needs a non-const `SCString&` via `.Format()`; embed `\n` for multiline.
- Once-per-day events: guard with a persistent int keyed by `DateYMD`.
- Read same-chart studies via `GetStudyArrayUsingID`; separate SC instances can't share
  study arrays — use a file bus.
- HUD shows FROZEN structural read (@IB) + LIVE conviction separately.
- Include a signal + decision logger (pipe-delimited text) for replay validation;
  moderate replay speed to avoid the calc-skipping throttle.
