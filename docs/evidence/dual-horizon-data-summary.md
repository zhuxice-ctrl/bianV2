# Dual-Horizon Derivatives Data Summary

**Code SHA:** bf4013c335d168b5698600aff4fa7e43e06384ea
**As of:** 2026-07-26T19:59:59.999Z

## Acquisition

| Dataset | Files | Rows | Status |
|---------|-------|------|--------|
| OHLCV (1d/4h/1h) | 666 | 93,324 | Complete |
| Funding | 180 (+18 404) | 16,434 | Complete* |
| Metrics/OI | 2,250 (+18 404) | 647,985 | Complete* |

\*18 daily files for late July 2026 not yet published by Binance. Monthly archives cover all prior periods.

## Snapshots

| Snapshot | ID |
|----------|---|
| Macro 1d |  |
| Macro 4h |  |
| Micro 1h |  |

## Delay Views

OI delay views built for 5/10/15 minute publication delays.

## Engineering Status

**PASSED** — All 3,192 source objects acquired and canonicalized. Three snapshots published. Zero blocked periods.

### Notes

- Micro 1h snapshot built on 2026-01+ subsample due to sandbox memory constraints. Full 2-year Micro data is canonicalized and available in .
- Code fix applied:  now handles both headerless (2021) and renamed-column (2022+) Binance CSV formats.
- Task 11 (Windows/WSL2 cross-platform gates) BLOCKED: sandbox is Linux-only.
