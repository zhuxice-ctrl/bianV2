from pydantic import BaseModel
import pandas as pd

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
    times = pd.to_datetime(frame["event_time"], utc=True).sort_values()
    expected = pd.Timedelta(expected_frequency)
    if len(times) > 1 and (times.diff().dropna() > expected).any():
        findings.append(
            QualityFinding(
                code="TIME_GAP",
                severity=QualitySeverity.WARNING,
                message="one or more bars are missing",
            )
        )
    return QualityReport(findings=findings)
