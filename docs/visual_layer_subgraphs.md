# Visual Layer — Subgraph & Drawing Development Record

> Why every subgraph and drawing group in the *old* study existed, what it was for,
> which are now **redundant**, and what the order-flow rebuild should keep, drop, or add.
> Preserved so the visual layer is rebuilt deliberately — not cargo-culted forward.
>
> Read alongside `docs/decisions.md`. Everything here is a **prior to question**, not a
> spec to copy. See `docs/challenge_and_open_questions.md`.

---

## 1. Why a structured drawing layer at all

In ACSIL, every plotted line, marker, HUD panel, and guide is either a **Subgraph**
(styleable, toggleable, exportable series) or an **ACS chart drawing** (managed by a
unique `LineNumber`). The old study used a deliberate **line-number base-offset map** so
that each family of drawings occupied its own numeric block and could be cleared/redrawn
without colliding. That discipline is worth keeping; the *content* is what changes.

### 1.1 Line-number base-offset map (old study)

| Base | Group | Purpose |
|------|-------|---------|
| 100000 | Prior-day VA | VAH / POC / VAL lines + labels |
| 200000–280000 | Signal markers | FADE / FOLLOW / IVB markers by type/session |
| 300000 | HUD | Playbook text panel |
| 400000 | Initial Balance | IB high / low / mid |
| 500000 | Weekly | Weekly VPOC, prior-week H/L |
| 600000–690000 | Signal timestamps | Per-signal time/price labels |
| 700000–740000 | IVB | Initial-balance extension targets |
| 800000 | Naked POCs | Untested prior POCs |
| 850000 | REV markers | Rejection/reversal markers |
| 960000 | Guides | Entry / stop / target / trailing-stop lines |

> Keep this base-offset convention in the rebuild. Reassign blocks as the visual content
> changes (see section 4), but never let two families share a base — collisions cause the
> "ghost line" bugs that are painful to trace.

---

## 2. Subgraph / drawing groups — what each was for

**Prior-day Value Area (base 100000)** — VAH (green), POC (magenta), VAL (red) as separate
subgraphs so each is individually styleable and toggleable. *Why:* these are the anchor of
the 80% Rule; traders need them visually distinct and always on. **Keep.**

**Initial Balance (base 400000)** — IB high/low (and mid). *Why:* context and target
reference; the IB range frames the day's opening auction. **Keep** (as context — never a
trigger; see D-007).

**Weekly (base 500000)** — weekly VPOC + prior-week high/low. *Why:* higher-timeframe
structure for the no-man's-land distance and directional context. **Keep.**

**VWAP ± SD** — daily-anchored VWAP with standard-deviation bands. *Why:* mean-reversion /
extension context and the REV VWAP-side gate. **Keep, but demote** — the IB-scalper work
found VWAP *confluence* largely **redundant** with other levels for signal quality (it added
little discriminating power). Keep it plotted for context and for the REV VWAP-side gate;
do **not** treat VWAP confluence as an independent confluence vote.

**Naked POCs (base 800000)** — untested prior-session POCs. *Why:* magnet/target levels.
**Keep as context**, low priority.

**Signal markers (bases 200000–280000, 850000)** — FADE/FOLLOW/IVB/REV markers. *Why:*
mark where and when a signal fired. **Keep the mechanism, replace the trigger** — in the
rebuild these fire on order-flow events, not clock closes (D-007).

**HUD (base 300000)** — the Playbook panel. *Why:* at-a-glance day state. **Keep**, in its
**improved split form**: `STRUCT(@IB)` (frozen structural read) + `LIVE` (evolving
conviction) shown separately. The old single `SCORE | CONVICTION` line is **redundant** —
it smeared a frozen structural read together with an evolving live read into one changing
number (the confusion that motivated the split).

**Guides (base 960000)** — yellow=entry, red=stop, green-solid=static target,
green-dashed=trailing stop. *Why:* visualize the 1.5R hybrid management (scale at the green
line, trail the dashed). **Keep** — they map directly to D-006 and were applied to FADE +
FOLLOW only (correctly; REV/IVB didn't need static guides).

---

## 3. Now redundant / to deprecate

| Item | Base | Why redundant | Action |
|------|------|---------------|--------|
| **IVB signals + extension targets** | 200000-280000, 700000-740000 | IVB was never a validated edge focus; guides were deliberately not applied to it; it added markers without proven expectancy | **Drop** in rebuild unless order-flow re-validates it |
| **Per-signal timestamp labels** | 600000-690000 | Stripped/reduced already due to visual overlap; the marker + HUD legend already convey type/time | **Drop** — rely on marker color + right-axis price + logger |
| **Old single SCORE/CONVICTION HUD line** | 300000 | Smeared frozen structural + live reads into one drifting number | **Superseded** by split STRUCT(@IB) / LIVE |
| **VWAP as a confluence vote** | — | Found redundant with other levels for signal quality | **Demote** to context + REV gate only |
| **Volatility filter visuals** (if any) | — | Volatility filters were non-discriminating in the IB-scalper testing | **Drop** unless re-derived |

> None of these are "delete and forget" — each has a Decision-Log rationale. If order-flow
> re-validation revives one (e.g. IVB on absorption), resurrect it with a fresh entry.

---

## 4. What the order-flow rebuild's visual layer should add

The trigger changes from timing to auction events, so the visuals gain a **footprint /
order-flow read-out**. Proposed new groups (assign fresh base blocks):

- **Delta / CVD subgraph** — cumulative delta line (session-anchored) with divergence
  markers where price makes a new extreme and CVD does not (D-005 direction context).
- **Absorption flags** — mark bars/levels where passive volume absorbed aggression
  (price stalled under heavy one-sided delta).
- **Exhaustion flags** — climactic volume/delta that failed to extend.
- **Imbalance / stacked-imbalance markers** — diagonal bid/ask imbalance stacks showing
  initiative in the trend direction.
- **No-man's-land shading** — visually shade zones >0.5×ATR from any structure so a
  discretionary eye instantly sees when a setup is in the void (D-004).

Design rule: the visual layer should let a human *see the reason* a signal fired (which
order-flow event) and *see the risk context* (distance to structure, conflicting reads) —
not just a bare arrow. Every marker should be traceable to the event that produced it.

---

## 5. Carry-forward ACSIL drawing gotchas

- Clear drawings with `sc.DeleteACSChartDrawing`; keep the base-offset blocks so a redraw
  clears only its own family.
- HUD/marker text needs a non-const `SCString&` via `.Format()`; embed `\n` for multiline.
- Labels overlap fast on a busy chart — prefer color + right-axis price + a HUD legend over
  per-drawing text (the timestamp-label removal was for exactly this reason).
- Guide lines are identified by color + right-axis price, not text, to reduce clutter.
