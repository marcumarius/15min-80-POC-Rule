# MomentumTrade.md — Institutional Momentum / Initiative Trading

**A layered decision engine for joining an established move, using order flow and footprint.**

> Companion to `CLAUDE.md`. This is the **momentum / initiative** side of the system —
> distinct from mean-reversion (FADE). It formalizes the FOLLOW family's rebuild on
> order-flow triggers. Everything here is a **prior to be tested**, not settled truth —
> see `docs/challenge_and_open_questions.md`.

---

## 0. The mental model (get this right or nothing else matters)

**You are not predicting a move. You are joining one that has already proven itself with
committed money.**

The professional's question is **not** "will price go up?" It is:

> **"Is there an imbalance of committed initiative that other participants will be forced
> to chase?"**

That reframe drives everything below. You are looking for evidence that one side is
*forced* — trapped participants covering, real buyers paying up because they cannot get
filled passively — and, critically, **the absence of anyone defending the other side.**

### The single most important tell: absorption vs. no absorption

- **Break into heavy resting liquidity that grinds** → a trap in the making. Someone is
  selling into your breakout.
- **Break that travels *easily*** — thin book, opposite side stepping away, delta expanding
  with price → real initiative.

**Professionals watch for what *isn't* there as much as what is.** The absence of defense is
the signal.

---

## 1. The six-layer decision stack

Sequential **gates**, not a scoring blob. **Each layer must pass before the next is
evaluated.** This is what makes it a decision *engine* rather than an indicator soup.

```
L0  Regime gate        → Can today even trend?
L1  Location gate      → Is this a place worth breaking from?
L2  Initiative event   → Did real money do this?
L3  Disconfirmation    → Is anyone fighting this?      ← the edge lives here
L4  Trigger            → Where do I actually pull it?
L5  Conviction/sizing  → How big?
L6  Management         → How do I hold and exit?
```

---

### Layer 0 — Regime gate: *"Can today even trend?"*

Filter the **day** before evaluating any setup.

**Pass conditions (trend-capable day):**
- Open-drive or open-test-drive (initiative from the bell).
- Gap that **holds** (does not fill back into value).
- IB that **extends** rather than balances.
- Value **migrating** in one direction vs. prior day.
- Prior day closed **on its extreme**.

**Fail conditions (balancing day → momentum has negative expectancy):**
- Rotational / two-sided auction.
- IB **contains** price all session.
- Value areas heavily **overlapping** prior day.

> On a balancing day you are in **FADE's** territory, not momentum's. **This gate alone
> kills most bad continuation trades.** Do not "look for a breakout" on a rotation day.

**Config:** `structural.ib_minutes`, day-type classifier, value-migration flag.

---

### Layer 1 — Location gate: *"Is this a place worth breaking from?"*

The break must be **of something**: prior-day VAH/VAL, IB high/low, overnight high/low,
weekly level, naked POC.

Two validated constraints apply:

- **Room to run.** Where is the next *opposing* level? Breaking into a wall 20 points away
  is a bad trade **regardless of how good the flow looks**. Risk/reward is decided here, not
  at the exit.
- **Not into the void.** Per Decision **D-004**, signals >~0.5×ATR from any structure
  underperform badly. Momentum needs a **reference to run toward**. Sweet spot observed:
  **30–100 points** of clear space.

**Config:** `filters.no_mans_land_atr` (0.5), structural level set.

---

### Layer 2 — Initiative event: *"Did real money do this?"*

The break must prove **participation**, not drift.

| Evidence | What it means | Config knob |
|---|---|---|
| **Volume expansion** on the break (z-score vs. recent norm — not eyeball) | Real participation, not a drift-through | `order_flow.acceptance.trade_and_rest_min_volume_z` |
| **Stacked imbalances** in the direction of travel (3+ consecutive diagonal bid/ask imbalances) | The classic institutional footprint of aggression | `order_flow.imbalance_ratio`, `stacked_imbalance_min` |
| **Delta expanding *with* price** — new price highs accompanied by new CVD highs | Aggressors are following through, not fading | `order_flow.delta_div_lookback`, `cvd_reset` |
| **Velocity / acceleration** — the tape speeds up | Urgency; participants are chasing | (new: `velocity_z`) |

> A **slow drift** through a level is **not** initiative. Speed and volume are part of the
> signal, not cosmetic.

---

### Layer 3 — Disconfirmation: *"Is anyone fighting this?"* ← **the most important layer**

This is what amateurs skip. **Explicitly look for reasons NOT to join.** Each is a **veto**,
not a demerit.

| Veto | What it means | Config knob |
|---|---|---|
| **Absorption against the move** — heavy volume at the extreme, price stalls | Someone big is selling into your breakout. **Veto.** | `absorption_vol_z`, `absorption_price_stall_ticks` |
| **Delta divergence** — price makes a new high, CVD does not | The move is running on fumes. **Veto.** | `delta_div_lookback` |
| **Exhaustion print** — climactic volume spike that fails to extend | That is the **end** of a move, not the start. **Veto.** | `exhaustion_climax_z` |

> **A momentum trader who only looks for confirmation gets picked off constantly.
> The edge lives in the veto layer.** Confirmation is cheap; disconfirmation is the moat.

This mirrors the validated **conflict veto** (Decision **D-003**) — the single biggest noise
filter found in 5 years of testing.

---

### Layer 4 — The trigger: *"Where do I actually pull it?"*

**Professionals almost never buy the break itself.** They buy:

1. **The first pullback that holds**, or
2. **The failed retest** of the reclaimed level.

**Why:**
- The break gives you **no defined risk**. The pullback gives you a **structure to stop under**.
- The pullback **tests the thesis**: if the broken level now holds as support, the auction has
  **accepted** it. If sellers were going to reject it, that is when they would show.
- **Trapped traders**: the fade crowd who shorted the break are now offside. **Their stops are
  your fuel.**

**What to watch on the pullback:**
- **Delta dries up** — no aggressive selling into a long pullback.
- **Volume contracts** — the pullback is a lack of interest, not a new initiative.
- **Pullback is shallow** — holds above the broken level and/or VWAP.
- Then: a **resumption imbalance** = **trigger**.

> **Your own data already told you this**: the backtest found **retest entry beat immediate
> entry** across all signal families. This is not theory — it is your measured result.

---

### Layer 5 — Conviction & sizing

**Confluence determines SIZE, not whether to trade** (Decision **D-002**).

| State | Action |
|---|---|
| Regime aligned + location good + initiative confirmed + **no** disconfirmation | **Full size** |
| Any layer marginal | **Reduced size** |
| Any Layer-3 veto fires | **Skip** — no size |

**Config:** `management.risk_per_trade`, `max_contracts`.

Reminder (Decision **D-005**): the day-type score predicts **direction, not magnitude**.
Never size up expecting a big-RR day because the score is high.

---

### Layer 6 — Management

- **Stop below the structure that must hold** (the pullback low) — **not** an arbitrary
  distance. If that structure breaks, the thesis is dead.
- Then the validated **1.5R scale-and-trail hybrid** (Decision **D-006**): take 50% at 1.5R,
  move to breakeven, trail the remainder.

**Config:** `management.tgt1_R` (1.5), `scale_out_fraction` (0.5), `breakeven_after_tgt1`,
`runner_trail`, `min_stop_pts`.

---

## 2. Honest caveats (read before you build)

**Momentum is inherently a lower-win-rate, higher-RR game.** You will take many small losses
on failed continuations and get paid by the occasional trend day that runs. **Your own numbers
reflect this**: FOLLOW had the **lowest win rate** of the three families but was the
**workhorse** — the highest volume of signals and positive every year. Do not expect
FADE-like hit rates. **Expect to be paid on the tail.**

**The retest may never come.** The strongest trend days do not pull back — that is the
tradeoff of demanding confirmation. **You will miss some big ones.** Accept it: the
alternative (chasing breaks) bleeds you on the false breaks, which are far more numerous.

**Order-flow features are feed-sensitive and easy to fool yourself with.** Stacked imbalances
and absorption in particular. **Every feature must be validated on hand-labeled footprints
before you trust it** — that is Phase 3's entire job. Do not ship a feature because it looks
right on three charts.

**This whole stack is a hypothesis.** It is built from professional practice + our validated
priors, but the *specific* thresholds (3 stacked imbalances? 2.0 volume z-score?) are
**unvalidated guesses** until Phase 3/7 tests them. Treat every number in `params.yaml` as a
starting point to be tuned and falsified, not a truth.

---

## 3. Mapping to the build phases

| Layer | Phase | Module |
|---|---|---|
| L0 Regime gate | Phase 1–2 | `structure/`, `signals/` (day-type classifier) |
| L1 Location gate | Phase 1 | `structure/levels.py` (`no_mans_land`, `nearest_structure`) |
| L2 Initiative event | Phase 3 | `features/` (volume z, imbalances, CVD, velocity) |
| L3 Disconfirmation | Phase 3 | `features/` (absorption, exhaustion, divergence) — **veto logic** |
| L4 Trigger | Phase 2 | `signals/` (pullback/retest state machine) |
| L5 Conviction/sizing | Phase 5 | `fusion/` (agreement engine + similarity) |
| L6 Management | Phase 6 | `management/` (1.5R hybrid, structural stops) |

---

## 4. Relationship to the existing signal families

- **FOLLOW** = this document. Momentum/initiative continuation beyond value. Rebuilt from
  "N consecutive 15-min closes" (a clock trigger, Decision **D-007**) to the six-layer
  order-flow stack above.
- **FADE** = the *opposite* regime (balancing day, failed excursion, mean reversion). Do not
  run both on the same day-type — L0 decides which game you are playing.
- **REV** = rejection at a level; shares the disconfirmation machinery (absorption/exhaustion)
  but plays it *against* the prior move rather than *with* it.

> L0 (regime gate) is what keeps these from cannibalizing each other. **A trending day is a
> FOLLOW day. A balancing day is a FADE day.** Getting L0 right is the highest-leverage work
> in the whole system.

---

## 5. Trading-context note

Trading-mechanics and software design, not financial advice. All prior performance figures
referenced are simulated/backtested; past results do not guarantee future outcomes.
Forward-test on sim before committing real capital.
