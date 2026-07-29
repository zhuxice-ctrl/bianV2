import pandas as pd
from pydantic import BaseModel

from bian_quant.data.contracts import QualityFinding, QualitySeverity


class QualityReport(BaseModel):
    findings: list[QualityFinding]

    @property
    def blocking(self) -> bool:
        return any(item.severity == QualitySeverity.BLOCKING for item in self.findings)


def inspect_ohlcv(frame: pd.DataFrame, *, expected_frequency: str) -> QualityReport:
    findings: list[QualityFinding] = []
    invalid = ~(
        (frame["high"] >= frame[["open", "close", "low"]].max(axis=1))
        & (frame["low"] <= frame[["open", "close", "high"]].min(axis=1))
    )
    if invalid.any():
        findings.append(
            QualityFinding(
                code="OHLC_RELATION",
                severity=QualitySeverity.BLOCKING,
                message="OHLC ordering is impossible",
                rows=frame.index[invalid].tolist(),
            )
        )
    if (frame["volume"] < 0).any():
        findings.append(
            QualityFinding(
                code="NEGATIVE_VOLUME",
                severity=QualitySeverity.BLOCKING,
                message="volume must be non-negative",
            )
        )
    expected = pd.Timedelta(expected_frequency)
    groups = frame.groupby("asset", sort=False) if "asset" in frame.columns else [(None, frame)]
    for asset, group in groups:
        times = pd.to_datetime(group["event_time"], utc=True).sort_values()
        label = f" for asset={asset!r}" if asset is not None else ""
        if times.duplicated().any():
            findings.append(
                QualityFinding(
                    code="DUPLICATE_BAR",
                    severity=QualitySeverity.BLOCKING,
                    message=f"duplicate event_time{label}",
                )
            )
        if len(times) > 1 and (times.diff().dropna() > expected).any():
            findings.append(
                QualityFinding(
                    code="TIME_GAP",
                    severity=QualitySeverity.WARNING,
                    message=f"one or more bars are missing{label}",
                )
            )
    return QualityReport(findings=findings)
