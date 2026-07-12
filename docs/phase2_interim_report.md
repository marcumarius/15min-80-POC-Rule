# Phase 2/3 Interim Report — first real-data batch (2026-07-12)

**Status: machinery complete and firing; economics PRELIMINARY.** One
contract series (MNQU6), 31 trading days (2026-05-29 → 2026-07-10), one
regime, in-sample, thresholds at config defaults (untuned). This is a first
honest look, NOT Phase 7 validation.

## What ran

Full pipeline: fast streaming `.scid` reader (`backtest/scid_fast.py`,
validated identical to the trusted per-day loader) → D-011 full-session PD
VA per day → FOLLOW/FADE event engine (`signals/engine.py`) on RTH 1-min
bars → D-006 1.5R scale-and-trail outcome model with D-008 costs
(`backtest/outcome.py`). 50 signals (~1.6/day).

## Results (costs included)

| Set | n | win% | PF | exp/trade | totR |
|---|---|---|---|---|---|
| RAW all signals | 50 | 48.0 | 1.12 | +0.060R | +3.01 |
| FOLLOW only | 26 | 53.8 | 1.20 | +0.090R | +2.34 |
| FADE only | 24 | 41.7 | 1.05 | +0.028R | +0.67 |
| **D-003 conflict-veto (clean days only)** | **10** | **80.0** | **3.07** | **+0.349R** | **+3.49** |
| First-signal-of-day only | 26 | 46.2 | 0.87 | −0.066R | −1.72 |

**Headline:** the conflict veto replicated on the order-flow signal set —
the 10 trades on internally-agreeing days captured more total R than all 50
raw trades combined, at 80% win. Chronological precedence (first-of-day) is
*negative* — agreement, not timing, carries the edge. This is an independent
re-confirmation of D-002/D-003 on a completely new trigger mechanism,
exactly what those entries' re-test triggers asked for.

**Caveats, stated plainly:** n=10 on the veto subset is tiny. The veto as
measured uses end-of-day hindsight (a live trader only discovers a conflict
after the first signal is already on); a live-executable version needs
Phase 5's fusion logic. One regime, in-sample, no walk-forward.

## Known issues found by this run (fix before trusting economics)

1. **FOLLOW structural stops are inconsistent** — stop = the VA edge, so on
   gap days acceptance fires hundreds of points beyond it (risks of 400-800
   pts observed, e.g. 06-15: 801.6p). R economics are distorted; needs a
   stop model that caps at an ATR multiple or uses a nearer invalidation.
2. **Absorption almost never fires** at defaults (z≥2.0 AND range ≤3 ticks
   on 1-min MNQ bars — 3 ticks is too tight). FADE currently keys almost
   entirely off CVD divergence. Tune `absorption_price_stall_ticks` /
   bar timeframe before concluding absorption is useless.
3. Exhaustion appeared once. Same tuning note.
4. Imbalance/stacked-imbalance features exist and are tested but are not
   yet wired into the engine's FOLLOW confirmation (needs footprint cells
   per bar in the batch path, not just minute bars).

## Update (same day): ATR-capped stops + the MNQM6 big sample

Stop model fixed (`management.max_stop_atr` = 0.5, tighter of structural
edge and ATR cap). Then the full MNQM6 file ran: 162 trading days
(2025-11-03 → 2026-06-18), segmented at the ~Mar 20 front-month roll.

**MNQM6 front-month (Mar 20 → Jun 18, liquid, 102 signals), costs included:**

| Set | n | win% | PF | exp | totR | maxDD |
|---|---|---|---|---|---|---|
| RAW all | 102 | 54.9 | 1.62 | +0.245R | +24.95 | 7.37R |
| FOLLOW | 61 | 57.4 | 1.88 | +0.278R | +16.97 | 4.25R |
| FADE | 41 | 51.2 | 1.39 | +0.195R | +7.98 | 5.14R |
| VETO (clean days) | 32 | 81.2 | 71.7* | +0.879R | +28.12 | 0.21R |

*PF 71.7 was inspected trade-by-trade before believing it: it is NOT an
outlier artifact. All 6 losers in the subset are −0.02 to −0.15R scratches
(breakeven stops after the 1.5R scale — the D-006 management converting
would-be losers into scratches), winners cluster +1.3 to +1.8R, and there
are ZERO full stop-outs on clean days. The raw edge (+0.245R over n=102)
is itself meaningfully positive on this larger sample — 4x the MNQU6
period's raw expectancy, consistent with the stop-model fix and a
trendier regime.

Pre-roll thin-contract months (n=143) were also positive (+0.120R, PF
1.27) — reported for completeness, low confidence due to liquidity.

**Replication status of the veto:** clean-day economics now confirmed on
BOTH contract periods (MNQU6: 80% win n=10; MNQM6 front: 81% win n=32).
Still hindsight-formulated — the live version (Phase 5) must decide with
only information available at signal time (e.g. "no opposing signal has
fired YET today" + conviction weighting), which will be weaker; measure it.

## Live-executable veto: measured, and it SPLITS BY REGIME

Formulation: chronological — take a signal only if no opposing signal has
fired earlier the same day (no hindsight; trades entered before a conflict
emerges stay entered).

| Period | RAW | LIVE-VETO |
|---|---|---|
| MNQM6 front (Mar-Jun, trendy) | n=102, +0.245R, PF 1.62 | **n=66, +0.395R, PF 2.25, maxDD 4.26R** |
| MNQU6 (May-Jul, choppier) | n=50, +0.065R, PF 1.13 | n=26, **−0.056R**, PF 0.89 |

Read plainly: in the trending regime the live veto works beautifully (fewer
trades, more total R). In the choppy period it INVERTS — because "no
opposing signal yet" always keeps the FIRST signal of the day, and on messy
days the first signal is the bad one (first-of-day was −0.066R there). The
hindsight veto's power came from skipping messy days ENTIRELY, which a
chronological rule cannot do. This is precisely why the D-002 fusion
hierarchy is regime → structure → trigger: the live veto needs a regime/
day-type read to know whether to trust the day's first signal. That is
Phase 5's job, now with a concrete, measured requirement.

Caveat: the two periods overlap ~3 weeks (June exists in both contracts);
they are adjacent samples, not independent.

## Regime gate found: open location (D-012)

Splitting every signal by a fact known AT THE OPEN — RTH open inside vs
outside the prior-day value area:

| Period | Outside-open days (raw) | Inside-open days (raw) |
|---|---|---|
| MNQM6 front | **+0.426R, n=62, PF 2.52, maxDD 2.23R** | −0.037R, n=40 |
| MNQU6 | **+0.227R, n=25, PF 1.60** | −0.097R, n=25 |

The split replicates across both periods: the edge lives on out-of-balance
opens, and inside-open days are flat-to-negative chop. This is coherent with
the strategy's own premise (the 80% rule IS an out-of-balance-open play) and
explains the live-veto regime split. Logged as D-012 (Provisional, flag-only
per dev rule 10 — the two periods overlap and share one macro regime).

Stacking the live veto ON TOP of outside-open improved M6 (+0.466R) but
flattened U6 (−0.008R) — inconsistent, so the veto stack is NOT part of the
provisional gate; open-location alone is the robust piece so far.

## Absorption tuning attempt: NEGATIVE RESULT, definition is timeframe-wrong

Grid-scanned `detect_absorption` on real July 8/9 tape: **zero events at
every threshold combination** (z 1.5-2.5 × stall 3-24 ticks), and a
relative-range variant (range below the 35th percentile of trailing bars +
high |delta| z) fired ~once per day and never at the known turning points.
Cause, measured: median 1-min MNQ bar range is ~91 ticks in this regime, and
|delta| correlates with range at minute granularity — "heavy delta, no
travel" essentially does not exist on minute bars. Absorption is a per-PRICE
phenomenon (heavy volume at a level that refuses to traverse) and must be
rebuilt on FootprintCells (per-price bid/ask ladders). This is precisely why
the data contract forbids collapsing footprint to OHLC before features
(CLAUDE.md §5). Until that rebuild, FADE runs on CVD divergence — which the
batch shows is already mildly positive on its own.

## Market depth unlocked (.depth format cracked + validated)

User supplied real Sierra depth recordings (`depth/`, gitignored): 6 RTH
days of MNQH26 (Jan 12-19, 18-27M records/day) + ~52min of MNQM26 premarket
(May 18). Format reverse-engineered byte-level ("SCDD" magic, 24-byte
records, same microsecond epoch and x0.01 price scale as .scid; commands
1=clear/2-3=add/4-5=modify/6-7=delete bid/ask). `data/depth.py` parses and
reconstructs the 100-level resting book. **Validated against the tape**: on
May 18 (same contract in both files), 77% of 47,317 trades printed within 1
tick of the reconstructed touch, 89% within 2 — residual is async timestamp
skew between the two recording paths. This is the bookmap layer: true
absorption (resting liquidity refreshing under aggression), pulling/stacking,
iceberg detection become possible. Note: the Jan depth days pair with the
H26 contract, whose trades we do NOT have in .scid — ask the user for the
MNQH26 .scid (or use M6-trades days only) before building joint features.
User also confirmed a preference for 800-trade bars (activity-based), which
is the planned bar basis for the feature rebuild.

## MNQH26 independent sample: D-012 falsified, FADE prior replicated

User supplied the MNQH26 .scid (Jul 2025 → Mar 2026, 104M records). Its
front-month window (Dec 19 → Mar 20, n=105 signals) overlaps NOTHING in the
earlier batches and sits in a different macro regime — a true independent
test. Results:

- **D-012 INVERTED**: outside-open −0.020R vs inside-open +0.148R — the
  exact opposite of both 2026 spring/summer periods. The open-location gate
  was a regime artifact. Demoted in decisions.md; usable only as a Phase 5
  regime *input*, never a standalone filter. (This is the process working:
  flag-only per rule 10 meant nothing shipped wrong.)
- **The durable pattern across all three front-month periods is the family
  split**: FADE positive in ALL THREE (H26 +0.182R, M6 +0.195R, U6 +0.028R;
  combined n=107) while FOLLOW flips sign with regime (−0.056R / +0.278R /
  +0.100R). This independently replicates the carried-forward prior that
  FADE (the 80% rule) is the strongest edge — now on order-flow triggers,
  with costs, across ~9 months and three contracts.
- Full-year coverage now on disk: Jul 2025 → Jul 2026 across H26/M6/U6, and
  the six Jan depth days now have same-contract tape (book+tape lab ready).

## Next steps (in order)

1. Rebuild the feature pipeline on 800-trade bars + per-price footprint
   (config `bar_trades`); re-run all three batches — absorption/exhaustion
   expected to come alive on activity-normalized bars, and FADE (the robust
   family) is the one absorption should strengthen most.
2. Independent-sample test of D-012 (older data or forward months) + proper
   IS/OOS split.
3. Phase 5: fuse open-location regime + structure + trigger + conflict state
   into one conviction score.
4. Then and only then: Decision-Log entry proposing the edge as Accepted.
