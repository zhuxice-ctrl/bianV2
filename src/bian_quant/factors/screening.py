"""Built-in price/volume screening inputs and point-in-time legacy loader."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from pathlib import Path

import pandas as pd

from bian_quant.factors.price import momentum, realized_volatility, reversal
from bian_quant.factors.spec import FactorSpec
from bian_quant.factors.volume import amihud_illiquidity, volume_surprise
from bian_quant.regimes.classifier import REGIME_LABELS

FactorCallable = Callable[[pd.DataFrame], pd.Series]


def _momentum_24(frame: pd.DataFrame) -> pd.Series:
    return momentum(frame["close"], periods=24)


def _reversal_12(frame: pd.DataFrame) -> pd.Series:
    return reversal(frame["close"], periods=12)


def _realized_vol_24(frame: pd.DataFrame) -> pd.Series:
    return realized_volatility(frame["close"], periods=24)


def _volume_surprise_24(frame: pd.DataFrame) -> pd.Series:
    return volume_surprise(frame["volume"], periods=24)


def _amihud_24(frame: pd.DataFrame) -> pd.Series:
    return amihud_illiquidity(frame["close"], frame["volume"], periods=24)


BUILTIN_FACTOR_FUNCTIONS: dict[str, FactorCallable] = {
    "momentum_24": _momentum_24,
    "reversal_12": _reversal_12,
    "realized_vol_24": _realized_vol_24,
    "volume_surprise_24": _volume_surprise_24,
    "amihud_24": _amihud_24,
}


def builtin_factor_specs(*, horizon: str) -> list[FactorSpec]:
    """Return immutable specifications for the initial interpretable library."""
    regimes = list(REGIME_LABELS)

    def build(
        *,
        factor_id: str,
        formula: str,
        direction: str,
        hypothesis: str,
        required_columns: list[str],
    ) -> FactorSpec:
        return FactorSpec.model_validate(
            {
                "factor_id": factor_id,
                "version": "1.0.0",
                "formula": formula,
                "direction": direction,
                "hypothesis": hypothesis,
                "required_columns": required_columns,
                "horizon": horizon,
                "missing_policy": "preserve",
                "winsor_limits": (0.01, 0.99),
                "valid_regimes": regimes,
                "failure_conditions": [
                    "walk-forward RankIC is unstable after multiple-testing correction"
                ],
                "parent_factors": [],
            }
        )

    return [
        build(
            factor_id="momentum_24",
            formula="close / close.shift(24) - 1",
            direction="positive",
            hypothesis="persistent medium-horizon price movement may continue into the next bar",
            required_columns=["close"],
        ),
        build(
            factor_id="reversal_12",
            formula="-(close / close.shift(12) - 1)",
            direction="positive",
            hypothesis="short-horizon price dislocations may mean-revert during the next bar",
            required_columns=["close"],
        ),
        build(
            factor_id="realized_vol_24",
            formula="std(log_return, 24)",
            direction="two_sided",
            hypothesis="recent realized volatility may condition the magnitude of the next return",
            required_columns=["close"],
        ),
        build(
            factor_id="volume_surprise_24",
            formula="zscore(volume, 24)",
            direction="two_sided",
            hypothesis="unusual trading activity may reveal short-lived information flow",
            required_columns=["volume"],
        ),
        build(
            factor_id="amihud_24",
            formula="mean(abs(log_return) / dollar_volume, 24)",
            direction="two_sided",
            hypothesis="recent price impact may identify liquidity-dependent return behavior",
            required_columns=["close", "volume"],
        ),
    ]


def load_legacy_screening_data(
    data_dir: Path,
    *,
    assets: Sequence[str],
    interval: str,
) -> tuple[pd.DataFrame, str]:
    """Load legacy OHLCV with bar-close availability and a content snapshot ID."""
    frames: list[pd.DataFrame] = []
    digest = hashlib.sha256()
    for asset in assets:
        path = data_dir / f"{asset}_{interval}.csv"
        if not path.is_file():
            raise FileNotFoundError(path)
        payload = path.read_bytes()
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(payload)

        source = pd.read_csv(path)
        required = {"open_time", "close_time", "close", "volume"}
        missing = required - set(source.columns)
        if missing:
            raise ValueError(f"{path.name} missing columns: {sorted(missing)}")
        event_time = pd.to_datetime(source["open_time"], unit="ms", utc=True)
        available_time = pd.to_datetime(source["close_time"], unit="ms", utc=True)
        if (available_time < event_time).any():
            raise ValueError(f"{path.name} has availability before event time")
        frames.append(
            pd.DataFrame(
                {
                    "event_time": event_time,
                    # timestamp is the decision time used by the factor runner.
                    "timestamp": available_time,
                    "available_time": available_time,
                    "asset": asset,
                    "close": pd.to_numeric(source["close"], errors="raise"),
                    "volume": pd.to_numeric(source["volume"], errors="raise"),
                }
            )
        )

    snapshot_id = f"legacy-ohlcv-{interval}-{digest.hexdigest()}"
    combined = pd.concat(frames, ignore_index=True)
    return combined.sort_values(["asset", "available_time"]).reset_index(drop=True), snapshot_id
