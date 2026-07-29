# PA Engine Comparison: Legacy vs New Event Engine

## Overview

This document compares the legacy Price Action (PA) backtest engine with the new
deterministic event-driven engine. Both engines were run on identical BTC/ETH/BNB
4h snapshot data to surface semantic differences in entry timing, conflict
resolution, cost modeling, and position handling.

## Key Differences

| Dimension | Legacy Engine | New Event Engine |
|---|---|---|
| **Entry timing** | Signal bar's `entry = open.shift(-1)` (next bar open) | Signal at bar *t* fills at bar *t+1* open (causal delay) |
| **Same-bar conflict** | Checks stop first, then target (implicit) | Explicit `STOP_FIRST` / `TARGET_FIRST` policy |
| **Fee model** | `TAKER_FEE + SLIPPAGE` deducted from risk amount | Separate `taker_fee_bps` and `slippage_bps`, fee on every fill |
| **Slippage** | Applied as part of cost on entry only | Adverse slippage on entry (longs pay more, shorts receive less) |
| **Trade count** | One position at a time, skips overlapping signals | One position at a time, explicit position close before new entry |
| **Return calculation** | Per-trade PnL based on entry/exit prices | Per-bar equity mark-to-market + per-trade PnL |
| **Open position at end** | Last trade may remain open | Explicit `close_at_end` flag (True = close at last close, False = mark) |
| **Funding** | Not modeled | Explicit `FundingEvent` at matching timestamps |
| **Exposure limit** | Risk-based sizing (`risk_pct * capital / risk`) | `gross_limit * equity` cap on notional |
| **Precision** | `float` (binary floating-point) | `Decimal` (exact arithmetic) |

## Expected Differences

Differences caused by more conservative explicit semantics are **expected
evidence**, not reasons to alter the new engine to match old headline returns:

1. **Lower trade count in new engine**: The new engine applies stricter
   exposure limits and explicit position management, which may skip some
   signals that the legacy engine would have traded.

2. **Different PnL for same-bar conflicts**: The `STOP_FIRST` policy is
   more conservative than the legacy engine's implicit ordering, leading
   to potentially different exit prices when both stop and target are
   touched in the same bar.

3. **Funding impact**: The new engine models funding cash flows, which
   the legacy engine ignores. Long positions in positive funding
   environments will show lower returns in the new engine.

4. **Slippage asymmetry**: The new engine applies adverse slippage
   directionally (longs pay more, shorts receive less), while the legacy
   engine applies a symmetric cost. This leads to slightly different
   entry/exit prices.

5. **Decimal precision**: The new engine uses `Decimal` for all monetary
   arithmetic, eliminating binary floating-point rounding errors present
   in the legacy engine's `float` calculations.

## PA Promotion Result

The legacy PA strategy was run through the new promotion gate using
`configs/experiments/baseline_pa.yaml`. The result is persisted regardless
of pass/fail. The adapter receives **no exemption** from positive-fold,
Sharpe, drawdown, stress, concentration, or locked-holdout rules.

### Evaluation

- **Positive fold ratio**: Must be ≥ 0.70
- **Median Sharpe**: Must be ≥ 0.80
- **Sharpe CI lower bound**: Must be > 0.0
- **Normal max drawdown**: Must be ≥ -0.15
- **Stress drawdown**: Must be ≥ -0.25

The PA strategy's performance on these gates is evaluated using the walk-forward
folds from the normal scenario and the stress drawdown from the price_spike /
double_cost scenarios. Any failure is recorded with a stable reason code.

## Conclusion

The new event engine provides stricter, more explicit, and more reproducible
semantics than the legacy engine. The PA strategy enters through the same
`SignalRecord` protocol as any other factor, and its promotion decision is
based on the same gates. Differences in headline returns between the two
engines are expected and documented above.
