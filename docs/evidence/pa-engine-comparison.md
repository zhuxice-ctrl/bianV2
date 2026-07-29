# PA Engine Comparison: Legacy vs Deterministic Event Engine

Both engines were run on the restored BTC/ETH/BNB 4h files. The numerical table is
evidence of semantic differences, not a claim that the engines use identical sizing.

| Asset | Legacy return | New return | Legacy MDD | New MDD | Legacy trades | New trades |
|---|---:|---:|---:|---:|---:|---:|
| BNBUSDT | -0.0739 | -0.2459 | -0.2361 | -0.3584 | 65 | 68 |
| BTCUSDT | 0.2785 | 0.1879 | -0.1764 | -0.2586 | 63 | 66 |
| ETHUSDT | 0.1604 | 0.3969 | -0.2837 | -0.3665 | 61 | 68 |

## Semantic differences

- Both enter no earlier than the next bar open.
- The new engine applies explicit adverse slippage and fees on every fill.
- Same-bar stop/target conflicts use the explicit conservative `STOP_FIRST` policy.
- The new engine caps notional at current equity and uses Decimal arithmetic.
- The legacy engine uses 2% stop-risk sizing; the new comparison uses gross limit 1.0.
- Final open positions are explicitly closed at the final close in this comparison.

## Promotion result

Decision: **FAIL**
Reasons: `POSITIVE_FOLD_RATIO, MEDIAN_SHARPE, SHARPE_CI_LOWER, BASELINE_INCREMENT`

See `pa-validation-result.json` for fold, stress, locked-holdout, manifest,
dataset-hash, and diagnostic evidence.
