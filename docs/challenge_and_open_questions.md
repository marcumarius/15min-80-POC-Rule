# Challenge This Study — Open Questions & Standing Invitation

> **Everything in `docs/decisions.md` is a prior, not a truth.** The single most valuable
> thing the next developer (human or Claude) can do is try to *break* our conclusions. If
> you prove one wrong, that is not a setback — it is the process working. Log it and invert.
>
> This document exists to make that easy: it lists what we concluded, **how confident we
> actually are**, exactly **where each conclusion is weak**, and **how to challenge it**. It
> also invites entirely different approaches we may have missed.

---

## 1. The honest confidence table

| Decision | Conclusion | Confidence | Weakest point |
|----------|-----------|-----------|---------------|
| D-002 | Confluence is the edge | **High** | Reads may be less *independent* than assumed |
| D-003 | Conflict veto | **High** | Could be discarding good contrarian setups |
| D-001 | REV US-only | **Medium-High** | Order-flow REV may behave differently overnight |
| D-006 | 1.5R hybrid management | **Medium-High** | Exit tuned on the same data it's judged on |
| D-008 | Costs mandatory | **High** | Slippage is *estimated*, not measured |
| D-004 | No-man's-land failure mode | **Medium** | Crude outcome model; 6-month + one regime |
| D-005 | Score = direction not magnitude | **Medium** | 173 days, small buckets, regime-tinted |
| D-009 | True VAP required | **High** | — (methodological, not empirical) |

If a conclusion is "Medium" or below, treat it as *actively open*. Do not build load-bearing
logic on it without re-testing.

---

## 2. The assumptions most worth attacking

**2.1 "Our backtest measured the right signals."**
FADE and Asia-FOLLOW diverged from the live study (~60% match) due to VA/acceptance
approximation. So any FADE/Asia-FOLLOW economics are **provisional**. *Challenge:* rebuild VA
from true tick VAP (Phase 1) and re-derive those signals; the conclusions about them may shift.

**2.2 "No-man's-land is the failure mode."**
This came from a **crude outcome model** (fixed ATR, immediate entry, single runner exit) on
**6 months** in **one regime**, and it *inverted* the original hypothesis — which is exactly
when you should be most suspicious of a fresh, convenient story. *Challenge:* re-test with the
proper 1.5R exit and true-VAP signals across multiple regimes. Does the effect survive? Is
0.5×ATR really the threshold, or an artifact of this window? Does it hold for FADE with a real
sample (we only had 4 no-man's-land FADEs)?

**2.3 "Confluence reads are independent."**
The confluence edge (D-002) assumes FADE/FOLLOW/REV are *independent* votes. If they're all
downstream of the same value-area position, they may be correlated — in which case "2 aligned"
is partly double-counting. *Challenge:* measure the correlation between the reads. If high, the
confluence edge is weaker than it looks and the agreement engine needs de-correlated inputs.

**2.4 "The score is directional truth."**
The 64%-at-|score|≥4 directional hit-rate came from a window that may have trended. *Challenge:*
split by regime. Is the direction edge real in chop, or is it just "the trend continued in a
trending sample"?

**2.5 "The 1.5R hybrid is optimal."**
`tgt1_R` was chosen on the same data used to judge it — a mild in-sample bias. *Challenge:*
walk-forward the exit choice. Does 1.5R win out-of-sample, or did we curve-fit the target?

**2.6 "Slippage of 1/3 ticks is right."**
Estimated, never measured. On fast MNQ moves with size, stop slippage can be far worse.
*Challenge:* measure realized slippage from actual fills (Phase 8) and feed it back. If it's
worse, thin-edge signals (FOLLOW especially) may not survive.

---

## 3. Bigger structural challenges (invite better approaches)

Do not assume our *framing* is right, either. Worth genuinely considering:

- **Is the FADE/FOLLOW/REV taxonomy the right carving?** Maybe order flow suggests different,
  cleaner primitives (e.g. "absorption reversal," "initiative continuation," "failed auction")
  that don't map 1:1 to the old families. Let the footprint data define the taxonomy rather
  than forcing it into the inherited buckets.

- **Should structure be the anchor at all, or order flow first?** We assume structure locates
  and order flow triggers. An alternative: detect institutional footprints *first*, then check
  whether they occur at structure. The ordering could change what's found.

- **Is a rules engine the right tool, or should Phase 4 similarity subsume the triggers?** If a
  nearest-neighbor / learned model on order-flow features predicts outcomes well, hand-coded
  triggers may be redundant. Test the learned approach against the rules; let the better one win.

- **Are we over-fitting to MNQ's recent regime?** Everything is one instrument, ~5 years, a
  strong-trend-heavy sample. Challenge on NQ, MES, and deliberately across a bear/chop split.

- **Is fixed 1% risk the right sizing** given the low win rate and prop trailing-drawdown
  mechanics? Explore volatility-scaled or conviction-scaled sizing — but validate, don't assume.

---

## 4. How to challenge (the workflow)

1. Pick a conclusion. State the null hypothesis ("no-man's-land has no effect on expectancy").
2. Design the cleanest test that could **falsify** it — out-of-sample, cost-modeled, regime-split.
3. Run it. Report n, win%, PF, expectancy, max DD, and the sample window — honestly, including
   if it's inconclusive.
4. **If it falsifies our prior:** write a superseding Decision-Log entry, invert the design, and
   celebrate — you just made the system more honest.
5. **If it confirms:** upgrade the confidence level and note the independent replication.

The bar for *overturning* a prior is a clean falsifying test. The bar for *questioning* one is
zero — question everything, always.

---

## 5. Standing note to Claude

When working this codebase: do not defer to these conclusions because they're written down.
If the data in front of you disagrees with a Decision-Log entry, say so plainly and show the
evidence — that is exactly the behavior this project was built on. Three of our priors came
from *inverting* an original hypothesis when the data contradicted it. Keep doing that. A
confident, well-evidenced "I think we were wrong about X, here's why" is worth more than a
hundred agreeable confirmations.
