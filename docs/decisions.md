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

### D-011 — PD VAH/POC/VAL window is FULL session (18:00 prior day → RTH close), NOT RTH-only
- **Date:** 2026-07-11
- **Status:** Accepted (supersedes the RTH-only claim in `How the PDVAHPOCVOL is generated.txt`)
- **Evidence:** Both legacy `.cpp` files' `secs < sessStartSec || secs >= sessEndSec` filter,
  and the user-supplied note, describe the value area as built from **09:30-16:00 ET only**.
  Real-data reconciliation against the user's live-study HUD reading for 2026-07-07
  (VAH=29587, POC=29539, VAL=29320, printed at US-session-end ~16:30) falsified this: an
  RTH-only rebuild of 2026-07-07 gave POC=29300/VAH=29508/VAL=29235 — off by up to 239
  points. Rebuilding from the **full session** (2026-07-06 18:00 ET → 2026-07-07 ~16:00-16:45
  ET, i.e. Asia+UK+US) gave VAH=29584-29588 (within ~3-10 ticks of 29587) and, when the POC
  tie between two comparably-sized volume nodes (4353 vs 3743 contracts, only 14% apart) is
  broken toward 29539 instead of 29300, VAL comes out at 29316.25 (within 15 ticks of 29320).
  Both edges independently land close to the target only under the full-session window,
  never under RTH-only, across every end-boundary tried (16:00/16:30/16:45).
- **Decision:** `structure/levels.py::session_profile_from_ticks()` must be fed the full
  18:00-anchored session (prior day 18:00 ET → current RTH close), not an RTH-filtered tick
  set, when building the PD VA reference. The RTH-only description in the source `.txt` note
  and both legacy `.cpp` files' code comments is superseded for this specific mechanism —
  the code's own session-time filter apparently does not represent what the live study's
  chart-displayed values actually reflect (possibly `VolumeAtPriceForBars` itself accumulates
  across the full chart history per bar regardless of the `secs` filter's effect on which
  *sessions* get keyed, rather than the filter gating which *volume* is accumulated -- worth
  re-reading the C++ with this specific question before Phase 2).
- **Re-test trigger:** the remaining POC/VAL gap (tens of ticks, not hundreds) is most likely
  a volume-counting difference between raw-tick `TotalVolume` summation and Sierra's native
  `VolumeAtPriceForBars` -- re-test once a second independent day is reconciled, and ideally
  once Sierra's own per-price volume numbers for one day are available to diff bin-by-bin
  rather than only comparing final POC/VAH/VAL.

### D-012 — Open-location regime gate: the edge lives on out-of-balance opens
- **Date:** 2026-07-12
- **Status:** Provisional (flag-only: `open_outside_value_gate`, default false)
- **Evidence:** First full batch of the order-flow FOLLOW/FADE engine (docs/
  phase2_interim_report.md). Splitting all signals by whether the day's RTH open was
  inside or outside the prior-day value area — a fact known AT THE OPEN, no hindsight:
  MNQM6 front-month: outside-open days +0.426R raw (n=62, PF 2.52) vs inside-open
  −0.037R (n=40); MNQU6: outside-open +0.227R (n=25, PF 1.60) vs inside-open −0.097R
  (n=25). Direction of the split replicated in both periods. Context: the live
  (no-hindsight) conflict veto was found regime-dependent — strong in the trending
  period, inverted in the choppy one — and this open-location gate is the first
  regime read that explains the split with information available at signal time.
  Auction-theoretically coherent: the entire 80%-rule framework premises an
  out-of-balance open.
- **Decision:** Ship as a flag only (dev rule 10): two adjacent, partially-overlapping
  in-sample periods are not independent confirmation. Do NOT hard-suppress inside-open
  days yet. Feed open-location into Phase 5's regime layer as the first
  regime → structure → trigger input.
- **Re-test trigger:** an independent sample (older data, or forward months), and a
  check that the inside-open negative isn't driven by the untuned absorption/exhaustion
  features (FADE currently keys almost entirely off CVD divergence).
- **RE-TESTED 2026-07-12 — FAILED AND INVERTED OOS.** MNQH26 front-month
  (Dec 19 2025 → Mar 20 2026, n=105, a genuinely non-overlapping sample in a different
  macro regime): outside-open −0.020R (n=68) vs inside-open +0.148R (n=37) — the exact
  opposite split. The gate was a regime artifact of the Mar-Jun trend, not a stable edge.
  Keep the flag default-false and DO NOT promote; open-location may still be useful as a
  Phase 5 *input* (it clearly carries regime information — its sign tracks the regime)
  but never as a standalone filter. Same test found the durable pattern instead: **FADE
  is positive in all three front-month periods** (H26 +0.182R n=42, M6 +0.195R n=41,
  U6 +0.028R n=24) while FOLLOW flips sign with regime (−0.056R / +0.278R / +0.100R) —
  an independent replication of the carried-forward "FADE is the strongest edge" prior
  (§3) on the new order-flow triggers.

### D-013 — L0 per-condition autopsy: open-drive gates FOLLOW, holding gaps veto FADE
- **Date:** 2026-07-12
- **Status:** Provisional (flag-only; in-sample, same 9 months as the baseline)
- **Evidence:** The blended 5-condition day-type score measured as pure noise (interim
  report), but splitting by each condition INDIVIDUALLY, with per-period sign consistency
  required across all three front-month periods (the standard that caught D-012):
  1. **open_drive → FOLLOW**: +0.388R with (n=50) vs −0.024R without (n=99),
     delta +0.412R, signs +++ (replicates in every period). Initiative from the bell is
     the regime read the momentum side was missing.
  2. **gap_holds → FADE veto**: −0.164R with (n=27) vs +0.259R without (n=80),
     delta −0.424R, signs −−− (consistently destructive everywhere). A gap that holds
     through the IB is out-of-balance conviction — fading it is fighting initiative.
  3. **narrow_ib → FOLLOW veto**: −0.044R with vs +0.205R without, delta −0.249R,
     signs −−−. The "narrow IB means breakout" folklore is INVERTED in this data.
  Parked (inconsistent signs): prior_close_on_extreme (positive but +-+/++-),
  value_migrated (weakly negative, mixed). The v1 score failed because it summed
  opposing effects (open_drive + with narrow_ib −) into one number.
- **Decision:** L0 v2 = three separate boolean rules, not a score: gate/upweight FOLLOW
  on open-drive days; veto FADE on gap-holds days; never treat narrow IB as trend-capable
  (candidate FOLLOW veto). Flag-only until measured as a combined gated system and,
  ideally, on a fourth period.
- **Re-test trigger:** forward months (U6 beyond Jul 10 / Z6) or older H26/Z25 data;
  and re-measure after FADE gains absorption evidence (gap_holds n=27 is smallish).
- **WEAK-OOS TESTED 2026-07-12 — NO SUPPORT, harmful in one period.** Fusion system
  (gates + live veto, unchanged) on the pre-front-month periods the rules never saw:
  H26 Jul-Dec25: fusion −0.202R vs ungated −0.069R (gates made a bad period worse);
  M6 Nov-Mar: +0.106R vs +0.104R (no help). Combined: fusion −0.057R vs ungated +0.017R.
  Major caveat cutting both ways: these are thin-liquidity contract months where the
  engine's own baseline barely works (price discovery was on the other contract), so
  this neither confirms nor cleanly falsifies — but it removes any claim of OOS
  support. Consequence: keep flags OFF, treat the in-sample +0.35-0.51R gated numbers
  as heavily inflated until a LIQUID unseen period (forward data) decides. The
  trustworthy core remains the ungated front-month baseline (+0.13R, n=256) and FADE's
  6/6-cell robustness.

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
| D-011 | PD VA window is full session, not RTH-only | Accepted |
| D-012 | Open-location regime gate (out-of-balance opens) | Provisional — FAILED OOS, do not promote |
| D-013 | L0 v2: open-drive gates FOLLOW; holding gaps veto FADE | Provisional |
