"""Derivatives-specific data quality gates.

Coverage is computed from explicit period boundaries and expected cadence,
never from the first/last observed row.  Missing values are never forward-
filled or zero-filled.
"""

from __future__ import annotations

import math
from datetime import datetime

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from bian_quant.data.contracts import QualityFinding, QualitySeverity


class CoverageReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset: str
    source_period: str
    expected_rows: int = Field(ge=0)
    observed_rows: int = Field(ge=0)
    coverage: float
    threshold: float
    excluded_periods: tuple[str, ...] = ()
    findings: tuple[QualityFinding, ...] = ()
    asset: str | None = None
    identity_key: str | None = None

    @property
    def blocking(self) -> bool:
        return any(f.severity == QualitySeverity.BLOCKING for f in self.findings)


def inspect_coverage(
    *,
    observed: int,
    expected: int,
    threshold: float,
    dataset: str,
    source_period: str,
) -> CoverageReport:
    """Inspect raw coverage counts against a threshold.

    For metrics_oi, a below-threshold month is *excluded* rather than blocking.
    For ohlcv and funding, below-threshold is blocking.
    """
    coverage = 1.0 if expected <= 0 else observed / expected

    findings: list[QualityFinding] = []
    excluded: tuple[str, ...] = ()

    if coverage < threshold:
        if dataset == "metrics_oi":
            excluded = (source_period,)
            findings.append(
                QualityFinding(
                    code="DATA_COVERAGE_BLOCKED",
                    severity=QualitySeverity.WARNING,
                    message=(
                        f"metrics_oi coverage {coverage:.4f} below {threshold} "
                        f"for {source_period}; period excluded"
                    ),
                )
            )
        else:
            findings.append(
                QualityFinding(
                    code="DATA_COVERAGE_BLOCKED",
                    severity=QualitySeverity.BLOCKING,
                    message=(
                        f"{dataset} coverage {coverage:.4f} below {threshold} for {source_period}"
                    ),
                )
            )

    return CoverageReport(
        dataset=dataset,
        source_period=source_period,
        expected_rows=expected,
        observed_rows=observed,
        coverage=coverage,
        threshold=threshold,
        excluded_periods=excluded,
        findings=tuple(findings),
    )


def inspect_funding(
    frame: pd.DataFrame,
    *,
    period_start: datetime,
    period_end: datetime,
    threshold: float,
) -> CoverageReport:
    """Inspect funding data for coverage, duplicates, and causal timestamps."""
    source_period = period_start.strftime("%Y-%m")

    if frame.empty:
        return inspect_coverage(
            observed=0,
            expected=0,
            threshold=threshold,
            dataset="funding",
            source_period=source_period,
        )

    findings: list[QualityFinding] = []

    # Check for duplicates
    dup_count = frame.duplicated(subset=["asset", "event_time"]).sum()
    if dup_count > 0:
        findings.append(
            QualityFinding(
                code="FUNDING_DUPLICATE",
                severity=QualitySeverity.BLOCKING,
                message=f"{dup_count} duplicate funding records found",
            )
        )

    # Check available_time >= event_time
    bad_causal = (frame["available_time"] < frame["event_time"]).sum()
    if bad_causal > 0:
        findings.append(
            QualityFinding(
                code="AVAILABLE_TIME_VIOLATION",
                severity=QualitySeverity.BLOCKING,
                message=f"{bad_causal} rows with available_time < event_time",
            )
        )

    # Expected rows from archived interval
    interval_hours = int(frame["funding_interval_hours"].iloc[0])
    if interval_hours <= 0 or not frame["funding_interval_hours"].isin([1, 4, 8]).all():
        findings.append(
            QualityFinding(
                code="FUNDING_INTERVAL_INVALID",
                severity=QualitySeverity.BLOCKING,
                message="funding interval must be one of 1, 4, or 8 hours",
            )
        )
    duration = period_end - period_start
    expected = max(1, round(duration.total_seconds() / 3600 / interval_hours))

    observed = len(frame)
    coverage = observed / expected if expected > 0 else 1.0

    if coverage < threshold:
        findings.append(
            QualityFinding(
                code="DATA_COVERAGE_BLOCKED",
                severity=QualitySeverity.BLOCKING,
                message=f"funding coverage {coverage:.4f} below {threshold}",
            )
        )

    return CoverageReport(
        dataset="funding",
        source_period=source_period,
        expected_rows=expected,
        observed_rows=observed,
        coverage=coverage,
        threshold=threshold,
        findings=tuple(findings),
    )


def inspect_metrics(
    frame: pd.DataFrame,
    *,
    period_start: datetime,
    period_end: datetime,
    threshold: float,
    expected_rows: int | None = None,
) -> CoverageReport:
    """Inspect metrics/OI data for coverage, non-negative OI, and causality."""
    source_period = period_start.strftime("%Y-%m")

    findings: list[QualityFinding] = []

    if frame.empty:
        return inspect_coverage(
            observed=0,
            expected=0,
            threshold=threshold,
            dataset="metrics_oi",
            source_period=source_period,
        )

    # Check non-negative OI
    bad_oi = ((frame["sum_open_interest"] < 0) | (frame["sum_open_interest_value"] < 0)).sum()
    if bad_oi > 0:
        findings.append(
            QualityFinding(
                code="METRICS_NEGATIVE_OI",
                severity=QualitySeverity.BLOCKING,
                message=f"{bad_oi} rows with negative sum_open_interest",
            )
        )

    duplicate_count = frame.duplicated(["asset", "event_time"]).sum()
    if duplicate_count > 0:
        findings.append(
            QualityFinding(
                code="METRICS_DUPLICATE",
                severity=QualitySeverity.BLOCKING,
                message=f"{duplicate_count} duplicate metrics records found",
            )
        )

    # Check available_time >= event_time
    bad_causal = (frame["available_time"] < frame["event_time"]).sum()
    if bad_causal > 0:
        findings.append(
            QualityFinding(
                code="AVAILABLE_TIME_VIOLATION",
                severity=QualitySeverity.BLOCKING,
                message=f"{bad_causal} rows with available_time < event_time",
            )
        )

    observed = len(frame)
    # Binance USD-M metrics archives have native five-minute cadence.
    duration = period_end - period_start
    expected = (
        max(1, math.ceil(duration.total_seconds() / 300))
        if expected_rows is None
        else expected_rows
    )
    coverage = observed / expected if expected > 0 else 1.0

    excluded: tuple[str, ...] = ()
    if coverage < threshold:
        excluded = (source_period,)
        findings.append(
            QualityFinding(
                code="DATA_COVERAGE_BLOCKED",
                severity=QualitySeverity.WARNING,
                message=f"metrics_oi coverage {coverage:.4f} below {threshold}; excluded",
            )
        )

    return CoverageReport(
        dataset="metrics_oi",
        source_period=source_period,
        expected_rows=expected,
        observed_rows=observed,
        coverage=coverage,
        threshold=threshold,
        excluded_periods=excluded,
        findings=tuple(findings),
    )


def inspect_ohlcv_coverage(
    *,
    observed: int,
    expected: int,
    threshold: float,
    source_period: str,
) -> CoverageReport:
    """Shorthand for OHLCV coverage inspection."""
    return inspect_coverage(
        observed=observed,
        expected=expected,
        threshold=threshold,
        dataset="ohlcv",
        source_period=source_period,
    )
