# CLAUDE.md — Order-Flow Auction Strategy (Ground-Up Rebuild)

> Handover + operating manual for a from-scratch rebuild of the MNQ/NQ intraday
> auction strategy. Read this file at the start of every session. It defines the
> strategy, the design philosophy, the parameters, the development rules, and the
> phased roadmap. Keep it updated as the source of truth.

---

## 0. TL;DR — What we are building and why

We are rebuilding an intraday futures strategy for **MNQ/NQ (and MES)** traded during
the **US Regular Trading Hours** session. The strategy keeps the proven **structural
framework** — prior-day Value Area (POC / VAH / VAL), the **80% Rule**, Initial
Balance, and weekly/session levels — but **replaces the trigger mechanism**.

**The core flaw we are fixing:** the old system fired signals on *time-based* rules —
"N consecutive 15-minute closes beyond value," "first 15-min close back inside value,"
IB completion at a fixed clock time. Clock boundaries are arbitrary; the auction does
not respect them. A close at 10:45 is not meaningfully different from one at 10:47, yet
the old triggers treated bar edges as truth. This injects noise and lag.

**The rebuild:** triggers fire on **order-flow / footprint events** — the actual
institutional footprints left in the tape:

- **Absorption** — passive limit orders soaking up aggressive market orders (price
  stalls despite heavy one-sided volume/delta).
- **Exhaustion** — climactic volume/delta that fails to extend (initiative dries up).
- **Delta / CVD divergence** — price makes a new extreme while cumulative delta does not.
- **Footprint imbalances** — stacked diagonal bid/ask imbalances showing initiative.
- **Trapped traders / failed auction** — acceptance beyond a level that reverses,
  leaving late participants offside.

Structure tells us **where** to care (context). Order flow tells us **when** and
**whether** to act (trigger). Confluence tells us **how much** to trust it.

---

## 1. Strategy definition

### 1.1 The three layers (never conflate them)

| Layer | Question | Source |
|---|---|---|
| **Structure (context)** | *Where* is price relative to auction reference points? | PD VA, IB, weekly/session levels |
| **Trigger (event)** | *Is an institutional footprint confirming action here, now?* | Footprint / order flow |
| **Confluence (conviction)** | *How many independent reads agree?* | Agreement engine |

A trade requires **all three**: a meaningful location, an order-flow event, and
non-conflicting confluence. Structure alone is not a signal. An order-flow event in
no-man's-land is not a signal.

### 1.2 Structural reference set (kept from prior work)

- **Prior-day RTH Value Area:** POC, VAH, VAL (computed from tick/volume-at-price, 70% VA).
- **80% Rule zone:** value area edges + acceptance logic.
- **Initial Balance:** first-hour high/low (context and target, not a clock trigger).
- **Weekly:** weekly VPOC, prior-week high/low.
- **Session:** overnight high/low, prior-day OHLC, naked POCs.
- **Daily-anchored VWAP** (reset 18:00 ET) ± standard deviations.

### 1.3 Signal families — redefined on order flow

Each family keeps its *intent* but swaps its *trigger* from timing to footprint.

**FOLLOW (continuation / initiative beyond value)**
- *Intent:* trade acceptance and continuation beyond the value area.
- *Old trigger (flaw):* N consecutive 15-min closes beyond VAH/VAL.
- *New trigger:* price trades beyond value **and** order flow confirms *initiative* —
  positive (for longs) stacked imbalances in the trend direction, expanding CVD,
  **no absorption** against the move, and acceptance (trade + rest) rather than a wick.

**FADE (80% Rule mean reversion)**
- *Intent:* failed excursion outside value → rotation back through value to the far edge.
- *Old trigger (flaw):* first 15-min close back inside value.
- *New trigger:* price re-enters value **and** the excursion is shown to have *failed* —
  absorption at the extreme, delta divergence into the high/low, exhaustion of initiative,
  trapped breakout traders. FADE is the **strongest historical edge**; protect its quality.

**REV (rejection / reversal at a prior-day level)**
- *Intent:* rejection at PD POC/VAH/VAL and reversal.
- *Old trigger (flaw):* wick/close rejection counting over a fixed window.
- *New trigger:* test of the level **and** absorption + exhaustion + divergence confirming
  the level is defended. REV must have **structure nearby** (it *is* a level-reaction signal).

> Ordering note: build FOLLOW (long/short) and FADE first. Add REV once the order-flow
> feature library and the FOLLOW/FADE triggers are validated.

---

## 2. Design philosophy (non-negotiable)

1. **Evidence before trust.** No edge is believed until it is backtested with honest,
   out-of-sample validation. Negative results are first-class citizens and must be reported
   plainly. (Three prior hypotheses were *inverted* by data — that is the process working.)
2. **Events, not clocks.** Triggers are auction events. Time may *gate* (session windows)
   but never *trigger*.
3. **Separation of concerns.** Structure, trigger, confluence, and management are distinct
   modules with clean interfaces. A change to exits must never require touching trigger code.
4. **Confluence is the edge.** The single most robust prior finding: independent reads that
   *agree* massively outperform any lone signal; opposing reads mean *stand aside*. The
   hierarchy is **regime → structure → trigger**, weighted, not equal-voting.
5. **Respect no-man's-land.** Signals far from any structural level underperform. Distance to
   structure is a first-class feature and a filter.
6. **Human-tradeable by design.** A statistically positive system with an untradeable drawdown
   or win rate is worthless. Management targets a win rate and drawdown a human can actually sit.
7. **Simplicity is earned.** Prefer the smallest model that captures the edge. Complexity must
   pay for itself in validated expectancy, not in narrative.

---

## 3. Carried-forward validated knowledge (do not re-litigate without new data)

These are conclusions from ~5 years of MNQ backtesting + a 6-month replay-log validation.
Treat as priors; re-test as the order-flow triggers change the signal set.

- **REV is a US-session-only edge.** Overnight REV loses. Gate REV to RTH.
- **Confluence dominates.** Lone signal ≈ break-even/negative; 2 independent reads aligned ≈
  strongly positive; opposing reads ≈ negative. Build the agreement engine early.
- **Conflict veto.** An opposing signal in the same session is the single biggest noise filter.
- **No-man's-land is the real failure mode.** Signals >~0.5×ATR from the nearest structural
  level underperform badly. (This *inverted* the original "signals into a zone fail" hypothesis —
  it is the void, not the wall, that kills trades.) REV/FADE want structure *near*; FOLLOW is
  less sensitive.
- **The day-type score predicts direction, not magnitude.** Use it as a directional tilt
  (~64% at |score| ≥ 4), never to size for a "big RR" day (correlation with range ≈ 0).
- **Management: 1.5R scale-and-trail hybrid.** Take 50% at 1.5R, move to breakeven, trail the
  remainder. Converts a 21%-win / −43%-DD runner system into ~50–56% win / ~−13.5% DD, PF ~2.0.
  Lower total profit than a pure runner, far higher risk-adjusted return and *tradeability*.
- **Time-based triggers are the known flaw.** The entire rebuild exists to remove them.

> **These findings are priors, not gospel.** See `docs/challenge_and_open_questions.md` for the
> honest confidence level of each, exactly where each is weak, and a standing invitation to
> falsify them. Three of these priors came from *inverting* an original hypothesis when data
> contradicted it — keep doing that. See `docs/visual_layer_subgraphs.md` for the subgraph /
> drawing-layer development record (why each existed, which are now redundant, what to rebuild).

---

## 4. Parameters (the knobs — centralize, never hard-code inline)

All parameters live in one config module (Python) and mirror as ACSIL inputs. Every knob has
a default, a range, and a one-line rationale.

**Structural**
- `va_percent` (default 70%) — value area coverage.
- `session_start` / `session_end` (RTH, ET) — trading window.
- `ib_minutes` (default 60) — IB duration (context only, not a trigger).
- `vwap_reset` (18:00 ET) — daily VWAP anchor.

**Order-flow / footprint**
- `delta_div_lookback` — bars/levels for price-vs-delta divergence detection.
- `absorption_vol_z` — z-score of resting-volume absorption vs local norm.
- `absorption_price_stall_ticks` — max price travel that still counts as absorption.
- `exhaustion_climax_z` — climactic volume/delta threshold.
- `imbalance_ratio` (e.g. 3.0) — diagonal bid/ask ratio for a footprint imbalance.
- `stacked_imbalance_min` — consecutive imbalances to confirm initiative.
- `acceptance_definition` — trade-and-rest criteria (replaces "N closes").

**Filter**
- `no_mans_land_atr` (default 0.5) — max distance to nearest structure, in ATR.
- `rev_us_only` (default true) — gate REV to RTH.
- `conflict_veto` (default true) — stand aside on opposing same-session reads.

**Risk / management**
- `risk_per_trade` (default 1%) — fixed-fractional.
- `min_stop_pts` (default 15 MNQ) — sizing sanity floor.
- `tgt1_R` (default 1.5) — first scale target.
- `runner` — trail method (swing / ATR).
- Prop-account: trailing-drawdown model, daily-loss limit, max contracts.

**Costs (always modeled)**
- `entry_slippage` (1 tick), `stop_slippage` (3 ticks), `commission` (round-trip $/contract).

---

## 5. Architecture & tech stack

**Environment:** VS Code + GitHub + Claude Code (local). Python for research/backtest;
ACSIL (C++) for the live Sierra Chart study. Rithmic feed for live + historical tick/footprint.

**Two-track codebase (shared parameter definitions, mirrored logic):**
- **Research track (Python):** data ingestion, feature engineering, backtests, validation.
  Fast iteration, honest statistics, the "brain" where edges are discovered and proven.
- **Live track (ACSIL/C++):** the Sierra Chart study/DLL that reproduces the *validated*
  logic on the live feed. Only validated logic is ported. The study is a faithful executor,
  not a place to invent signals.

**Suggested repository layout**
```
/config          # single source of truth for all parameters (yaml/py) + mirrored ACSIL inputs
/data            # loaders: tick/footprint ingestion, resampling, VA/VWAP builders
/features        # order-flow feature library (delta, CVD, absorption, exhaustion, imbalance)
/structure       # PD VA, IB, weekly/session levels, no-man's-land distance
/signals         # FOLLOW / FADE / REV trigger logic (event-based)
/fusion          # agreement engine + similarity + decision fusion → conviction
/management      # exits (1.5R hybrid), sizing, prop-risk intelligence
/backtest        # engine, walk-forward, Monte Carlo, cost model
/validation      # OOS reports, regime splits, tearsheets
/acsil           # C++ study source, build notes
/docs            # this file, phase specs, decision log
```

**Data contract:** every module consumes and emits typed, timestamped records with an explicit
timezone (ET). Footprint data must retain per-price bid/ask volume; do not collapse to OHLC
before features are computed.

---

## 6. Development rules

1. **Config-driven.** No magic numbers in logic. Every constant is a named parameter with a
   rationale in `/config`.
2. **Backtest before port.** A trigger is not written into ACSIL until it is validated in
   Python with costs, OOS, and a regime split.
3. **One trigger, one module, one test.** Each signal family has its own file and its own test
   suite (unit tests on synthetic footprints + a regression test on a fixed historical slice).
4. **Cost model is mandatory** in every economic result. No frictionless numbers in reports.
5. **Honest reporting.** Every backtest states n, win%, PF, expectancy (R), max drawdown, and
   the sample window. Small-n and regime caveats are stated, not buried. If data contradicts a
   hypothesis, say so and invert the design.
6. **Decision log.** Every accepted/rejected edge gets a dated entry in `/docs/decisions.md`
   with the evidence. This prevents re-litigating settled questions.
7. **Git discipline.** Feature branches per phase/signal; PR includes the validation report;
   `main` is always in a known-good, buildable state. Tag releases per phase.
8. **ACSIL gotchas (known):** `Input::GetString()` returns `const char*`; HUD/marker text needs
   a non-const `SCString&` via `.Format()`; embed `\n` for multiline; use persistent ints keyed
   by date for once-per-day events; read same-chart studies via `GetStudyArrayUsingID`; separate
   Sierra Chart instances cannot share study arrays (use a file bus if needed).
9. **Determinism.** Given the same data and config, a backtest must reproduce exactly. Seed any
   stochastic step; version the data.
10. **No silent overfitting.** A filter derived from a small sample ships as a *flag*, not a
    hard suppressor, until an independent test confirms it (precedent: no-man's-land started as
    a flag, hard-suppressed for REV only once two tests agreed).

---

## 7. Development phases

> Each phase has **Objective → Deliverables → Acceptance criteria → Status**.
> Do not advance until acceptance criteria are met and logged.

### Phase 1 — Foundation Engine
**Status: Code complete, gate nearly passed, one narrow item open.** All modules
implemented, 57/57 unit tests green, including a real-data regression test against the
user's actual MNQU6.CME.scid tick data. Byte-level inspection of the real file found and
fixed 3 `.scid` parser bugs (missing magic header, wrong datetime field type, missing
price scale). Reconciling against a real Sierra-displayed ground truth (2026-07-07:
VAH=29587/POC=29539/VAL=29320) **overturned an assumed rule** — D-011: the PD VA window
is the FULL session (18:00 ET prior day → RTH close), not RTH-only as the source note and
both legacy `.cpp` files' comments claimed. VAH now matches within ~3 ticks; POC/VAL are
a near photo-finish between two comparably-sized volume nodes (14% apart), tracked as an
open item in D-011 (likely a volume-counting difference vs. Sierra's native
`VolumeAtPriceForBars`, not a window/algorithm error). See `docs/phase1_report.md`. One
more day's reconciliation should confirm the gap is small and stable before opening Phase 2.
**Objective:** the plumbing. Reliable ingestion of tick/footprint data and construction of all
structural references, with correct sessions and timezones.
**Deliverables:**
- Tick/footprint loader (Rithmic export + Sierra `.scid`), ET-aligned, deduplicated.
- Value-area builder (true volume-at-price, 70% VA) for PD/weekly.
- IB, VWAP±SD, overnight/prior-day levels, naked POCs.
- No-man's-land distance function (distance to nearest structure, in ATR).
**Acceptance:** structural levels reproduce Sierra Chart's to within tick tolerance on a
sample month; sessions correct across DST; unit tests green.

### Phase 2 — Decision Engine
**Status: Planned**
**Objective:** the event-based trigger state machine for FOLLOW (long/short) and FADE — no
time triggers. Defines *acceptance*, *test*, *failure* in order-flow terms (stubs allowed for
features until Phase 3).
**Deliverables:** a signal state machine that consumes structure + (stubbed) features and emits
candidate signals with location, direction, and the event that fired them.
**Acceptance:** on historical slices, signals fire at auction events (not clock edges);
FOLLOW/FADE candidates are reproducible and inspectable.

### Phase 3 — Feature Engineering
**Status: Planned**
**Objective:** the institutional-grade order-flow feature library that powers triggers.
**Deliverables:** absorption, exhaustion, delta/CVD divergence, footprint imbalance & stacked
imbalances, acceptance (trade-and-rest), trapped-trader detection — each a tested function with
tunable parameters from `/config`.
**Acceptance:** each feature validated on hand-labeled synthetic footprints + spot-checked on
real tape; FOLLOW/FADE triggers now consume real features and beat the old time-based signal
set on expectancy (with costs, OOS).

### Phase 4 — Similarity Intelligence
**Status: Planned**
**Objective:** for a live setup, find historically analogous setups (feature-vector nearest
neighbors) and estimate an empirical probability/expectancy distribution — "this looks like
these N past setups, which resolved thus."
**Deliverables:** feature-vector encoding of setups, a similarity index, and a calibrated
probability estimate with sample size and confidence.
**Acceptance:** similarity-estimated probabilities are calibrated OOS (reliability curve);
adds incremental expectancy over structure+trigger alone.

### Phase 5 — Decision Fusion
**Status: Planned**
**Objective:** fuse structure + trigger + confluence (agreement) + similarity into one
conviction score and a go/no-go decision. Evolves the validated agreement engine
(regime → structure → trigger, weighted; conflict veto; no-man's-land filter).
**Deliverables:** a fusion module emitting direction + conviction (HIGH/MOD/LOW/CONFLICT) + a
one-line rationale; the score used as directional tilt, never magnitude.
**Acceptance:** fused conviction is monotonic with realized expectancy OOS; conflict/no-man's-land
cases are correctly down-weighted or vetoed.

### Phase 6 — Trade Management & Risk Intelligence
**Status: Planned**
**Objective:** turn a positive signal into a tradeable outcome. Exits, sizing, and prop-account
risk.
**Deliverables:** 1.5R scale-and-trail hybrid (50% at 1.5R, BE, trail); dynamic/structural stops;
fixed-fractional sizing with min-stop floor and contract caps; prop trailing-drawdown and
daily-loss guards; Monte Carlo blow-up estimates.
**Acceptance:** management lifts risk-adjusted return (return/DD) and lands win rate + max
drawdown in a human-tradeable band; prop rules never breached in simulation.

### Phase 7 — Statistical Validation
**Status: Planned**
**Objective:** prove the whole system, honestly and out-of-sample.
**Deliverables:** walk-forward across regimes (bull/bear/chop), Monte Carlo on trade order,
per-signal/per-session/per-regime economics, full cost model, tearsheets. A replay-log
cross-check against the live ACSIL study to confirm the port is faithful.
**Acceptance:** positive expectancy OOS across regimes with stated caveats; live study signal
counts match the research engine within tolerance; no unexplained divergence.

### Phase 8 — Production Release
**Status: Planned, structural slice started early.** `acsil/OrderFlowAuctionStudy.cpp` ports
the validated Phase 1 structural layer (PD VAH/POC/VAL with the D-011 window correction, IB,
weekly, no-man's-land) — no signal logic yet, since FADE/FOLLOW/REV still need Phase 2/3
Python validation first (dev rule #2). Not yet built/tested in Sierra Chart (no ACSIL
compiler in the research environment) — needs a build pass and compile-error fixes before
it's real. Full Phase 8 scope (signals, alerts, live conviction HUD, logging) stays gated
on Phases 2-7.
**Objective:** deploy the validated logic live.
**Deliverables:** the ACSIL study/DLL with only validated logic, HUD showing frozen structural
read + live conviction, alerts/ntfy, a signal+decision logger, and a monitoring/journaling loop
that feeds realized trades back into Phase 4/7.
**Acceptance:** live signals reconcile with backtest; logging complete; a documented go-live
checklist and rollback plan.

---

## 8. Definition of done (per edge)

An edge is "done" only when: it is config-driven, unit-tested, validated OOS with costs across
regimes, logged in `/docs/decisions.md` with evidence, ported faithfully to ACSIL, and its live
fires reconcile with the backtest. Anything less is a hypothesis, not an edge.

---

## 9. Trading-context note

This is a trading-mechanics and software project, not financial advice. All performance figures
are simulated/backtested; past results do not guarantee future outcomes. Forward-test on sim
before committing real capital, and size within prop-account and personal risk limits.
