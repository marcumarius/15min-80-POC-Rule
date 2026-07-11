# Phase 1 Report — Foundation Engine

**Status: code complete, gate NOT yet passed.** Per CLAUDE.md's honest-reporting
rule, this report states plainly what is proven and what is still only
unit-tested against synthetic fixtures.

---

## 1. What was built

| Module | Contents |
|---|---|
| `config/__init__.py` | Typed, dotted-access `Config` over `params.yaml`; validates every documented `range` against its `default` and raises `ConfigError` on violation. |
| `structure/sessions.py` | `trading_day()`, `session_of()`, `in_rth()` — all DST-safe by construction (compare local wall-clock `time()` off a tz-aware ET datetime; no manual offset math). |
| `structure/value_area.py` | `volume_at_price()`, `value_area()`, `value_area_from_footprint()` — true tick-size-binned VAP, ported line-for-line from the legacy ACSIL `ComputeProfile` including its exact tie-break rules (POC ties favor the lower price; expansion ties favor the upper neighbor). |
| `structure/levels.py` | `StructuralSnapshot`/`Level`, `nearest_structure()`, `no_mans_land()` (D-004), plus session/weekly/IB/ATR/naked-POC builders and the D-010 (Provisional) flagged additions: `compute_overnight_vp()`, `level_stack_distance()`/`is_stacked()`. |
| `data/loaders.py` | `load_ticks()` (Sierra `.scid` + Rithmic CSV), `load_footprint()` (CSV; `.depth` explicitly `NotImplementedError`), `classify_aggressor()`, `ticks_to_footprint()`. |
| `tests/` | 50 unit tests, all passing, covering every module above with synthetic/hand-constructed fixtures. |

Also this session: logged Decision D-010 (stacked PD levels + overnight
session volume profile, Provisional) in `docs/decisions.md`; moved the legacy
ACSIL study to `acsil/legacy/PriorDayNY_ValueArea_80PctRule.cpp` as the
concrete evidence source for D-007.

---

## 2. Acceptance criteria — status against docs/phase1_foundation_engine.md §4

1. **"Structural levels reproduce Sierra Chart's to within tick tolerance on
   a sample month."** ❌ **Not done.** No real tick/footprint data exists in
   this repo. `value_area()` is a faithful port of the legacy study's proven
   `ComputeProfile` algorithm (same binning, same tie-breaks), so it should
   reproduce Sierra's output once fed real data — but that is an expectation,
   not a measurement. This is the single most important open item.
2. **"Sessions/trading-day mapping correct across a DST transition."** ✅
   Unit-tested against the actual 2026 US DST dates (spring-forward
   2026-03-08, fall-back 2026-11-01, confirmed via `zoneinfo` rather than
   assumed) and against two dates with different UTC offsets. Correctness
   here is structural (wall-clock comparison on a tz-aware datetime), not
   date-specific, but the tests pin real transition dates rather than
   fabricated ones.
3. **"`no_mans_land` and `nearest_structure` verified against hand-computed
   cases."** ✅ Done — both are pure functions over a hand-constructed
   `StructuralSnapshot`, independent of any data pipeline; 8 tests cover
   direction handling, the ATR threshold, zero-ATR, and no-structure-in-
   direction edge cases.
4. **"Loaders are deterministic, deduplicated, ET-aligned, DST-safe."**
   ⚠️ **Partially done.** The Rithmic-CSV path is tested for dedup/sort. The
   `.scid` binary parser is implemented against Sierra's documented
   `s_IntradayFileHeader`/`s_IntradayRecord` layout and round-trips against a
   *hand-built* file matching that layout — but no real `.scid` export exists
   to confirm the layout assumption (endianness, epoch, UTC-vs-local
   timestamping) is actually correct. `load_footprint()` only handles a CSV
   footprint export; `.depth` raises `NotImplementedError` rather than guess
   at an undocumented binary format.
5. **"All unit + regression tests green; snapshot output is reproducible."**
   ✅ 50/50 unit tests pass (`pytest tests/`). ❌ No regression test on a
   fixed historical slice exists yet — there is no historical slice, real or
   sample, in the repo to regress against.
6. **This report.** ✅ (this file) — but it cannot state a VA reconciliation
   max-tick-error, because no reconciliation has happened.

---

## 3. The real gate: no sample data exists

Every "✅" above is a unit test against synthetic or hand-built fixtures, not
a validation against real market data. Per CLAUDE.md §2.1 ("evidence before
trust") and §6.5 ("honest reporting"), Phase 1 should **not** be marked
complete/accepted in `docs/decisions.md` until:

- A real `.scid` or Rithmic tick export (even one sample day) is available to
  confirm `_load_scid_ticks`'s byte-layout and timezone assumptions.
- A real footprint/VAP export (even one sample day) is available to run
  `value_area()` against and compare POC/VAH/VAL to Sierra Chart's own display
  for that day, producing the tick-tolerance number criterion 1 requires.
- That comparison is written up here with the actual max-tick-error observed.

**Until then, treat every function in this phase as "correctly implements
the documented algorithm," not "produces correct real-world values."** The
distinction matters most for `_load_scid_ticks` (D-009/D-007's whole
premise — true VAP instead of 1-min approximation — depends on this being
right) and for D-010's overnight-VP feature (already Provisional and
off-by-default, so lower risk).

---

## 4. Next step

Do not open the Phase 2 branch yet. Next action is obtaining one real sample
day of tick/footprint data (Rithmic export or Sierra `.scid`/footprint CSV)
to run the criterion-1 reconciliation and close out this report's open items.
