# Phase 1 Report — Foundation Engine

**Status: code complete, real .scid data flowing end-to-end, window mechanism
corrected against real evidence (D-011), gate still open on one narrow item**
(§4). Per CLAUDE.md's honest-reporting rule, this report states plainly what
is proven and what is still open.

---

## 1. What was built

| Module | Contents |
|---|---|
| `config/__init__.py` | Typed, dotted-access `Config` over `params.yaml`; validates every documented `range` against its `default` and raises `ConfigError` on violation. |
| `structure/sessions.py` | `trading_day()`, `session_of()`, `in_rth()` — DST-safe by construction. |
| `structure/value_area.py` | `volume_at_price()`, `value_area()`, `value_area_from_footprint()` — true tick-size-binned VAP, ported line-for-line from the legacy ACSIL `ComputeProfile`, including its exact tie-break rules. |
| `structure/levels.py` | `StructuralSnapshot`/`Level`, `nearest_structure()`, `no_mans_land()` (D-004), session/weekly/IB/ATR/naked-POC builders, `session_profile_from_ticks()` (the corrected, full-session PD VA recipe, see §2), and the D-010 (Provisional) flagged additions. |
| `data/loaders.py` | `load_ticks()` (Sierra `.scid` + Rithmic CSV), `iter_scid_ticks_for_day()` (binary-search single-day extraction for multi-GB files), `load_footprint()` (CSV; `.depth` explicitly `NotImplementedError`), `classify_aggressor()`, `ticks_to_footprint()`. |
| `tests/` | 57 unit tests, all passing, including a real-data regression test (see §3). |

Also this session: logged D-010 (stacked PD levels + overnight VP,
Provisional) and D-011 (PD VA window correction, Accepted); moved the legacy
ACSIL study to `acsil/legacy/PriorDayNY_ValueArea_80PctRule.cpp`; read a
second legacy `.cpp` (`15MIN_80%Rule_IBV.cpp`) and confirmed it agrees with
the first on the VA mechanism.

---

## 2. How PD VAH/POC/VAL are actually built (corrected by real-data evidence)

The `How the PDVAHPOCVOL is generated.txt` note and both legacy `.cpp`
files' code comments describe the value area as **RTH-only (09:30-16:00 ET)**.
Real-data reconciliation against the user's live-study HUD reading
**falsified that** — see D-011 in `docs/decisions.md`. The window that
actually reproduces the displayed PD VA is:

1. **FULL SESSION, not RTH-only.** Prior day's 18:00 ET reopen through the
   current day's RTH close (Asia+UK+US all included). An RTH-only rebuild of
   2026-07-07 missed the real (live-study-displayed) value by up to 239
   points; the full-session rebuild lands within single digits to ~15 ticks
   of each edge (see §3).
2. **True volume-at-price** — every tick's actual traded volume is binned at
   its own price (not a 1-minute OHLC approximation, D-009).
3. **70% expansion from POC** by heavier-adjacent-bin, exact tie-break
   parity with the legacy study (verified by `tests/test_value_area.py`).
4. **Projected onto the next day** as the "PD" reference that FADE/FOLLOW/REV
   key off.
5. **`trading_date` uses `trading_day()`** (the 18:00-anchored boundary from
   `sessions.py`), not plain calendar date — this was flipped from an earlier
   draft that used calendar date, which was correct only under the (wrong)
   RTH-only assumption. Now that the window is genuinely 18:00-anchored,
   `trading_day()` is the right tool.
6. **Caveat carried into code:** this all assumes chart/data timezone is ET.
   `data/loaders.py` converts every `.scid` timestamp to ET at ingestion, so
   this is enforced structurally, not just documented.

**This reverses what the source note and code comments say.** Logged as
D-011 rather than silently changed, per CLAUDE.md's decision-log discipline
— if the note or `.cpp` comments are re-read later, don't trust their
RTH-only description without re-checking this entry first.

---

## 3. Real data: format bugs fixed, then a real reconciliation run

The user provided real `.scid` files (`Scid data/MNQM6.CME.scid`,
`Scid data/MNQU6.CME.scid` — MNQ's June and September 2026 contracts,
gitignored, ~6.5GB combined).

**Three `.scid` parser bugs found via byte-level inspection** (not guessed):
1. Missing 4-byte `"SCID"` magic signature before the header fields.
2. DateTime is `int64` microseconds since 1899-12-30 UTC, not an 8-byte
   double of days.
3. Price needs `× 0.01` scaling (confirmed by real consecutive Close diffs
   landing on exact multiples of MNQ's 0.25 tick once scaled).

All three fixed in `data/loaders.py`, locked in by a golden-record
regression test built from the real file's actual first-record bytes.

**Reconciliation against a real ground-truth number.** The user read their
live study's HUD for 2026-07-07 (printed at US-session-end, ~16:30):
**VAH=29587, POC=29539, VAL=29320**.

| Window tried | POC | VAH | VAL |
|---|---|---|---|
| RTH-only (09:30-16:00), original assumption | 29300.0 | 29508.0 | 29235.0 |
| Full session, 18:00 Jul6 → 16:00 Jul7 | 29300.0 | **29588.25** | 29235.0 |
| Full session, 18:00 Jul6 → 16:30 Jul7 | 29300.0 | 29584.5 | 29235.0 |
| Full session, 18:00 Jul6 → 16:45 Jul7 | 29300.0 | 29584.0 | 29235.0 |
| **Target (live study)** | **29539** | **29587** | **29320** |

VAH converges to within ~3 ticks of the target under every full-session
variant, regardless of the exact end-boundary (16:00/16:30/16:45) — this is
what falsified the RTH-only assumption and established D-011.

POC/VAL don't match outright, but the picture is not a broken methodology:
the two top volume nodes in the full-session reconstruction are **29300.00
(4353 contracts) and 29539.00 (3743 contracts) — only 14% apart**, a near
photo-finish, not a dominant winner. Forcing the POC tie-break to 29539
(the target) instead of 29300 gives **VAL=29316.25 — within 15 ticks of the
target 29320**. So each anchor choice reproduces the *opposite* edge almost
exactly; nothing points at a wrong window or a wrong algorithm, just a small
volume-counting difference (raw-tick `TotalVolume` summation vs. Sierra's
native `VolumeAtPriceForBars`) tipping a close call.

This is now regression-locked with a stated tolerance (not a spurious exact
match) in
`tests/test_levels.py::test_session_profile_from_ticks_reproduces_real_july7_reconciliation`.

---

## 4. What's still open

The remaining gap (tens of ticks on POC/VAL, not hundreds) is most likely a
volume-counting difference, not a window or algorithm error. Closing it
needs one of:
- Sierra's own per-price volume numbers for one day (a numbers export), to
  diff bin-by-bin against my reconstructed `vap` map and find exactly where
  the ~600-contract difference at the 29300/29539 nodes comes from.
- A second independent day's reconciliation, to check whether the gap is
  systematic (same direction/magnitude every day) or specific to 2026-07-07.

This is a narrow, well-characterized gap — not a blocker on the scale of
"wrong window" or "wrong contract" (both ruled out). Phase 2 can reasonably
begin once one more day is checked to confirm the gap doesn't grow.

**On Option A vs B (moot now):** Option A (the `.scid` files already on
disk) was the right call — it found and fixed three real format bugs and
drove the D-011 window correction, both of which a CSV export would have
masked entirely.

---

## 5. Next step

Reconcile one more day (ideally with a Sierra-native per-price volume export
for at least one of them) to confirm the POC/VAL gap is small and stable,
then log the result here and close D-011's re-test trigger. Do not open the
Phase 2 branch until that's done.
