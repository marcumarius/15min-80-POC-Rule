# ACSIL (Sierra Chart live study)

The C++ study/DLL that faithfully executes ONLY validated logic on the live feed.
The study is an executor, not a place to invent signals.

## `OrderFlowAuctionStudy.cpp` — current

The ground-up rebuild's live study. Two layers, built and confirmed compiling/running
in Sierra Chart by the user (structural layer, first build) with the signal layer added
2026-07-12:

**Structural layer** (PD VAH/POC/VAL, Initial Balance, weekly VPOC/PWH/PWL, no-man's-land
readout). Mirrors `structure/levels.py` + `structure/value_area.py` + `structure/sessions.py`.
Implements the **D-011 window correction**: prior-day value area is built from the FULL
18:00-ET-anchored session (Asia+UK+US), not RTH-only as the legacy study and its
accompanying note originally claimed — tested against a real chart reading and falsified.
IB and RTH open/high/low/close are still tracked from RTH bars only.

**Order-flow signal layer** (added 2026-07-12): the **UNGATED** FOLLOW/FADE event engine
only — delta/CVD divergence, absorption, exhaustion, trade-and-rest acceptance — mirroring
`signals/engine.py` + `features/{delta,absorption,exhaustion,acceptance}.py` exactly. This
is the "trustworthy core" validated with costs across three regime periods
(`docs/phase2_interim_report.md`): +0.130R/trade combined (n=256), FADE positive in all
six period×bar-basis cells tested. Includes a pipe-delimited signal logger
(`In_LogEnable`/`In_LogFile`) so live-fired signals can be reconciled against the Python
backtest (Phase 7) — the mechanism for accumulating genuine forward out-of-sample data,
which is the single biggest open question left in the project.

**Deliberately NOT ported** (see the file's header comment for the evidence): the D-013
regime gates and live conflict veto (`fusion/decision.py`) — measured in-sample only and
FAILED weak-OOS on unseen thin-contract periods (fusion −0.057R vs ungated +0.017R on data
the rules never saw); and the MOMO pullback engine (`signals/momentum.py`) — lost to
FOLLOW head-to-head combined, regime-complementary but with no validated regime gate to
select between them. Do not add either without new decisions.md evidence.

**Signal-layer addition not yet built/tested in Sierra Chart** — the structural layer was
already confirmed working; the order-flow layer is new and, per the same constraint as
before, there's no ACSIL compiler in the research environment. Build it in `ACS_Source`,
report any compile errors back for a fix. Brace/paren balance and input-index consistency
were checked programmatically before handoff, but that is not a substitute for compilation.

**Not yet done:** weekly VPOC has NOT been re-validated under the D-011 full-session
pattern (still RTH-only, matching the legacy study). REV is not ported (Phase 2/3
ordering: FOLLOW/FADE first, per CLAUDE.md §1.3).

**Run on a 1-minute chart** for fidelity to the validated backtest — the numbers above
came from 1-minute bars. An 800-trade/tick basis was tested as extra FADE evidence and
measured slightly negative; if you run this on your preferred tick chart, treat its
signals as unvalidated until a matching Python backtest exists on that bar basis.

## `legacy/`

Two versions of the **pre-rebuild** study — the actual time-based-trigger implementation
that Decision D-007 (`docs/decisions.md`) replaces. Kept for reference only; not built or
ported as-is.

- `PriorDayNY_ValueArea_80PctRule.cpp` — the fuller-featured version (includes the
  no-man's-land `ProxFlag`/`ProxMaxATR` filter, D-004's origin).
- `15MIN_80%Rule_IBV.cpp` — an earlier/different snapshot, missing the no-man's-land
  filter but otherwise identical PD VAH/POC/VAL mechanism (`ComputeProfile`, RTH-session
  filter, Pass 1/Pass 2 structure) — cross-checked against the first file and the user's
  `How the PDVAHPOCVOL is generated.txt` note during the D-011 investigation; both `.cpp`
  files agree with each other (and were both superseded by real-data reconciliation, D-011).

Notable pieces, from the fuller file:

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
