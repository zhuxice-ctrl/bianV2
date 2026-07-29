# Price/Volume Factor Screening Results

## Overview

- **Assets**: BTCUSDT, ETHUSDT, BNBUSDT
- **Interval**: 4h
- **Factors**: momentum_24, reversal_12, realized_vol_24, volume_surprise_24, amihud_24

## Methodology

- Walk-forward splits with 6-bar purge between train and test
- Regime thresholds fit on train fold only (no full-sample quantiles)
- IC reported by fold, asset, and regime (no pooled metrics)
- Forward 1-bar log return as label

## Results

### BTCUSDT (2190 bars, 3 folds)

### ETHUSDT (2190 bars, 3 folds)

### BNBUSDT (2190 bars, 3 folds)


## Per-Factor IC Summary

| Factor | Fold | Asset | Regime | Spearman IC | Pearson IC | Coverage | N | CI Lower | CI Upper |
|--------|------|-------|--------|-------------|------------|----------|---|----------|----------|
| momentum_24 | fold_0 | BTCUSDT | range_low_vol | -0.1922 | -0.3985 | 0.50 | 24 | -0.5991 | -0.0132 |
| momentum_24 | fold_0 | BTCUSDT | trend_high_vol | -0.1437 | -0.0589 | 1.00 | 68 | -0.2708 | 0.1699 |
| momentum_24 | fold_0 | BTCUSDT | range_high_vol | -0.0597 | -0.0639 | 1.00 | 66 | -0.3016 | 0.1353 |
| momentum_24 | fold_0 | BTCUSDT | liquidity_stress | -0.0440 | -0.0438 | 1.00 | 359 | -0.1316 | 0.0457 |
| momentum_24 | fold_0 | BTCUSDT | trend_low_vol | -1.0000 | -0.9615 | 1.00 | 5 | nan | nan |
| reversal_12 | fold_0 | BTCUSDT | range_low_vol | 0.1248 | 0.1211 | 0.75 | 36 | -0.1528 | 0.4092 |
| reversal_12 | fold_0 | BTCUSDT | trend_high_vol | 0.0028 | -0.0352 | 1.00 | 68 | -0.2044 | 0.1256 |
| reversal_12 | fold_0 | BTCUSDT | range_high_vol | 0.0947 | 0.1159 | 1.00 | 66 | -0.0421 | 0.3084 |
| reversal_12 | fold_0 | BTCUSDT | liquidity_stress | 0.0231 | 0.0446 | 1.00 | 359 | -0.0589 | 0.1454 |
| reversal_12 | fold_0 | BTCUSDT | trend_low_vol | 0.9000 | 0.8662 | 1.00 | 5 | nan | nan |
| realized_vol_24 | fold_0 | BTCUSDT | range_low_vol | -0.1478 | 0.1299 | 0.50 | 24 | -0.5109 | 0.3751 |
| realized_vol_24 | fold_0 | BTCUSDT | trend_high_vol | 0.0420 | 0.0199 | 1.00 | 68 | -0.2705 | 0.3256 |
| realized_vol_24 | fold_0 | BTCUSDT | range_high_vol | -0.2096 | -0.1330 | 1.00 | 66 | -0.2984 | 0.0379 |
| realized_vol_24 | fold_0 | BTCUSDT | liquidity_stress | 0.0627 | 0.0646 | 1.00 | 359 | -0.0498 | 0.1709 |
| realized_vol_24 | fold_0 | BTCUSDT | trend_low_vol | 0.7000 | 0.9024 | 1.00 | 5 | nan | nan |
| volume_surprise_24 | fold_0 | BTCUSDT | range_low_vol | -0.1154 | 0.0290 | 0.52 | 25 | -0.2796 | 0.2470 |
| volume_surprise_24 | fold_0 | BTCUSDT | trend_high_vol | 0.0473 | 0.0523 | 1.00 | 68 | -0.1582 | 0.2529 |
| volume_surprise_24 | fold_0 | BTCUSDT | range_high_vol | -0.0698 | -0.0589 | 1.00 | 66 | -0.2320 | 0.1865 |
| volume_surprise_24 | fold_0 | BTCUSDT | liquidity_stress | 0.1158 | 0.0096 | 1.00 | 359 | -0.1003 | 0.1125 |
| volume_surprise_24 | fold_0 | BTCUSDT | trend_low_vol | -0.5000 | -0.7587 | 1.00 | 5 | nan | nan |
| amihud_24 | fold_0 | BTCUSDT | range_low_vol | -0.0617 | 0.0590 | 0.50 | 24 | -0.4513 | 0.3251 |
| amihud_24 | fold_0 | BTCUSDT | trend_high_vol | 0.0020 | 0.0070 | 1.00 | 68 | -0.1893 | 0.1871 |
| amihud_24 | fold_0 | BTCUSDT | range_high_vol | -0.0934 | -0.1622 | 1.00 | 66 | -0.3392 | 0.0688 |
| amihud_24 | fold_0 | BTCUSDT | liquidity_stress | 0.0027 | 0.0201 | 1.00 | 359 | -0.0712 | 0.1101 |
| amihud_24 | fold_0 | BTCUSDT | trend_low_vol | -0.3000 | -0.1690 | 1.00 | 5 | nan | nan |
| momentum_24 | fold_1 | BTCUSDT | range_low_vol | 0.0623 | 0.0870 | 0.72 | 62 | -0.2214 | 0.2768 |
| momentum_24 | fold_1 | BTCUSDT | trend_high_vol | -0.1688 | 0.0257 | 1.00 | 38 | -0.3305 | 0.2971 |
| momentum_24 | fold_1 | BTCUSDT | range_high_vol | 0.0590 | 0.0805 | 1.00 | 16 | -0.6032 | 0.5538 |
| momentum_24 | fold_1 | BTCUSDT | liquidity_stress | -0.1601 | -0.1148 | 1.00 | 372 | -0.2276 | -0.0066 |
| momentum_24 | fold_1 | BTCUSDT | trend_low_vol | -0.2507 | -0.2634 | 1.00 | 34 | -0.5140 | 0.0171 |
| reversal_12 | fold_1 | BTCUSDT | range_low_vol | 0.0252 | -0.0085 | 0.86 | 74 | -0.2088 | 0.1957 |
| reversal_12 | fold_1 | BTCUSDT | trend_high_vol | -0.0537 | -0.0783 | 1.00 | 38 | -0.4511 | 0.3897 |
| reversal_12 | fold_1 | BTCUSDT | range_high_vol | 0.3618 | 0.4186 | 1.00 | 16 | 0.1956 | 0.6640 |
| reversal_12 | fold_1 | BTCUSDT | liquidity_stress | 0.0606 | 0.0175 | 1.00 | 372 | -0.0699 | 0.1215 |
| reversal_12 | fold_1 | BTCUSDT | trend_low_vol | 0.2220 | 0.2316 | 1.00 | 34 | -0.0669 | 0.4828 |
| realized_vol_24 | fold_1 | BTCUSDT | range_low_vol | 0.0490 | 0.0570 | 0.72 | 62 | -0.1402 | 0.2863 |
| realized_vol_24 | fold_1 | BTCUSDT | trend_high_vol | 0.4736 | 0.4356 | 1.00 | 38 | 0.1590 | 0.6245 |
| realized_vol_24 | fold_1 | BTCUSDT | range_high_vol | -0.2456 | -0.2430 | 1.00 | 16 | -0.6298 | 0.1578 |
| realized_vol_24 | fold_1 | BTCUSDT | liquidity_stress | -0.0536 | -0.0160 | 1.00 | 372 | -0.1399 | 0.1006 |
| realized_vol_24 | fold_1 | BTCUSDT | trend_low_vol | -0.0839 | -0.0561 | 1.00 | 34 | -0.3305 | 0.2801 |
| volume_surprise_24 | fold_1 | BTCUSDT | range_low_vol | -0.0174 | -0.0104 | 0.73 | 63 | -0.2385 | 0.2064 |
| volume_surprise_24 | fold_1 | BTCUSDT | trend_high_vol | -0.1012 | -0.1231 | 1.00 | 38 | -0.4347 | 0.2662 |
| volume_surprise_24 | fold_1 | BTCUSDT | range_high_vol | 0.2824 | 0.0845 | 1.00 | 16 | -0.2923 | 0.4735 |
| volume_surprise_24 | fold_1 | BTCUSDT | liquidity_stress | 0.1523 | 0.1646 | 1.00 | 372 | 0.0697 | 0.2598 |
| volume_surprise_24 | fold_1 | BTCUSDT | trend_low_vol | 0.0017 | 0.0785 | 1.00 | 34 | -0.1431 | 0.3274 |
| amihud_24 | fold_1 | BTCUSDT | range_low_vol | -0.0937 | -0.1065 | 0.72 | 62 | -0.3722 | 0.0989 |
| amihud_24 | fold_1 | BTCUSDT | trend_high_vol | 0.0877 | 0.1336 | 1.00 | 38 | -0.1063 | 0.4117 |
| amihud_24 | fold_1 | BTCUSDT | range_high_vol | 0.4147 | 0.2630 | 1.00 | 16 | -0.0614 | 0.6922 |
| amihud_24 | fold_1 | BTCUSDT | liquidity_stress | 0.0323 | 0.0073 | 1.00 | 372 | -0.0807 | 0.1021 |
| amihud_24 | fold_1 | BTCUSDT | trend_low_vol | -0.3222 | -0.2923 | 1.00 | 34 | -0.5089 | -0.0710 |
| momentum_24 | fold_2 | BTCUSDT | range_low_vol | -0.1111 | -0.0568 | 0.91 | 259 | -0.1724 | 0.0485 |
| momentum_24 | fold_2 | BTCUSDT | trend_low_vol | 0.0270 | 0.0800 | 1.00 | 117 | -0.1504 | 0.2190 |
| momentum_24 | fold_2 | BTCUSDT | trend_high_vol | -0.2764 | -0.1959 | 1.00 | 35 | -0.4116 | 0.0134 |
| momentum_24 | fold_2 | BTCUSDT | range_high_vol | 0.4545 | 0.5305 | 1.00 | 11 | -0.4536 | 0.9642 |
| momentum_24 | fold_2 | BTCUSDT | liquidity_stress | -0.0593 | -0.0864 | 1.00 | 96 | -0.2420 | 0.0615 |
| reversal_12 | fold_2 | BTCUSDT | range_low_vol | 0.0270 | 0.0141 | 0.95 | 271 | -0.0833 | 0.1182 |
| reversal_12 | fold_2 | BTCUSDT | trend_low_vol | -0.0807 | -0.1123 | 1.00 | 117 | -0.2480 | 0.0968 |
| reversal_12 | fold_2 | BTCUSDT | trend_high_vol | 0.3434 | 0.2549 | 1.00 | 35 | 0.0669 | 0.4635 |
| reversal_12 | fold_2 | BTCUSDT | range_high_vol | -0.5818 | -0.7922 | 1.00 | 11 | -0.9643 | -0.1181 |
| reversal_12 | fold_2 | BTCUSDT | liquidity_stress | 0.1208 | 0.1478 | 1.00 | 96 | -0.0087 | 0.3215 |
| realized_vol_24 | fold_2 | BTCUSDT | range_low_vol | 0.0025 | -0.0207 | 0.91 | 259 | -0.1429 | 0.1041 |
| realized_vol_24 | fold_2 | BTCUSDT | trend_low_vol | -0.0903 | -0.0845 | 1.00 | 117 | -0.2709 | 0.1130 |
| realized_vol_24 | fold_2 | BTCUSDT | trend_high_vol | 0.2258 | 0.1379 | 1.00 | 35 | -0.0733 | 0.2819 |
| realized_vol_24 | fold_2 | BTCUSDT | range_high_vol | -0.6182 | -0.7057 | 1.00 | 11 | -0.9135 | -0.0865 |
| realized_vol_24 | fold_2 | BTCUSDT | liquidity_stress | 0.0867 | 0.0146 | 1.00 | 96 | -0.1737 | 0.2161 |
| volume_surprise_24 | fold_2 | BTCUSDT | range_low_vol | -0.0457 | 0.0067 | 0.92 | 260 | -0.0910 | 0.0989 |
| volume_surprise_24 | fold_2 | BTCUSDT | trend_low_vol | -0.0209 | 0.0268 | 1.00 | 117 | -0.1110 | 0.1461 |
| volume_surprise_24 | fold_2 | BTCUSDT | trend_high_vol | -0.1768 | -0.0825 | 1.00 | 35 | -0.3842 | 0.1838 |
| volume_surprise_24 | fold_2 | BTCUSDT | range_high_vol | -0.3364 | -0.5080 | 1.00 | 11 | -0.8594 | 0.3838 |
| volume_surprise_24 | fold_2 | BTCUSDT | liquidity_stress | -0.0628 | -0.0185 | 1.00 | 96 | -0.1508 | 0.1350 |
| amihud_24 | fold_2 | BTCUSDT | range_low_vol | -0.0012 | -0.0058 | 0.91 | 259 | -0.1071 | 0.1059 |
| amihud_24 | fold_2 | BTCUSDT | trend_low_vol | 0.0154 | -0.0259 | 1.00 | 117 | -0.1680 | 0.1477 |
| amihud_24 | fold_2 | BTCUSDT | trend_high_vol | 0.2479 | 0.2352 | 1.00 | 35 | 0.0549 | 0.4462 |
| amihud_24 | fold_2 | BTCUSDT | range_high_vol | -0.3727 | -0.4579 | 1.00 | 11 | -0.7757 | 0.6065 |
| amihud_24 | fold_2 | BTCUSDT | liquidity_stress | -0.0877 | -0.0032 | 1.00 | 96 | -0.2041 | 0.1531 |
| momentum_24 | fold_0 | ETHUSDT | range_low_vol | -0.1922 | -0.3780 | 0.50 | 24 | -0.5888 | 0.0425 |
| momentum_24 | fold_0 | ETHUSDT | liquidity_stress | -0.0402 | -0.0319 | 1.00 | 497 | -0.1049 | 0.0404 |
| reversal_12 | fold_0 | ETHUSDT | range_low_vol | 0.1282 | 0.1383 | 0.75 | 36 | -0.1156 | 0.4344 |
| reversal_12 | fold_0 | ETHUSDT | liquidity_stress | 0.0080 | -0.0121 | 1.00 | 497 | -0.0959 | 0.0724 |
| realized_vol_24 | fold_0 | ETHUSDT | range_low_vol | -0.1043 | -0.1030 | 0.50 | 24 | -0.4240 | 0.1815 |
| realized_vol_24 | fold_0 | ETHUSDT | liquidity_stress | 0.0389 | 0.0035 | 1.00 | 497 | -0.0763 | 0.0781 |
| volume_surprise_24 | fold_0 | ETHUSDT | range_low_vol | -0.1923 | -0.0280 | 0.52 | 25 | -0.3149 | 0.1974 |
| volume_surprise_24 | fold_0 | ETHUSDT | liquidity_stress | 0.0219 | -0.0376 | 1.00 | 497 | -0.1311 | 0.0490 |
| amihud_24 | fold_0 | ETHUSDT | range_low_vol | -0.3301 | -0.3361 | 0.50 | 24 | -0.5438 | -0.0851 |
| amihud_24 | fold_0 | ETHUSDT | liquidity_stress | -0.0204 | 0.0443 | 1.00 | 497 | -0.0474 | 0.1401 |
| momentum_24 | fold_1 | ETHUSDT | range_low_vol | -0.1228 | -0.0743 | 0.50 | 24 | -0.4019 | 0.1782 |
| momentum_24 | fold_1 | ETHUSDT | trend_high_vol | -0.1317 | 0.0007 | 1.00 | 38 | -0.3041 | 0.2229 |
| momentum_24 | fold_1 | ETHUSDT | range_high_vol | -0.4000 | -0.1577 | 1.00 | 4 | nan | nan |
| momentum_24 | fold_1 | ETHUSDT | liquidity_stress | -0.1236 | -0.1073 | 1.00 | 456 | -0.2024 | -0.0141 |
| reversal_12 | fold_1 | ETHUSDT | range_low_vol | -0.0088 | 0.0098 | 0.75 | 36 | -0.2386 | 0.3012 |
| reversal_12 | fold_1 | ETHUSDT | trend_high_vol | 0.0330 | -0.0250 | 1.00 | 38 | -0.2989 | 0.3368 |
| reversal_12 | fold_1 | ETHUSDT | range_high_vol | 0.4000 | 0.6256 | 1.00 | 4 | nan | nan |
| reversal_12 | fold_1 | ETHUSDT | liquidity_stress | 0.0782 | 0.0577 | 1.00 | 456 | -0.0068 | 0.1350 |
| realized_vol_24 | fold_1 | ETHUSDT | range_low_vol | 0.1261 | 0.2454 | 0.50 | 24 | -0.0735 | 0.5153 |
| realized_vol_24 | fold_1 | ETHUSDT | trend_high_vol | 0.4387 | 0.3004 | 1.00 | 38 | 0.1126 | 0.5899 |
| realized_vol_24 | fold_1 | ETHUSDT | range_high_vol | 0.2000 | 0.0268 | 1.00 | 4 | nan | nan |
| realized_vol_24 | fold_1 | ETHUSDT | liquidity_stress | -0.0591 | -0.0198 | 1.00 | 456 | -0.1078 | 0.0763 |
| volume_surprise_24 | fold_1 | ETHUSDT | range_low_vol | 0.0946 | 0.0978 | 0.52 | 25 | -0.1891 | 0.3837 |
| volume_surprise_24 | fold_1 | ETHUSDT | trend_high_vol | 0.0739 | 0.1051 | 1.00 | 38 | -0.1306 | 0.3323 |
| volume_surprise_24 | fold_1 | ETHUSDT | range_high_vol | 0.6000 | 0.3122 | 1.00 | 4 | nan | nan |
| volume_surprise_24 | fold_1 | ETHUSDT | liquidity_stress | 0.1103 | 0.1246 | 1.00 | 456 | 0.0484 | 0.1988 |
| amihud_24 | fold_1 | ETHUSDT | range_low_vol | -0.1826 | -0.2724 | 0.50 | 24 | -0.5463 | 0.1053 |
| amihud_24 | fold_1 | ETHUSDT | trend_high_vol | -0.0167 | -0.0335 | 1.00 | 38 | -0.1965 | 0.2093 |
| amihud_24 | fold_1 | ETHUSDT | range_high_vol | -0.4000 | 0.0428 | 1.00 | 4 | nan | nan |
| amihud_24 | fold_1 | ETHUSDT | liquidity_stress | -0.0128 | -0.0110 | 1.00 | 456 | -0.0363 | 0.0185 |
| momentum_24 | fold_2 | ETHUSDT | range_low_vol | -0.0570 | -0.0078 | 0.86 | 144 | -0.1941 | 0.1437 |
| momentum_24 | fold_2 | ETHUSDT | trend_low_vol | -0.0393 | 0.0040 | 1.00 | 130 | -0.2557 | 0.2482 |
| momentum_24 | fold_2 | ETHUSDT | liquidity_stress | -0.1146 | -0.0563 | 1.00 | 243 | -0.1680 | 0.0352 |
| reversal_12 | fold_2 | ETHUSDT | range_low_vol | -0.0256 | -0.0499 | 0.93 | 156 | -0.2246 | 0.1183 |
| reversal_12 | fold_2 | ETHUSDT | trend_low_vol | 0.0183 | -0.0482 | 1.00 | 130 | -0.2017 | 0.1562 |
| reversal_12 | fold_2 | ETHUSDT | liquidity_stress | 0.0956 | 0.0355 | 1.00 | 243 | -0.0580 | 0.1564 |
| realized_vol_24 | fold_2 | ETHUSDT | range_low_vol | -0.0868 | -0.1034 | 0.86 | 144 | -0.2355 | 0.0273 |
| realized_vol_24 | fold_2 | ETHUSDT | trend_low_vol | -0.0516 | -0.0554 | 1.00 | 130 | -0.2747 | 0.1520 |
| realized_vol_24 | fold_2 | ETHUSDT | liquidity_stress | -0.0490 | -0.0640 | 1.00 | 243 | -0.1713 | 0.0606 |
| volume_surprise_24 | fold_2 | ETHUSDT | range_low_vol | -0.1503 | -0.0794 | 0.86 | 145 | -0.2627 | 0.0725 |
| volume_surprise_24 | fold_2 | ETHUSDT | trend_low_vol | -0.0969 | -0.0731 | 1.00 | 130 | -0.2192 | 0.0725 |
| volume_surprise_24 | fold_2 | ETHUSDT | liquidity_stress | -0.1052 | -0.0003 | 1.00 | 243 | -0.1059 | 0.0871 |
| amihud_24 | fold_2 | ETHUSDT | range_low_vol | 0.0350 | -0.0007 | 0.86 | 144 | -0.1554 | 0.1513 |
| amihud_24 | fold_2 | ETHUSDT | trend_low_vol | -0.0860 | -0.0727 | 1.00 | 130 | -0.1838 | 0.0625 |
| amihud_24 | fold_2 | ETHUSDT | liquidity_stress | 0.0173 | 0.0370 | 1.00 | 243 | -0.0481 | 0.1297 |
| momentum_24 | fold_0 | BNBUSDT | range_low_vol | 0.0622 | 0.1630 | 0.78 | 84 | -0.1585 | 0.3237 |
| momentum_24 | fold_0 | BNBUSDT | trend_low_vol | -0.1188 | 0.0739 | 1.00 | 44 | -0.2902 | 0.3927 |
| momentum_24 | fold_0 | BNBUSDT | trend_high_vol | -0.1676 | -0.0098 | 1.00 | 41 | -0.2805 | 0.2173 |
| momentum_24 | fold_0 | BNBUSDT | range_high_vol | -0.0437 | -0.0564 | 1.00 | 77 | -0.2560 | 0.1987 |
| momentum_24 | fold_0 | BNBUSDT | liquidity_stress | -0.0998 | -0.0993 | 1.00 | 276 | -0.2108 | 0.0081 |
| reversal_12 | fold_0 | BNBUSDT | range_low_vol | 0.0610 | -0.0181 | 0.89 | 96 | -0.1915 | 0.2001 |
| reversal_12 | fold_0 | BNBUSDT | trend_low_vol | 0.0264 | -0.3696 | 1.00 | 44 | -0.6463 | 0.3278 |
| reversal_12 | fold_0 | BNBUSDT | trend_high_vol | 0.0371 | -0.0500 | 1.00 | 41 | -0.3166 | 0.2605 |
| reversal_12 | fold_0 | BNBUSDT | range_high_vol | 0.0791 | 0.0667 | 1.00 | 77 | -0.1950 | 0.3085 |
| reversal_12 | fold_0 | BNBUSDT | liquidity_stress | 0.0956 | 0.0513 | 1.00 | 276 | -0.0458 | 0.1644 |
| realized_vol_24 | fold_0 | BNBUSDT | range_low_vol | -0.0643 | -0.0846 | 0.78 | 84 | -0.1926 | 0.0868 |
| realized_vol_24 | fold_0 | BNBUSDT | trend_low_vol | -0.0163 | -0.0501 | 1.00 | 44 | -0.3332 | 0.2717 |
| realized_vol_24 | fold_0 | BNBUSDT | trend_high_vol | 0.0047 | 0.0432 | 1.00 | 41 | -0.1730 | 0.2473 |
| realized_vol_24 | fold_0 | BNBUSDT | range_high_vol | 0.0738 | 0.0811 | 1.00 | 77 | -0.1126 | 0.2131 |
| realized_vol_24 | fold_0 | BNBUSDT | liquidity_stress | 0.0557 | 0.0940 | 1.00 | 276 | -0.0646 | 0.2358 |
| volume_surprise_24 | fold_0 | BNBUSDT | range_low_vol | 0.0319 | -0.0541 | 0.79 | 85 | -0.1856 | 0.0988 |
| volume_surprise_24 | fold_0 | BNBUSDT | trend_low_vol | -0.0541 | -0.0849 | 1.00 | 44 | -0.2794 | 0.0885 |
| volume_surprise_24 | fold_0 | BNBUSDT | trend_high_vol | 0.2394 | 0.1017 | 1.00 | 41 | -0.1056 | 0.3886 |
| volume_surprise_24 | fold_0 | BNBUSDT | range_high_vol | 0.0183 | 0.0288 | 1.00 | 77 | -0.1701 | 0.2088 |
| volume_surprise_24 | fold_0 | BNBUSDT | liquidity_stress | -0.0196 | -0.0439 | 1.00 | 276 | -0.1662 | 0.0724 |
| amihud_24 | fold_0 | BNBUSDT | range_low_vol | 0.1206 | 0.1430 | 0.78 | 84 | -0.0358 | 0.3198 |
| amihud_24 | fold_0 | BNBUSDT | trend_low_vol | 0.0544 | 0.5426 | 1.00 | 44 | -0.0744 | 0.7913 |
| amihud_24 | fold_0 | BNBUSDT | trend_high_vol | -0.0023 | -0.0358 | 1.00 | 41 | -0.2231 | 0.1733 |
| amihud_24 | fold_0 | BNBUSDT | range_high_vol | 0.0099 | 0.0261 | 1.00 | 77 | -0.1019 | 0.1747 |
| amihud_24 | fold_0 | BNBUSDT | liquidity_stress | -0.0593 | -0.0581 | 1.00 | 276 | -0.1711 | 0.0625 |
| momentum_24 | fold_1 | BNBUSDT | range_low_vol | -0.1920 | -0.1604 | 0.50 | 24 | -0.5513 | 0.1879 |
| momentum_24 | fold_1 | BNBUSDT | trend_high_vol | 0.3143 | 0.2111 | 1.00 | 6 | nan | nan |
| momentum_24 | fold_1 | BNBUSDT | liquidity_stress | -0.0801 | -0.0031 | 1.00 | 492 | -0.1524 | 0.1520 |
| reversal_12 | fold_1 | BNBUSDT | range_low_vol | 0.1642 | 0.0918 | 0.75 | 36 | -0.1525 | 0.3700 |
| reversal_12 | fold_1 | BNBUSDT | trend_high_vol | 0.0857 | -0.4550 | 1.00 | 6 | nan | nan |
| reversal_12 | fold_1 | BNBUSDT | liquidity_stress | 0.0517 | -0.0112 | 1.00 | 492 | -0.1471 | 0.1438 |
| realized_vol_24 | fold_1 | BNBUSDT | range_low_vol | 0.2130 | 0.2687 | 0.50 | 24 | -0.0605 | 0.6483 |
| realized_vol_24 | fold_1 | BNBUSDT | trend_high_vol | -0.6571 | -0.6633 | 1.00 | 6 | nan | nan |
| realized_vol_24 | fold_1 | BNBUSDT | liquidity_stress | -0.0256 | -0.0255 | 1.00 | 492 | -0.1548 | 0.1002 |
| volume_surprise_24 | fold_1 | BNBUSDT | range_low_vol | 0.2446 | 0.0662 | 0.52 | 25 | -0.1540 | 0.4487 |
| volume_surprise_24 | fold_1 | BNBUSDT | trend_high_vol | 0.8857 | 0.7446 | 1.00 | 6 | nan | nan |
| volume_surprise_24 | fold_1 | BNBUSDT | liquidity_stress | 0.0275 | 0.0303 | 1.00 | 492 | -0.0959 | 0.1462 |
| amihud_24 | fold_1 | BNBUSDT | range_low_vol | 0.1565 | 0.0313 | 0.50 | 24 | -0.1798 | 0.2562 |
| amihud_24 | fold_1 | BNBUSDT | trend_high_vol | 0.3714 | 0.5801 | 1.00 | 6 | nan | nan |
| amihud_24 | fold_1 | BNBUSDT | liquidity_stress | 0.0201 | 0.0424 | 1.00 | 492 | -0.0386 | 0.1837 |
| momentum_24 | fold_2 | BNBUSDT | range_low_vol | -0.0283 | -0.0237 | 0.91 | 262 | -0.1913 | 0.1491 |
| momentum_24 | fold_2 | BNBUSDT | trend_low_vol | -0.2776 | -0.2092 | 1.00 | 105 | -0.3998 | -0.0342 |
| momentum_24 | fold_2 | BNBUSDT | range_high_vol | 0.0835 | 0.1465 | 1.00 | 23 | -0.2898 | 0.4964 |
| momentum_24 | fold_2 | BNBUSDT | trend_high_vol | -0.1976 | -0.1319 | 1.00 | 26 | -0.3392 | 0.1530 |
| momentum_24 | fold_2 | BNBUSDT | liquidity_stress | -0.0118 | -0.0145 | 1.00 | 102 | -0.1829 | 0.1465 |
| reversal_12 | fold_2 | BNBUSDT | range_low_vol | -0.0726 | -0.1253 | 0.95 | 274 | -0.2351 | 0.0215 |
| reversal_12 | fold_2 | BNBUSDT | trend_low_vol | 0.2297 | 0.1085 | 1.00 | 105 | -0.1224 | 0.3833 |
| reversal_12 | fold_2 | BNBUSDT | range_high_vol | -0.0682 | -0.2651 | 1.00 | 23 | -0.6400 | 0.3702 |
| reversal_12 | fold_2 | BNBUSDT | trend_high_vol | 0.2287 | 0.1652 | 1.00 | 26 | -0.0784 | 0.3877 |
| reversal_12 | fold_2 | BNBUSDT | liquidity_stress | 0.0833 | 0.1156 | 1.00 | 102 | -0.0163 | 0.2716 |
| realized_vol_24 | fold_2 | BNBUSDT | range_low_vol | 0.0173 | -0.0259 | 0.91 | 262 | -0.1467 | 0.1026 |
| realized_vol_24 | fold_2 | BNBUSDT | trend_low_vol | -0.0601 | -0.0617 | 1.00 | 105 | -0.2474 | 0.1505 |
| realized_vol_24 | fold_2 | BNBUSDT | range_high_vol | 0.0247 | 0.1084 | 1.00 | 23 | -0.1640 | 0.4427 |
| realized_vol_24 | fold_2 | BNBUSDT | trend_high_vol | -0.0831 | -0.0367 | 1.00 | 26 | -0.5243 | 0.2522 |
| realized_vol_24 | fold_2 | BNBUSDT | liquidity_stress | 0.0294 | -0.0442 | 1.00 | 102 | -0.1723 | 0.0908 |
| volume_surprise_24 | fold_2 | BNBUSDT | range_low_vol | -0.0048 | -0.0197 | 0.92 | 263 | -0.1542 | 0.1025 |
| volume_surprise_24 | fold_2 | BNBUSDT | trend_low_vol | 0.0244 | 0.0954 | 1.00 | 105 | -0.1333 | 0.2670 |
| volume_surprise_24 | fold_2 | BNBUSDT | range_high_vol | 0.1512 | 0.0362 | 1.00 | 23 | -0.4022 | 0.5625 |
| volume_surprise_24 | fold_2 | BNBUSDT | trend_high_vol | 0.0591 | -0.0068 | 1.00 | 26 | -0.2921 | 0.2170 |
| volume_surprise_24 | fold_2 | BNBUSDT | liquidity_stress | 0.0213 | 0.0059 | 1.00 | 102 | -0.1432 | 0.1803 |
| amihud_24 | fold_2 | BNBUSDT | range_low_vol | -0.0717 | -0.0336 | 0.91 | 262 | -0.1717 | 0.1091 |
| amihud_24 | fold_2 | BNBUSDT | trend_low_vol | 0.0596 | 0.0284 | 1.00 | 105 | -0.1322 | 0.1824 |
| amihud_24 | fold_2 | BNBUSDT | range_high_vol | 0.0504 | -0.0118 | 1.00 | 23 | -0.3040 | 0.3715 |
| amihud_24 | fold_2 | BNBUSDT | trend_high_vol | -0.1979 | -0.2167 | 1.00 | 26 | -0.4699 | 0.1403 |
| amihud_24 | fold_2 | BNBUSDT | liquidity_stress | 0.0482 | 0.0379 | 1.00 | 102 | -0.1283 | 0.2053 |

## Aggregate Statistics

| Factor | Mean IC | Median IC | Std IC | N Groups |
|--------|---------|-----------|--------|----------|
| amihud_24 | -0.0261 | -0.0012 | 0.1746 | 37 |
| momentum_24 | -0.1038 | -0.1111 | 0.2129 | 37 |
| realized_vol_24 | 0.0043 | 0.0025 | 0.2375 | 37 |
| reversal_12 | 0.0897 | 0.0610 | 0.2065 | 37 |
| volume_surprise_24 | 0.0306 | 0.0183 | 0.2275 | 37 |