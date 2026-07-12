# Phase 1 — Foundation Engine (Build Spec)

**Status:** Planned → *first phase to build*
**Objective:** the plumbing. Reliable ingestion of tick/footprint data and construction of
every structural reference, with correct sessions and timezones. No signals, no order flow yet —
just a trustworthy substrate that everything else stands on.

> Guiding rule: Phase 1 is "done" only when the structural levels reproduce Sierra Chart's to
> within tick tolerance on a sample month, sessions are correct across DST, and all unit tests
> are green. Get this wrong and every later phase inherits the error.

---

## 1. Scope

**In scope**
- Data ingestion: Rithmic exports and Sierra `.scid`/`.depth` tick + footprint data.
- Timezone + session handling (ET, DST-aware; futures session boundaries).
- Structural reference construction: prior-day Value Area (POC/VAH/VAL) from **true**
  volume-at-price, Initial Balance, weekly VPOC + prior-week H/L, overnight H/L, prior-day OHLC,
  naked POCs, daily-anchored VWAP ± SD.
- No-man's-land distance function (distance to nearest structure, in ATR).
- A clean, typed, timezone-explicit data contract that all downstream modules consume.

**Out of scope (later phases)**
- Any order-flow feature (Phase 3), any signal/trigger (Phase 2), fusion, management, backtest.

**Flagged/optional (D-010, Provisional — build behind `overnight_vp_enable`, off by default)**
- Overnight (Asia+UK) session volume profile: HVN/POC/LVN as an additional `Level kind` in
  `StructuralSnapshot`.
- Level-stacking metric: PD POC-to-nearest-VA-edge distance, flagged when below
  `level_stack_tol_ticks`. Not a hard filter — exposed as a field for Phase 5's confluence
  engine to weight later.

---

## 2. Data contract (the interface everything else depends on)

Define once, in `/data`, and never break it silently.

**Tick record**
```
Tick:
  ts: datetime (tz-aware, ET)   # exchange timestamp
  price: float
  volume: int
  aggressor: {buy, sell, unknown}   # from bid/ask trade classification
```

**Footprint cell (price × time bucket)**
```
FootprintCell:
  ts_bucket: datetime (ET)
  price: float
  bid_volume: int    # traded at bid (sell aggression)
  ask_volume: int    # traded at ask (buy aggression)
```
> Do NOT collapse footprint to OHLC before Phase 3 needs per-price bid/ask volume. Preserve it.

**Bar (derived, for context/plotting only — never for triggers)**
```
Bar: ts, open, high, low, close, volume, delta (ask_vol - bid_vol)
```

**StructuralSnapshot (Phase 1's primary output, per trading day)**
```
StructuralSnapshot:
  date: date
  pd_va: {poc, vah, val}          # prior-day RTH value area
  ib: {high, low, mid}            # initial balance (context)
  weekly: {vpoc, pw_high, pw_low}
  overnight: {high, low}
  prior_day: {open, high, low, close}
  naked_pocs: [float, ...]
  vwap_anchor_ts: datetime
  atr_daily: float
  levels(): -> list[Level]        # flattened, for distance queries
```

**Level (for no-man's-land distance)**
```
Level: name: str, price: float, kind: {va, ib, weekly, session, vwap}
```

---

## 3. Deliverables

### 3.1 `data/loaders.py`
- `load_ticks(path) -> Iterable[Tick]` — parse Rithmic/`.scid`, ET-align, deduplicate, sort.
- `load_footprint(path) -> Iterable[FootprintCell]` — preserve per-price bid/ask volume.
- Aggressor classification (bid/ask trade side) if not provided by the feed.
- **Acceptance:** row counts and timestamps reconcile with source; no dupes; monotonic ts;
  DST transitions handled (no missing/duplicated hour).

### 3.2 `structure/sessions.py`
- `trading_day(ts) -> date` — map a timestamp to its futures trading day (18:00 ET boundary).
- `session_of(ts) -> {asia, uk, us}` and `in_rth(ts) -> bool`.
- **Acceptance:** correct classification across a DST-spanning sample; Sunday 18:00 reopen maps
  to Monday's trading day.

### 3.3 `structure/value_area.py`
- `value_area(vap, tick_size, va_percent) -> {poc, vah, val}` — **true** volume-at-price,
  **tick-size bins** (corrected from an earlier "1-pt bins" draft wording — Sierra's own VAP
  bins at tick resolution, so matching it within *tick* tolerance requires binning at
  `tick_size`, not a rounded whole point), 70% expansion from POC (up/down by heavier
  adjacent bin, ties favor the lower price on POC selection and the upper bin on expansion —
  mirrors the legacy `ComputeProfile` tie-breaking exactly). This is the true-VAP fix from
  D-009. `volume_at_price(cells, tick_size) -> vap` builds the input map from footprint cells.
  **Window (D-011, corrects an earlier RTH-only assumption):** despite both legacy `.cpp`
  files' code comments and the source `.txt` note describing PD VAH/POC/VAL as built from
  09:30-16:00 ET only, real-data reconciliation against the live study's own displayed values
  falsified that — the window that actually reproduces the displayed PD VA is the **full
  18:00-anchored session** (prior day 18:00 ET reopen through current-day RTH close,
  Asia+UK+US). See `structure/levels.py::session_profile_from_ticks()` and D-011 for the
  evidence; feed it the full session, not `in_rth()`-filtered ticks.
- **Acceptance:** on a sample month, VAH/POC/VAL match Sierra Chart's VA study within tick
  tolerance. This is the single most important acceptance test in Phase 1.

### 3.4 `structure/levels.py`
- Build the full `StructuralSnapshot`: PD VA, IB, weekly VPOC + PW H/L, overnight H/L,
  prior-day OHLC, naked POCs, daily-anchored VWAP ± SD, daily ATR(14).
- `nearest_structure(price, direction, snapshot) -> (level, distance_pts)`.
- `no_mans_land(price, direction, snapshot, atr, max_atr) -> bool` (D-004).
- **Acceptance:** distances match hand calculations; no-man's-land flag matches known cases.

### 3.5 `config/__init__.py`
- Load `params.yaml`, validate types/ranges, expose a typed `Config` object.
- **Acceptance:** invalid/out-of-range values raise clearly; defaults load correctly.

### 3.6 Tests (`/tests` or per-module)
- Unit tests for sessions/DST, value-area math (synthetic distributions with known POC/VA),
  distance/no-man's-land, and loader dedup/ordering.
- One **regression test** on a fixed historical slice: snapshot output is byte-stable given
  the same data + config (determinism rule, CLAUDE.md §6.9).

---

## 4. Acceptance criteria (phase gate)

Phase 1 is complete when **all** hold:
1. Structural levels reproduce Sierra Chart's to within tick tolerance on a sample month
   (VA is the critical one).
2. Sessions/trading-day mapping correct across a DST transition.
3. `no_mans_land` and `nearest_structure` verified against hand-computed cases.
4. Loaders are deterministic, deduplicated, ET-aligned, DST-safe.
5. All unit + regression tests green; snapshot output is reproducible.
6. A short `docs/phase1_report.md` records the VA reconciliation (max tick error observed).

Only then open the Phase 2 branch.

---

## 5. Risks & notes

- **Footprint/tick data is heavy and feed-sensitive.** Budget time for loader edge cases
  (session gaps, half-days, roll dates). Prefer a continuous back-adjusted contract for history.
- **Do not approximate VA from 1-min bars** (D-009). The whole point of Phase 1 is true VAP.
- **Preserve bid/ask per price** — Phase 3 order-flow features are impossible if footprint is
  flattened here.
- **Timezone bugs are silent and catastrophic.** Every record is tz-aware ET from ingestion on.
  A prior project had prior-day OHLC levels bleed across the overnight session from a session
  misconfig — test this explicitly.

---

## 6. Suggested first commit sequence

1. `config/params.yaml` + `config/__init__.py` loader (+ tests). *(params.yaml already seeded.)*
2. Data contract types (`data/types.py`).
3. `data/loaders.py` + loader tests.
4. `structure/sessions.py` + DST tests.
5. `structure/value_area.py` + VA math tests, then the Sierra reconciliation.
6. `structure/levels.py` (snapshot + distance/no-man's-land) + tests.
7. `docs/phase1_report.md` with the VA reconciliation result → phase gate review.
