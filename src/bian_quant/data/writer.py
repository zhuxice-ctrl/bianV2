from pathlib import Path

import pandas as pd

from bian_quant.data.contracts import QualitySeverity
from bian_quant.data.quality import QualityReport, inspect_ohlcv


class DataQualityError(ValueError):
    def __init__(self, report: QualityReport) -> None:
        codes = sorted(
            finding.code
            for finding in report.findings
            if finding.severity == QualitySeverity.BLOCKING
        )
        super().__init__(f"blocking data-quality findings prevent publication: {codes}")
        self.report = report


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, engine="pyarrow", index=False, compression="zstd")


def write_canonical_ohlcv(
    frame: pd.DataFrame, path: Path, *, expected_frequency: str
) -> QualityReport:
    report = inspect_ohlcv(frame, expected_frequency=expected_frequency)
    if report.blocking:
        raise DataQualityError(report)
    write_parquet(frame, path)
    return report
