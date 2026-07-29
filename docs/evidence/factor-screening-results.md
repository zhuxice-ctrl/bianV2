# Price/Volume Factor Screening Results

## Run identity

- Run ID: `cff58bfd-6beb-49f8-b0c8-a90945d88c36`
- Code SHA: `5ea6269c89066ff25782ad2db6742ae01fef2077`
- Dataset snapshot: `legacy-ohlcv-4h-473a859a0d90dbe7e4559592761f5613faa9d381b188d08b3e49d61a7e079a94`
- Assets: BTCUSDT, ETHUSDT, BNBUSDT
- Interval: 4h
- Availability: OHLCV close and volume become usable at CSV close_time; factor decision timestamp equals available_time

## Decision

**No factor is automatically promoted to candidate.** This screen creates auditable observations; promotion remains a separate decision gate.

Funding/OI real-data screening is **BLOCKED** because no canonical Funding/OI snapshot is present. Causal fixture tests are not treated as market evidence.

## Multiple-testing summary

| Factor | Tested slices | BH-surviving slices |
|---|---:|---:|
| momentum_24 | 26 | 0 |
| reversal_12 | 26 | 0 |
| realized_vol_24 | 26 | 0 |
| volume_surprise_24 | 26 | 0 |
| amihud_24 | 26 | 0 |

## Redundancy clusters

| Factor | Cluster | Rejection reason |
|---|---:|---|
| amihud_24 | 4 | representative |
| momentum_24 | 1 | representative |
| realized_vol_24 | 3 | representative |
| reversal_12 | 2 | representative |
| volume_surprise_24 | 5 | representative |

## Incremental validation

| Factor | Standalone IC | Delta IC | Delta cost-adjusted return | Incremental |
|---|---:|---:|---:|---|
| momentum_24 | -0.0042 | 0.0138 | -0.0001 | False |
| reversal_12 | -0.0315 | 0.0089 | -0.0000 | False |
| realized_vol_24 | -0.0470 | 0.0094 | 0.0002 | True |
| volume_surprise_24 | -0.0189 | -0.0396 | -0.0005 | False |
| amihud_24 | 0.0184 | 0.0000 | 0.0000 | False |

## Lifecycle state

| Factor | State after evidence run |
|---|---|
| amihud_24 | observed |
| momentum_24 | observed |
| realized_vol_24 | observed |
| reversal_12 | observed |
| volume_surprise_24 | observed |

## Per-fold / asset / regime evidence

The table below contains no pooled replacement metric. Raw and BH-adjusted p-values for every row are retained in the companion JSON file.

| Factor | Fold | Asset | Regime | RankIC | Pearson IC | Coverage | N | RankIC CI | Raw p |
|---|---|---|---|---:|---:|---:|---:|---|---:|
| momentum_24 | fold_0 | BNBUSDT | range_low_vol | 0.0408 | 0.0745 | 1.0000 | 91 | [-0.1833, 0.2333] | 0.7013 |
| momentum_24 | fold_0 | BNBUSDT | range_high_vol | -0.0482 | -0.0744 | 1.0000 | 89 | [-0.2570, 0.2192] | 0.6536 |
| momentum_24 | fold_0 | BNBUSDT | trend_low_vol | -0.0571 | 0.1394 | 1.0000 | 47 | [-0.2802, 0.0975] | 0.7029 |
| momentum_24 | fold_0 | BNBUSDT | trend_high_vol | -0.1616 | -0.0117 | 1.0000 | 43 | [-0.5293, 0.1405] | 0.3006 |
| momentum_24 | fold_0 | BNBUSDT | liquidity_stress | -0.1040 | -0.1012 | 1.0000 | 277 | [-0.2311, 0.0317] | 0.0840 |
| reversal_12 | fold_0 | BNBUSDT | range_low_vol | 0.0806 | 0.0261 | 1.0000 | 91 | [-0.1136, 0.2558] | 0.4474 |
| reversal_12 | fold_0 | BNBUSDT | range_high_vol | 0.0781 | 0.0613 | 1.0000 | 89 | [-0.1511, 0.3001] | 0.4669 |
| reversal_12 | fold_0 | BNBUSDT | trend_low_vol | -0.0298 | -0.3189 | 1.0000 | 47 | [-0.2643, 0.2707] | 0.8422 |
| reversal_12 | fold_0 | BNBUSDT | trend_high_vol | 0.0423 | -0.0472 | 1.0000 | 43 | [-0.2112, 0.3076] | 0.7875 |
| reversal_12 | fold_0 | BNBUSDT | liquidity_stress | 0.1005 | 0.0538 | 1.0000 | 277 | [-0.0312, 0.2192] | 0.0951 |
| realized_vol_24 | fold_0 | BNBUSDT | range_low_vol | -0.0072 | -0.0413 | 1.0000 | 91 | [-0.1951, 0.1454] | 0.9456 |
| realized_vol_24 | fold_0 | BNBUSDT | range_high_vol | 0.0893 | 0.1111 | 1.0000 | 89 | [-0.1224, 0.2341] | 0.4055 |
| realized_vol_24 | fold_0 | BNBUSDT | trend_low_vol | -0.0256 | -0.0917 | 1.0000 | 47 | [-0.2715, 0.1863] | 0.8646 |
| realized_vol_24 | fold_0 | BNBUSDT | trend_high_vol | -0.0015 | 0.0395 | 1.0000 | 43 | [-0.3038, 0.2293] | 0.9923 |
| realized_vol_24 | fold_0 | BNBUSDT | liquidity_stress | 0.0506 | 0.0913 | 1.0000 | 277 | [-0.0875, 0.1897] | 0.4014 |
| volume_surprise_24 | fold_0 | BNBUSDT | range_low_vol | 0.0107 | -0.0818 | 1.0000 | 91 | [-0.1746, 0.1951] | 0.9196 |
| volume_surprise_24 | fold_0 | BNBUSDT | range_high_vol | -0.0210 | -0.0048 | 1.0000 | 89 | [-0.1681, 0.1232] | 0.8450 |
| volume_surprise_24 | fold_0 | BNBUSDT | trend_low_vol | -0.0846 | -0.0969 | 1.0000 | 47 | [-0.2738, 0.0793] | 0.5716 |
| volume_surprise_24 | fold_0 | BNBUSDT | trend_high_vol | 0.2336 | 0.0966 | 1.0000 | 43 | [0.0132, 0.4600] | 0.1316 |
| volume_surprise_24 | fold_0 | BNBUSDT | liquidity_stress | -0.0136 | -0.0410 | 1.0000 | 277 | [-0.1474, 0.1019] | 0.8220 |
| amihud_24 | fold_0 | BNBUSDT | range_low_vol | 0.0708 | 0.1057 | 1.0000 | 91 | [-0.1071, 0.2278] | 0.5048 |
| amihud_24 | fold_0 | BNBUSDT | range_high_vol | 0.0561 | 0.0717 | 1.0000 | 89 | [-0.1038, 0.2142] | 0.6017 |
| amihud_24 | fold_0 | BNBUSDT | trend_low_vol | 0.1093 | 0.4608 | 1.0000 | 47 | [-0.1764, 0.3110] | 0.4647 |
| amihud_24 | fold_0 | BNBUSDT | trend_high_vol | -0.0091 | -0.0367 | 1.0000 | 43 | [-0.2436, 0.2264] | 0.9540 |
| amihud_24 | fold_0 | BNBUSDT | liquidity_stress | -0.0634 | -0.0601 | 1.0000 | 277 | [-0.1927, 0.0762] | 0.2932 |
| momentum_24 | fold_1 | BNBUSDT | trend_low_vol | 0.3765 | 0.3021 | 1.0000 | 20 | [n/a, n/a] | n/a |
| momentum_24 | fold_1 | BNBUSDT | range_low_vol | -0.1868 | -0.1631 | 1.0000 | 18 | [n/a, n/a] | n/a |
| momentum_24 | fold_1 | BNBUSDT | trend_high_vol | -0.1351 | -0.1275 | 1.0000 | 16 | [n/a, n/a] | n/a |
| momentum_24 | fold_1 | BNBUSDT | liquidity_stress | -0.0806 | -0.0032 | 1.0000 | 493 | [-0.1842, 0.0259] | 0.0737 |
| reversal_12 | fold_1 | BNBUSDT | trend_low_vol | -0.2361 | -0.3005 | 1.0000 | 20 | [n/a, n/a] | n/a |
| reversal_12 | fold_1 | BNBUSDT | range_low_vol | -0.0382 | -0.0394 | 1.0000 | 18 | [n/a, n/a] | n/a |
| reversal_12 | fold_1 | BNBUSDT | trend_high_vol | 0.2388 | 0.2246 | 1.0000 | 16 | [n/a, n/a] | n/a |
| reversal_12 | fold_1 | BNBUSDT | liquidity_stress | 0.0526 | -0.0109 | 1.0000 | 493 | [-0.0389, 0.1442] | 0.2441 |
| realized_vol_24 | fold_1 | BNBUSDT | trend_low_vol | -0.4015 | -0.3644 | 1.0000 | 20 | [n/a, n/a] | n/a |
| realized_vol_24 | fold_1 | BNBUSDT | range_low_vol | -0.2136 | -0.0617 | 1.0000 | 18 | [n/a, n/a] | n/a |
| realized_vol_24 | fold_1 | BNBUSDT | trend_high_vol | -0.3471 | -0.6261 | 1.0000 | 16 | [n/a, n/a] | n/a |
| realized_vol_24 | fold_1 | BNBUSDT | liquidity_stress | -0.0271 | -0.0261 | 1.0000 | 493 | [-0.1293, 0.0709] | 0.5483 |
| volume_surprise_24 | fold_1 | BNBUSDT | trend_low_vol | 0.3895 | 0.1182 | 1.0000 | 20 | [n/a, n/a] | n/a |
| volume_surprise_24 | fold_1 | BNBUSDT | range_low_vol | 0.1496 | -0.2341 | 1.0000 | 18 | [n/a, n/a] | n/a |
| volume_surprise_24 | fold_1 | BNBUSDT | trend_high_vol | 0.3647 | 0.3519 | 1.0000 | 16 | [n/a, n/a] | n/a |
| volume_surprise_24 | fold_1 | BNBUSDT | liquidity_stress | 0.0293 | 0.0317 | 1.0000 | 493 | [-0.0649, 0.1201] | 0.5159 |
| amihud_24 | fold_1 | BNBUSDT | trend_low_vol | -0.1910 | -0.2699 | 1.0000 | 20 | [n/a, n/a] | n/a |
| amihud_24 | fold_1 | BNBUSDT | range_low_vol | -0.2776 | -0.1069 | 1.0000 | 18 | [n/a, n/a] | n/a |
| amihud_24 | fold_1 | BNBUSDT | trend_high_vol | -0.3176 | -0.2766 | 1.0000 | 16 | [n/a, n/a] | n/a |
| amihud_24 | fold_1 | BNBUSDT | liquidity_stress | 0.0204 | 0.0425 | 1.0000 | 493 | [-0.0876, 0.1353] | 0.6511 |
| momentum_24 | fold_2 | BNBUSDT | range_low_vol | -0.0248 | -0.0212 | 0.9963 | 269 | [-0.1675, 0.1178] | 0.6855 |
| momentum_24 | fold_2 | BNBUSDT | trend_low_vol | -0.2499 | -0.2068 | 1.0000 | 122 | [-0.4180, -0.1132] | 0.0055 |
| momentum_24 | fold_2 | BNBUSDT | range_high_vol | 0.0835 | 0.1465 | 1.0000 | 23 | [n/a, n/a] | n/a |
| momentum_24 | fold_2 | BNBUSDT | trend_high_vol | -0.1976 | -0.1319 | 1.0000 | 26 | [n/a, n/a] | n/a |
| momentum_24 | fold_2 | BNBUSDT | liquidity_stress | -0.0118 | -0.0145 | 1.0000 | 102 | [-0.2048, 0.1370] | 0.9063 |
| reversal_12 | fold_2 | BNBUSDT | range_low_vol | -0.0764 | -0.1271 | 0.9963 | 269 | [-0.1813, 0.0340] | 0.2114 |
| reversal_12 | fold_2 | BNBUSDT | trend_low_vol | 0.2234 | 0.1140 | 1.0000 | 122 | [0.1035, 0.3853] | 0.0134 |
| reversal_12 | fold_2 | BNBUSDT | range_high_vol | -0.0682 | -0.2651 | 1.0000 | 23 | [n/a, n/a] | n/a |
| reversal_12 | fold_2 | BNBUSDT | trend_high_vol | 0.2287 | 0.1652 | 1.0000 | 26 | [n/a, n/a] | n/a |
| reversal_12 | fold_2 | BNBUSDT | liquidity_stress | 0.0833 | 0.1156 | 1.0000 | 102 | [-0.0526, 0.2756] | 0.4050 |
| realized_vol_24 | fold_2 | BNBUSDT | range_low_vol | 0.0171 | -0.0206 | 0.9963 | 269 | [-0.1010, 0.1311] | 0.7797 |
| realized_vol_24 | fold_2 | BNBUSDT | trend_low_vol | -0.0652 | -0.0719 | 1.0000 | 122 | [-0.2320, 0.1135] | 0.4757 |
| realized_vol_24 | fold_2 | BNBUSDT | range_high_vol | 0.0247 | 0.1084 | 1.0000 | 23 | [n/a, n/a] | n/a |
| realized_vol_24 | fold_2 | BNBUSDT | trend_high_vol | -0.0831 | -0.0367 | 1.0000 | 26 | [n/a, n/a] | n/a |
| realized_vol_24 | fold_2 | BNBUSDT | liquidity_stress | 0.0294 | -0.0442 | 1.0000 | 102 | [-0.1219, 0.1797] | 0.7695 |
| volume_surprise_24 | fold_2 | BNBUSDT | range_low_vol | -0.0014 | -0.0163 | 0.9963 | 269 | [-0.1136, 0.1009] | 0.9813 |
| volume_surprise_24 | fold_2 | BNBUSDT | trend_low_vol | 0.0036 | 0.0778 | 1.0000 | 122 | [-0.1914, 0.1764] | 0.9686 |
| volume_surprise_24 | fold_2 | BNBUSDT | range_high_vol | 0.1512 | 0.0362 | 1.0000 | 23 | [n/a, n/a] | n/a |
| volume_surprise_24 | fold_2 | BNBUSDT | trend_high_vol | 0.0591 | -0.0068 | 1.0000 | 26 | [n/a, n/a] | n/a |
| volume_surprise_24 | fold_2 | BNBUSDT | liquidity_stress | 0.0213 | 0.0059 | 1.0000 | 102 | [-0.1520, 0.2211] | 0.8318 |
| amihud_24 | fold_2 | BNBUSDT | range_low_vol | -0.0735 | -0.0340 | 0.9963 | 269 | [-0.2094, 0.0728] | 0.2296 |
| amihud_24 | fold_2 | BNBUSDT | trend_low_vol | 0.0462 | 0.0292 | 1.0000 | 122 | [-0.1094, 0.2288] | 0.6132 |
| amihud_24 | fold_2 | BNBUSDT | range_high_vol | 0.0504 | -0.0118 | 1.0000 | 23 | [n/a, n/a] | n/a |
| amihud_24 | fold_2 | BNBUSDT | trend_high_vol | -0.1979 | -0.2167 | 1.0000 | 26 | [n/a, n/a] | n/a |
| amihud_24 | fold_2 | BNBUSDT | liquidity_stress | 0.0482 | 0.0379 | 1.0000 | 102 | [-0.1238, 0.2394] | 0.6303 |
| momentum_24 | fold_0 | BTCUSDT | trend_high_vol | -0.0915 | -0.0092 | 1.0000 | 74 | [-0.3163, 0.1883] | 0.4381 |
| momentum_24 | fold_0 | BTCUSDT | range_high_vol | -0.0707 | -0.0672 | 1.0000 | 79 | [-0.2718, 0.1019] | 0.5361 |
| momentum_24 | fold_0 | BTCUSDT | range_low_vol | -0.3576 | -0.4559 | 1.0000 | 29 | [n/a, n/a] | n/a |
| momentum_24 | fold_0 | BTCUSDT | liquidity_stress | -0.0474 | -0.0458 | 1.0000 | 360 | [-0.1567, 0.0603] | 0.3702 |
| momentum_24 | fold_0 | BTCUSDT | trend_low_vol | -1.0000 | -0.9615 | 1.0000 | 5 | [n/a, n/a] | n/a |
| reversal_12 | fold_0 | BTCUSDT | trend_high_vol | 0.0101 | -0.0358 | 1.0000 | 74 | [-0.1868, 0.1892] | 0.9318 |
| reversal_12 | fold_0 | BTCUSDT | range_high_vol | 0.0726 | 0.1041 | 1.0000 | 79 | [-0.1302, 0.2957] | 0.5248 |
| reversal_12 | fold_0 | BTCUSDT | range_low_vol | 0.0759 | 0.0709 | 1.0000 | 29 | [n/a, n/a] | n/a |
| reversal_12 | fold_0 | BTCUSDT | liquidity_stress | 0.0279 | 0.0476 | 1.0000 | 360 | [-0.0824, 0.1368] | 0.5976 |
| reversal_12 | fold_0 | BTCUSDT | trend_low_vol | 0.9000 | 0.8662 | 1.0000 | 5 | [n/a, n/a] | n/a |
| realized_vol_24 | fold_0 | BTCUSDT | trend_high_vol | -0.0076 | -0.0315 | 1.0000 | 74 | [-0.2624, 0.2156] | 0.9489 |
| realized_vol_24 | fold_0 | BTCUSDT | range_high_vol | -0.1289 | -0.0621 | 1.0000 | 79 | [-0.3051, 0.0714] | 0.2575 |
| realized_vol_24 | fold_0 | BTCUSDT | range_low_vol | 0.0759 | 0.2247 | 1.0000 | 29 | [n/a, n/a] | n/a |
| realized_vol_24 | fold_0 | BTCUSDT | liquidity_stress | 0.0592 | 0.0624 | 1.0000 | 360 | [-0.0671, 0.1767] | 0.2624 |
| realized_vol_24 | fold_0 | BTCUSDT | trend_low_vol | 0.7000 | 0.9024 | 1.0000 | 5 | [n/a, n/a] | n/a |
| volume_surprise_24 | fold_0 | BTCUSDT | trend_high_vol | 0.0821 | 0.0733 | 1.0000 | 74 | [-0.0980, 0.2817] | 0.4868 |
| volume_surprise_24 | fold_0 | BTCUSDT | range_high_vol | -0.0964 | -0.0712 | 1.0000 | 79 | [-0.2997, 0.1621] | 0.3978 |
| volume_surprise_24 | fold_0 | BTCUSDT | range_low_vol | -0.2709 | -0.2698 | 1.0000 | 29 | [n/a, n/a] | n/a |
| volume_surprise_24 | fold_0 | BTCUSDT | liquidity_stress | 0.1204 | 0.0132 | 1.0000 | 360 | [0.0013, 0.2249] | 0.0224 |
| volume_surprise_24 | fold_0 | BTCUSDT | trend_low_vol | -0.5000 | -0.7587 | 1.0000 | 5 | [n/a, n/a] | n/a |
| amihud_24 | fold_0 | BTCUSDT | trend_high_vol | -0.0063 | 0.0079 | 1.0000 | 74 | [-0.1857, 0.1805] | 0.9573 |
| amihud_24 | fold_0 | BTCUSDT | range_high_vol | -0.0686 | -0.1397 | 1.0000 | 79 | [-0.2366, 0.1399] | 0.5478 |
| amihud_24 | fold_0 | BTCUSDT | range_low_vol | 0.1916 | 0.3258 | 1.0000 | 29 | [n/a, n/a] | n/a |
| amihud_24 | fold_0 | BTCUSDT | liquidity_stress | 0.0012 | 0.0204 | 1.0000 | 360 | [-0.0933, 0.0925] | 0.9812 |
| amihud_24 | fold_0 | BTCUSDT | trend_low_vol | -0.3000 | -0.1690 | 1.0000 | 5 | [n/a, n/a] | n/a |
| momentum_24 | fold_1 | BTCUSDT | trend_low_vol | 0.0564 | 0.2464 | 1.0000 | 57 | [-0.2851, 0.3547] | 0.6769 |
| momentum_24 | fold_1 | BTCUSDT | range_low_vol | 0.1347 | 0.1338 | 1.0000 | 48 | [-0.1881, 0.4226] | 0.3613 |
| momentum_24 | fold_1 | BTCUSDT | trend_high_vol | -0.1444 | 0.0050 | 1.0000 | 53 | [-0.4800, 0.1775] | 0.3021 |
| momentum_24 | fold_1 | BTCUSDT | range_high_vol | 0.0590 | 0.0805 | 1.0000 | 16 | [n/a, n/a] | n/a |
| momentum_24 | fold_1 | BTCUSDT | liquidity_stress | -0.1607 | -0.1149 | 1.0000 | 373 | [-0.2497, -0.0843] | 0.0019 |
| reversal_12 | fold_1 | BTCUSDT | trend_low_vol | -0.0378 | -0.1763 | 1.0000 | 57 | [-0.3254, 0.2294] | 0.7802 |
| reversal_12 | fold_1 | BTCUSDT | range_low_vol | -0.0747 | -0.0582 | 1.0000 | 48 | [-0.2913, 0.1733] | 0.6139 |
| reversal_12 | fold_1 | BTCUSDT | trend_high_vol | -0.0327 | -0.0356 | 1.0000 | 53 | [-0.3664, 0.3457] | 0.8165 |
| reversal_12 | fold_1 | BTCUSDT | range_high_vol | 0.3618 | 0.4186 | 1.0000 | 16 | [n/a, n/a] | n/a |
| reversal_12 | fold_1 | BTCUSDT | liquidity_stress | 0.0610 | 0.0175 | 1.0000 | 373 | [-0.0214, 0.1555] | 0.2402 |
| realized_vol_24 | fold_1 | BTCUSDT | trend_low_vol | -0.2515 | -0.2638 | 1.0000 | 57 | [-0.5387, 0.0195] | 0.0591 |
| realized_vol_24 | fold_1 | BTCUSDT | range_low_vol | 0.1521 | 0.1977 | 1.0000 | 48 | [-0.1229, 0.3433] | 0.3021 |
| realized_vol_24 | fold_1 | BTCUSDT | trend_high_vol | 0.3976 | 0.3849 | 1.0000 | 53 | [0.1953, 0.5666] | 0.0032 |
| realized_vol_24 | fold_1 | BTCUSDT | range_high_vol | -0.2456 | -0.2430 | 1.0000 | 16 | [n/a, n/a] | n/a |
| realized_vol_24 | fold_1 | BTCUSDT | liquidity_stress | -0.0553 | -0.0170 | 1.0000 | 373 | [-0.1541, 0.0450] | 0.2865 |
| volume_surprise_24 | fold_1 | BTCUSDT | trend_low_vol | 0.1289 | 0.0210 | 1.0000 | 57 | [-0.1168, 0.3592] | 0.3394 |
| volume_surprise_24 | fold_1 | BTCUSDT | range_low_vol | -0.1771 | -0.1361 | 1.0000 | 48 | [-0.4648, 0.0933] | 0.2286 |
| volume_surprise_24 | fold_1 | BTCUSDT | trend_high_vol | -0.0241 | -0.0464 | 1.0000 | 53 | [-0.3183, 0.2850] | 0.8639 |
| volume_surprise_24 | fold_1 | BTCUSDT | range_high_vol | 0.2824 | 0.0845 | 1.0000 | 16 | [n/a, n/a] | n/a |
| volume_surprise_24 | fold_1 | BTCUSDT | liquidity_stress | 0.1539 | 0.1652 | 1.0000 | 373 | [0.0622, 0.2410] | 0.0029 |
| amihud_24 | fold_1 | BTCUSDT | trend_low_vol | -0.0251 | -0.0159 | 1.0000 | 57 | [-0.3365, 0.2871] | 0.8527 |
| amihud_24 | fold_1 | BTCUSDT | range_low_vol | -0.0935 | -0.0774 | 1.0000 | 48 | [-0.3611, 0.1915] | 0.5272 |
| amihud_24 | fold_1 | BTCUSDT | trend_high_vol | 0.0539 | 0.1155 | 1.0000 | 53 | [-0.3222, 0.4378] | 0.7017 |
| amihud_24 | fold_1 | BTCUSDT | range_high_vol | 0.4147 | 0.2630 | 1.0000 | 16 | [n/a, n/a] | n/a |
| amihud_24 | fold_1 | BTCUSDT | liquidity_stress | 0.0335 | 0.0077 | 1.0000 | 373 | [-0.0606, 0.1328] | 0.5190 |
| momentum_24 | fold_2 | BTCUSDT | liquidity_stress | -0.0576 | -0.0836 | 1.0000 | 98 | [-0.2313, 0.0726] | 0.5734 |
| momentum_24 | fold_2 | BTCUSDT | range_low_vol | -0.1271 | -0.0693 | 0.9964 | 280 | [-0.2440, -0.0271] | 0.0335 |
| momentum_24 | fold_2 | BTCUSDT | trend_low_vol | 0.0258 | 0.0787 | 1.0000 | 118 | [-0.1966, 0.1964] | 0.7814 |
| momentum_24 | fold_2 | BTCUSDT | trend_high_vol | -0.2764 | -0.1959 | 1.0000 | 35 | [-0.4602, 0.0195] | 0.1080 |
| momentum_24 | fold_2 | BTCUSDT | range_high_vol | 0.4545 | 0.5305 | 1.0000 | 11 | [n/a, n/a] | n/a |
| reversal_12 | fold_2 | BTCUSDT | liquidity_stress | 0.1209 | 0.1434 | 1.0000 | 98 | [-0.0221, 0.3001] | 0.2358 |
| reversal_12 | fold_2 | BTCUSDT | range_low_vol | 0.0377 | 0.0214 | 0.9964 | 280 | [-0.0603, 0.1534] | 0.5296 |
| reversal_12 | fold_2 | BTCUSDT | trend_low_vol | -0.0779 | -0.1097 | 1.0000 | 118 | [-0.2478, 0.1406] | 0.4020 |
| reversal_12 | fold_2 | BTCUSDT | trend_high_vol | 0.3434 | 0.2549 | 1.0000 | 35 | [0.0572, 0.5522] | 0.0434 |
| reversal_12 | fold_2 | BTCUSDT | range_high_vol | -0.5818 | -0.7922 | 1.0000 | 11 | [n/a, n/a] | n/a |
| realized_vol_24 | fold_2 | BTCUSDT | liquidity_stress | 0.1039 | 0.0349 | 1.0000 | 98 | [-0.0795, 0.2528] | 0.3084 |
| realized_vol_24 | fold_2 | BTCUSDT | range_low_vol | 0.0089 | -0.0153 | 0.9964 | 280 | [-0.1066, 0.1316] | 0.8822 |
| realized_vol_24 | fold_2 | BTCUSDT | trend_low_vol | -0.0913 | -0.0828 | 1.0000 | 118 | [-0.2419, 0.1036] | 0.3252 |
| realized_vol_24 | fold_2 | BTCUSDT | trend_high_vol | 0.2258 | 0.1379 | 1.0000 | 35 | [-0.0413, 0.4004] | 0.1922 |
| realized_vol_24 | fold_2 | BTCUSDT | range_high_vol | -0.6182 | -0.7057 | 1.0000 | 11 | [n/a, n/a] | n/a |
| volume_surprise_24 | fold_2 | BTCUSDT | liquidity_stress | -0.0606 | -0.0133 | 1.0000 | 98 | [-0.2209, 0.1006] | 0.5535 |
| volume_surprise_24 | fold_2 | BTCUSDT | range_low_vol | -0.0601 | -0.0146 | 0.9964 | 280 | [-0.1555, 0.0464] | 0.3166 |
| volume_surprise_24 | fold_2 | BTCUSDT | trend_low_vol | -0.0138 | 0.0302 | 1.0000 | 118 | [-0.1738, 0.1405] | 0.8820 |
| volume_surprise_24 | fold_2 | BTCUSDT | trend_high_vol | -0.1768 | -0.0825 | 1.0000 | 35 | [-0.5114, 0.1225] | 0.3098 |
| volume_surprise_24 | fold_2 | BTCUSDT | range_high_vol | -0.3364 | -0.5080 | 1.0000 | 11 | [n/a, n/a] | n/a |
| amihud_24 | fold_2 | BTCUSDT | liquidity_stress | -0.0635 | 0.0207 | 1.0000 | 98 | [-0.2572, 0.1268] | 0.5344 |
| amihud_24 | fold_2 | BTCUSDT | range_low_vol | 0.0111 | -0.0071 | 0.9964 | 280 | [-0.0985, 0.1171] | 0.8528 |
| amihud_24 | fold_2 | BTCUSDT | trend_low_vol | 0.0035 | -0.0329 | 1.0000 | 118 | [-0.1496, 0.1846] | 0.9703 |
| amihud_24 | fold_2 | BTCUSDT | trend_high_vol | 0.2479 | 0.2352 | 1.0000 | 35 | [-0.0248, 0.4913] | 0.1510 |
| amihud_24 | fold_2 | BTCUSDT | range_high_vol | -0.3727 | -0.4579 | 1.0000 | 11 | [n/a, n/a] | n/a |
| momentum_24 | fold_0 | ETHUSDT | trend_low_vol | 1.0000 | 1.0000 | 1.0000 | 2 | [n/a, n/a] | n/a |
| momentum_24 | fold_0 | ETHUSDT | range_low_vol | 0.0130 | -0.1014 | 1.0000 | 21 | [n/a, n/a] | n/a |
| momentum_24 | fold_0 | ETHUSDT | liquidity_stress | -0.0477 | -0.0366 | 1.0000 | 523 | [-0.1323, 0.0347] | 0.2765 |
| reversal_12 | fold_0 | ETHUSDT | trend_low_vol | -1.0000 | -1.0000 | 1.0000 | 2 | [n/a, n/a] | n/a |
| reversal_12 | fold_0 | ETHUSDT | range_low_vol | 0.0143 | 0.0375 | 1.0000 | 21 | [n/a, n/a] | n/a |
| reversal_12 | fold_0 | ETHUSDT | liquidity_stress | 0.0217 | -0.0040 | 1.0000 | 523 | [-0.0647, 0.1098] | 0.6210 |
| realized_vol_24 | fold_0 | ETHUSDT | trend_low_vol | 1.0000 | 1.0000 | 1.0000 | 2 | [n/a, n/a] | n/a |
| realized_vol_24 | fold_0 | ETHUSDT | range_low_vol | 0.0714 | 0.2875 | 1.0000 | 21 | [n/a, n/a] | n/a |
| realized_vol_24 | fold_0 | ETHUSDT | liquidity_stress | 0.0354 | 0.0007 | 1.0000 | 523 | [-0.0534, 0.1163] | 0.4196 |
| volume_surprise_24 | fold_0 | ETHUSDT | trend_low_vol | 1.0000 | 1.0000 | 1.0000 | 2 | [n/a, n/a] | n/a |
| volume_surprise_24 | fold_0 | ETHUSDT | range_low_vol | 0.0468 | 0.0753 | 1.0000 | 21 | [n/a, n/a] | n/a |
| volume_surprise_24 | fold_0 | ETHUSDT | liquidity_stress | 0.0164 | -0.0337 | 1.0000 | 523 | [-0.0654, 0.0980] | 0.7084 |
| amihud_24 | fold_0 | ETHUSDT | trend_low_vol | 1.0000 | 1.0000 | 1.0000 | 2 | [n/a, n/a] | n/a |
| amihud_24 | fold_0 | ETHUSDT | range_low_vol | 0.0519 | 0.2727 | 1.0000 | 21 | [n/a, n/a] | n/a |
| amihud_24 | fold_0 | ETHUSDT | liquidity_stress | -0.0438 | 0.0289 | 1.0000 | 523 | [-0.1265, 0.0377] | 0.3175 |
| momentum_24 | fold_1 | ETHUSDT | trend_low_vol | 0.5410 | 0.4509 | 1.0000 | 26 | [n/a, n/a] | n/a |
| momentum_24 | fold_1 | ETHUSDT | range_low_vol | 0.2308 | 0.2711 | 1.0000 | 12 | [n/a, n/a] | n/a |
| momentum_24 | fold_1 | ETHUSDT | trend_high_vol | -0.1285 | -0.0213 | 1.0000 | 48 | [-0.3856, 0.0486] | 0.3840 |
| momentum_24 | fold_1 | ETHUSDT | range_high_vol | -0.4000 | -0.1577 | 1.0000 | 4 | [n/a, n/a] | n/a |
| momentum_24 | fold_1 | ETHUSDT | liquidity_stress | -0.1240 | -0.1074 | 1.0000 | 457 | [-0.2045, -0.0299] | 0.0080 |
| reversal_12 | fold_1 | ETHUSDT | trend_low_vol | -0.4452 | -0.4126 | 1.0000 | 26 | [n/a, n/a] | n/a |
| reversal_12 | fold_1 | ETHUSDT | range_low_vol | -0.3986 | -0.4829 | 1.0000 | 12 | [n/a, n/a] | n/a |
| reversal_12 | fold_1 | ETHUSDT | trend_high_vol | 0.0497 | 0.0171 | 1.0000 | 48 | [-0.2090, 0.3235] | 0.7371 |
| reversal_12 | fold_1 | ETHUSDT | range_high_vol | 0.4000 | 0.6256 | 1.0000 | 4 | [n/a, n/a] | n/a |
| reversal_12 | fold_1 | ETHUSDT | liquidity_stress | 0.0781 | 0.0577 | 1.0000 | 457 | [0.0059, 0.1612] | 0.0955 |
| realized_vol_24 | fold_1 | ETHUSDT | trend_low_vol | -0.4168 | -0.2777 | 1.0000 | 26 | [n/a, n/a] | n/a |
| realized_vol_24 | fold_1 | ETHUSDT | range_low_vol | -0.5804 | -0.3362 | 1.0000 | 12 | [n/a, n/a] | n/a |
| realized_vol_24 | fold_1 | ETHUSDT | trend_high_vol | 0.2889 | 0.1693 | 1.0000 | 48 | [-0.0048, 0.5831] | 0.0465 |
| realized_vol_24 | fold_1 | ETHUSDT | range_high_vol | 0.2000 | 0.0268 | 1.0000 | 4 | [n/a, n/a] | n/a |
| realized_vol_24 | fold_1 | ETHUSDT | liquidity_stress | -0.0598 | -0.0201 | 1.0000 | 457 | [-0.1409, 0.0239] | 0.2022 |
| volume_surprise_24 | fold_1 | ETHUSDT | trend_low_vol | 0.4322 | 0.2336 | 1.0000 | 26 | [n/a, n/a] | n/a |
| volume_surprise_24 | fold_1 | ETHUSDT | range_low_vol | 0.3776 | 0.1873 | 1.0000 | 12 | [n/a, n/a] | n/a |
| volume_surprise_24 | fold_1 | ETHUSDT | trend_high_vol | 0.0545 | 0.0919 | 1.0000 | 48 | [-0.1591, 0.2817] | 0.7130 |
| volume_surprise_24 | fold_1 | ETHUSDT | range_high_vol | 0.6000 | 0.3122 | 1.0000 | 4 | [n/a, n/a] | n/a |
| volume_surprise_24 | fold_1 | ETHUSDT | liquidity_stress | 0.1112 | 0.1246 | 1.0000 | 457 | [0.0280, 0.1902] | 0.0174 |
| amihud_24 | fold_1 | ETHUSDT | trend_low_vol | -0.4092 | -0.4121 | 1.0000 | 26 | [n/a, n/a] | n/a |
| amihud_24 | fold_1 | ETHUSDT | range_low_vol | -0.5175 | -0.6282 | 1.0000 | 12 | [n/a, n/a] | n/a |
| amihud_24 | fold_1 | ETHUSDT | trend_high_vol | 0.0025 | -0.0425 | 1.0000 | 48 | [-0.2794, 0.3738] | 0.9866 |
| amihud_24 | fold_1 | ETHUSDT | range_high_vol | -0.4000 | 0.0428 | 1.0000 | 4 | [n/a, n/a] | n/a |
| amihud_24 | fold_1 | ETHUSDT | liquidity_stress | -0.0125 | -0.0110 | 1.0000 | 457 | [-0.0575, 0.0296] | 0.7898 |
| momentum_24 | fold_2 | ETHUSDT | range_low_vol | -0.0919 | -0.0473 | 1.0000 | 139 | [-0.2883, 0.0765] | 0.2818 |
| momentum_24 | fold_2 | ETHUSDT | liquidity_stress | -0.1264 | -0.0588 | 0.9963 | 267 | [-0.2481, -0.0302] | 0.0391 |
| momentum_24 | fold_2 | ETHUSDT | trend_low_vol | -0.0406 | 0.0051 | 1.0000 | 135 | [-0.2376, 0.1659] | 0.6399 |
| reversal_12 | fold_2 | ETHUSDT | range_low_vol | -0.0178 | -0.0272 | 1.0000 | 139 | [-0.1841, 0.1509] | 0.8351 |
| reversal_12 | fold_2 | ETHUSDT | liquidity_stress | 0.1106 | 0.0425 | 0.9963 | 267 | [0.0210, 0.2201] | 0.0713 |
| reversal_12 | fold_2 | ETHUSDT | trend_low_vol | 0.0170 | -0.0505 | 1.0000 | 135 | [-0.1625, 0.2116] | 0.8452 |
| realized_vol_24 | fold_2 | ETHUSDT | range_low_vol | -0.0704 | -0.0562 | 1.0000 | 139 | [-0.2217, 0.0811] | 0.4100 |
| realized_vol_24 | fold_2 | ETHUSDT | liquidity_stress | -0.0546 | -0.0679 | 0.9963 | 267 | [-0.1459, 0.0483] | 0.3739 |
| realized_vol_24 | fold_2 | ETHUSDT | trend_low_vol | -0.0539 | -0.0517 | 1.0000 | 135 | [-0.2291, 0.1298] | 0.5345 |
| volume_surprise_24 | fold_2 | ETHUSDT | range_low_vol | -0.0794 | -0.0568 | 1.0000 | 139 | [-0.2539, 0.0809] | 0.3528 |
| volume_surprise_24 | fold_2 | ETHUSDT | liquidity_stress | -0.1159 | -0.0057 | 0.9963 | 267 | [-0.2092, -0.0286] | 0.0585 |
| volume_surprise_24 | fold_2 | ETHUSDT | trend_low_vol | -0.1129 | -0.0841 | 1.0000 | 135 | [-0.2850, 0.0663] | 0.1923 |
| amihud_24 | fold_2 | ETHUSDT | range_low_vol | 0.0277 | -0.0217 | 1.0000 | 139 | [-0.1449, 0.1843] | 0.7462 |
| amihud_24 | fold_2 | ETHUSDT | liquidity_stress | -0.0030 | 0.0135 | 0.9963 | 267 | [-0.1106, 0.1124] | 0.9607 |
| amihud_24 | fold_2 | ETHUSDT | trend_low_vol | -0.0692 | -0.0487 | 1.0000 | 135 | [-0.2030, 0.0856] | 0.4250 |
