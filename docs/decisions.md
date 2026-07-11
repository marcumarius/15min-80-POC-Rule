# Decision Log

> Permanent, dated, evidence-backed record of every accepted or rejected edge and
> design choice. **Do not re-litigate a settled decision without new data.** When new
> evidence overturns an entry, add a superseding entry — never delete history.
>
> Entry format: ID · Title · Date · Status · Evidence · Decision · Re-test trigger.
>
> Statuses: **Accepted** · **Rejected** · **Provisional** (flag-only until confirmed) ·
> **Superseded**.

The seed entries below are **carried forward** from prior MNQ/NQ work: ~5 years of
1-minute backtesting (2021-07 → 2026-07, ~1,558 trading days) plus a 6-month
replay-log validation against the live Sierra Chart study (2025-11 → 2026-07). They
are **priors for the rebuild**, not gospel — each has an explicit re-test trigger for
when the move to order-flow triggers changes the signal set.

---

### D-001 — REV is a US-session-only edge
- **Date:** 2026-07-11 (carried forward)
- **Status:** Accepted
- **Evidence:** 5yr backtest — US REV strongly positive (short PF ~2.4, long positive);
  overnight REV net losing (UK/Asia short negative). 6mo replay confirmed US REV as the
  standout under 1.5R management (long ~65% win, short ~74%).
- **Decision:** Gate REV to RTH (`rev_us_only = true`).
- **Re-test trigger:** once REV fires on absorption/exhaustion/divergence rather than a
  time-window rejection count, re-run the session split — the order-flow version may
  behave differently overnight.

### D-002 — Confluence is the primary edge
- **Date:** 2026-07-11 (carried forward)
- **Status:** Accepted
- **Evidence:** Monotonic relationship — lone signal ≈ −0.25R; +1 independent read
  aligned ≈ −0.10R; +2 aligned ≈ +0.35R (PF ~1.58). Effect held across the 5yr sample.
- **Decision:** Build the agreement engine early (Phase 5). Weight reads by role
  (regime → structure → trigger); do not equal-vote.
- **Re-test trigger:** re-measure once triggers are order-flow based; confluence of
  *independent* order-flow reads may be even stronger (or more correlated — check).

### D-003 — Conflict veto is the single biggest noise filter
- **Date:** 2026-07-11 (carried forward)
- **Status:** Accepted
- **Evidence:** An opposing signal in the same session shifted expectancy from ~+0.11R
  (clean) to ~−0.32R. Largest single-filter improvement observed.
- **Decision:** Stand aside when independent reads oppose in the same session
  (`conflict_veto = true`).
- **Re-test trigger:** none pending; re-confirm on the new signal set in Phase 7.

### D-004 — "No-man's-land," not "into a zone," is the real failure mode
- **Date:** 2026-07-11 (carried forward)
- **Status:** Accepted (hard-suppress for REV; **Provisional** for FADE)
- **Evidence:** Original hypothesis ("signals fire into a nearby supply/demand zone and
  reverse") was **inverted** by data: losers had *more* clear space (median ~158pt) than
  winners (~80pt). Worst bucket was >~0.5×ATR from any structure (~21% win vs ~36%).
  Sweet spot 30–100pt. Per-type: REV near +1.25R vs no-man's-land +0.48R (n≈51, strong);
  FADE near +0.62R vs −0.56R (n=4 no-man's-land — too few); FOLLOW least sensitive.
- **Decision:** Distance-to-structure is a first-class feature and filter
  (`no_mans_land_atr = 0.5`). Hard-suppress REV in no-man's-land; **FADE stays flag-only**
  (4 samples is insufficient — hard-coding would overfit); FOLLOW flag-only.
- **Re-test trigger:** revisit the FADE hard-suppress once ≥30 no-man's-land FADE samples
  exist; re-tune the 0.5×ATR threshold (it removed ~45% of signals — 0.6–0.7 may balance
  volume better).

### D-005 — Day-type score predicts direction, not magnitude
- **Date:** 2026-07-11 (carried forward)
- **Status:** Accepted
- **Evidence:** |score| vs day-range correlation ≈ −0.18 (near zero/negative); high-score
  days were *not* bigger movers. But signed score predicted breakout direction ~55%
  overall, ~64% at |score| ≥ 4.
- **Decision:** Use the score as a **directional tilt only**. Never size up for a "big RR"
  day based on score.
- **Re-test trigger:** re-measure direction hit-rate on the fused conviction (Phase 5),
  which should improve on the raw score.

### D-006 — 1.5R scale-and-trail hybrid for tradeability
- **Date:** 2026-07-11 (carried forward)
- **Status:** Accepted
- **Evidence:** Pure runner: ~21% win, PF ~2.0, but −43% max DD (untradeable psychologically).
  1.5R hybrid (50% at 1.5R, breakeven, trail rest): ~50–56% win, PF ~2.0–2.2, −13.5% max DD,
  return/DD ~3.4x. Lower total profit, far higher risk-adjusted return and human tradeability.
- **Decision:** Default management is the 1.5R hybrid (`tgt1_R = 1.5`).
- **Re-test trigger:** re-optimize `tgt1_R` (1.0/1.5/2.0 tested; 1.5 best balance) once the
  order-flow trigger changes the entry distribution.

### D-007 — Time-based triggers are the core flaw (the reason for this rebuild)
- **Date:** 2026-07-11
- **Status:** Accepted
- **Evidence:** Prior triggers fired on clock boundaries (N consecutive 15-min closes, IB at
  fixed time, first close back inside value). Clock edges are arbitrary relative to the
  auction; this injects lag and noise. Replay validation also exposed a Sierra replay-speed
  throttle that *dropped* time-triggered signals at high speed — a fragility of bar-close logic.
  Confirmed against the actual legacy source
  (`acsil/legacy/PriorDayNY_ValueArea_80PctRule.cpp:629-638`): FADE/FOLLOW are a
  consecutive-close streak counter (`cIn`/`cAb`/`cBe`) that resets to zero on any single
  close the wrong way, running on a chart hardcoded to 30-minute bars (line 4). Two
  compounding lag sources: (1) the 30-min bar-close floor — intrabar events are invisible
  until close; (2) the streak reset — a wider acceptance window needs multiple consecutive
  closes, discarding progress on one bad bar. Net effect: FADE only fires once price has
  already closed back inside value for N bars (often already near POC, the target); FOLLOW
  only fires after N closes beyond VAH/VAL (often already at the next wall) — i.e. exactly
  the "late, or straight into support/resistance" failure mode this rebuild targets. REV's
  rejection detector (`DetectRej`, lines 91-132) is the exception — a bar-level
  touch/wick-rejection/momentum-dying proxy for absorption/exhaustion, not a close-streak —
  and is a reasonable design skeleton for Phase 3 rather than a pure discard.
- **Decision:** Rebuild all triggers on auction events (absorption, exhaustion, delta/CVD
  divergence, footprint imbalance, acceptance, trapped traders). Time may **gate** (session
  windows) but never **trigger**.
- **Re-test trigger:** N/A — this is the founding premise; validate the replacement in Phase 3/7.

### D-008 — Costs are mandatory in every economic result
- **Date:** 2026-07-11 (carried forward)
- **Status:** Accepted
- **Evidence:** Modeling 1-tick entry slippage, 3-tick stop slippage, a 15pt min-stop, and
  $1.5 round-trip commission cut a frictionless 5yr result from ~$123k to ~$86k without
  changing the per-year robustness. Frictionless numbers are misleading.
- **Decision:** Every backtest/report includes the cost model (`entry_slippage`,
  `stop_slippage`, `commission`, `min_stop_pts`). No frictionless figures in reports.
- **Re-test trigger:** none; update cost assumptions if broker/feed terms change.

### D-009 — Value areas require true volume-at-price, not 1-min approximation
- **Date:** 2026-07-11 (carried forward)
- **Status:** Accepted
- **Evidence:** Prior backtests approximated VA by distributing 1-min volume across bar
  ranges (tick VAP unavailable historically). Reconstruction validation showed FOLLOW
  (US/UK) and REV matched the live study well, but **FADE and Asia-FOLLOW diverged** —
  the study fired ~60% of the reconstructed count — traceable to VA/acceptance approximation.
- **Decision:** Phase 1 must build VA from true tick/footprint volume-at-price. Treat any
  1-min-approximated VA result as provisional.
- **Re-test trigger:** re-validate FADE/Asia-FOLLOW counts against the live study once true
  VAP is in place.

### D-010 — Stacked PD levels + overnight session volume profile (new structural hypothesis)
- **Date:** 2026-07-11
- **Status:** Provisional (flag-only; not backtested)
- **Evidence:** n=1 documented example (2026-07-09, `Interesting observations/July 9.jpeg`
  + `.txt`). Author's note: when PD VAH and PD POC sit unusually close together (a lopsided
  value area, POC near the edge rather than centered), that zone reacted twice during the
  Asia session before a sustained move — a stronger reaction than either level alone
  typically produces. Separately, the author manually builds a Fixed-Range Volume Profile
  over the overnight (Asia+UK) session and finds price frequently retests that overnight
  HVN/POC at the US open, then continues in the direction implied by whether the zone now
  acts as support or resistance. Four other same-week chart examples (June 30, Jul 2, 7, 8)
  are visually consistent but have no written explanation on file, so are not counted as
  independent evidence yet.
- **Decision:** Treat as two candidate structural additions, both flag-only until tested:
  (1) a level-stacking metric — distance between PD POC and its nearest VA edge, flagged
  when unusually small — feeding the confluence engine as a conviction booster on REV, not
  a new trigger; (2) an overnight-session (Asia+UK) volume profile (HVN/POC/LVN) as a new
  `Level kind` in `StructuralSnapshot`, extending `nearest_structure`/no-man's-land and
  gating a US-open-window read. Neither replaces or weakens FADE/FOLLOW/REV.
- **Re-test trigger:** promote out of Provisional once (a) Phase 1's true-VAP engine can
  reconstruct the overnight profile and (b) a real sample (not n=1) shows the stacked-level
  and overnight-retest reactions outperform an unstacked/non-retest baseline, cost-modeled
  and OOS.

---

## Ledger (quick index)

| ID | Title | Status |
|----|-------|--------|
| D-001 | REV US-session-only | Accepted |
| D-002 | Confluence is the edge | Accepted |
| D-003 | Conflict veto | Accepted |
| D-004 | No-man's-land failure mode | Accepted (FADE provisional) |
| D-005 | Score = direction not magnitude | Accepted |
| D-006 | 1.5R hybrid management | Accepted |
| D-007 | Time triggers = the flaw | Accepted |
| D-008 | Costs mandatory | Accepted |
| D-009 | True VAP required | Accepted |
| D-010 | Stacked PD levels + overnight VP | Provisional |
