# Baseline-0 Evidence Status

## Reproducible
The BTC/ETH/BNB 4h Price Action baseline is replayed from the tracked CSV snapshot and compared with `tests/golden/baseline_summary.json`.

## Archival only
`results/experiments.json` and `results/experiments_summary.md` describe 165 historical runs, but `main@59e8bcb` and `dashboard_v2_1.zip` do not contain the generator script. These files are useful negative evidence, especially the failed OOS results, but are not treated as reproducible experiment outputs.

## Consequence
The new validation engine must rebuild the anti-overfitting protocol from explicit code and manifests. It must not claim numerical continuity with the archival 165-run report.
