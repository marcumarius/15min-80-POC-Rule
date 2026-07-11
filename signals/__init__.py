"""Event-based trigger state machine (Phase 2): FOLLOW long/short, FADE, then REV.
Consumes structure + order-flow features; emits candidate signals with location,
direction, and the auction EVENT that fired them. No time triggers (Decision D-007)."""
