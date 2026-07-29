# PA Validation Result

- Decision: **FAIL**
- Reasons: `POSITIVE_FOLD_RATIO, MEDIAN_SHARPE, SHARPE_CI_LOWER, BASELINE_INCREMENT`
- Positive fold ratio: `0.5000`
- Median Sharpe: `-0.7852`
- Sharpe CI lower: `-3.2369`
- Normal max drawdown: `-0.0961`
- Stress drawdown: `-0.1005`

## OOS folds

| Fold | Net return | Sharpe | Max drawdown |
|---:|---:|---:|---:|
| 0 | 0.2303 | 5.7747 | -0.0766 |
| 1 | -0.0859 | -4.4551 | -0.0961 |
| 2 | -0.0375 | -1.7203 | -0.0702 |
| 3 | 0.0009 | 0.1499 | -0.0350 |

## Locked holdout

Portfolio return: `-0.0480`
Portfolio Sharpe: `-1.0095`
Portfolio max drawdown: `-0.1037`

The locked holdout was evaluated once after research folds and was not used for tuning.
