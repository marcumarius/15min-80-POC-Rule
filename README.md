# Order-Flow Auction Strategy

Intraday MNQ/NQ (and MES) auction strategy for the US RTH session. Keeps the proven
structural framework (prior-day Value Area / 80% Rule, IB, weekly/session levels) but
**replaces time-based triggers with order-flow / footprint events** (absorption,
exhaustion, delta/CVD divergence, imbalances, trapped traders).

**Start here:** [`CLAUDE.md`](./CLAUDE.md) — strategy, philosophy, parameters, dev rules,
and the 8-phase roadmap. Then [`docs/decisions.md`](./docs/decisions.md) for carried-forward
validated findings, [`docs/phase1_foundation_engine.md`](./docs/phase1_foundation_engine.md)
for the first build spec, and [`docs/phase1_report.md`](./docs/phase1_report.md) for its
current status (code complete, real-data reconciliation still pending).

## Layout
| Dir | Purpose |
|-----|---------|
| `config/` | single source of truth for all parameters |
| `data/` | tick/footprint ingestion, resampling, data contract |
| `structure/` | PD VA, IB, weekly/session levels, no-man's-land distance |
| `features/` | order-flow feature library (Phase 3) |
| `signals/` | FOLLOW / FADE / REV event-based triggers (Phase 2) |
| `fusion/` | agreement engine + similarity + decision fusion (Phase 4-5) |
| `management/` | exits (1.5R hybrid), sizing, prop-risk (Phase 6) |
| `backtest/` | engine, walk-forward, Monte Carlo, cost model |
| `validation/` | OOS reports, regime splits, tearsheets (Phase 7) |
| `acsil/` | Sierra Chart C++ live study (Phase 8) |

## Two-track model
- **Research (Python):** where edges are discovered and *proven* (fast, honest, statistical).
- **Live (ACSIL/C++):** faithfully executes only *validated* logic on the live feed.

Trading-mechanics/software project, not financial advice. All figures are simulated; forward-test
on sim before real capital.
