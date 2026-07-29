"""Protocol and shared types for factor functions."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class FactorFunction(Protocol):
    """A pure function over a point-in-time DataFrame returning a named Series."""

    def __call__(self, frame: pd.DataFrame, **kwargs: object) -> pd.Series: ...
