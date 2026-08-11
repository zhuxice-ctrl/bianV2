"""Stable acquisition-failure classification, including temporary cutoff-month Funding gaps."""

from __future__ import annotations

from urllib.error import HTTPError

from pydantic import BaseModel, ConfigDict

from bian_quant.data.acquisition import (
    DualHorizonAcquisition,
    SourceDataset,
    SourceGranularity,
    SourceObject,
)


class AcquisitionFailureEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    identity_key: str
    error_code: str
    message: str
    http_status: int | None
    attempt_count: int
    temporary: bool


def is_funding_tail_period(source: SourceObject, config: DualHorizonAcquisition) -> bool:
    """Return True for monthly Funding sources in the two-month tail window.

    The tail covers the cutoff month and the immediately preceding month,
    matching periods whose ``period_start`` falls on the first day of either.
    """
    if source.dataset != SourceDataset.FUNDING or source.granularity != SourceGranularity.MONTHLY:
        return False
    cutoff = config.as_of.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    previous = (
        cutoff.replace(year=cutoff.year - 1, month=12)
        if cutoff.month == 1
        else cutoff.replace(month=cutoff.month - 1)
    )
    return previous <= source.period_start <= cutoff


def classify_acquisition_failure(
    source: SourceObject,
    config: DualHorizonAcquisition,
    error: Exception,
) -> AcquisitionFailureEvidence:
    message = str(error)
    http_status = error.code if isinstance(error, HTTPError) else None
    if http_status == 404 and is_funding_tail_period(source, config):
        code = "FUNDING_TAIL_ARCHIVE_NOT_YET_AVAILABLE"
        temporary = True
        attempts = 1
    elif isinstance(error, HTTPError):
        code = "RAW_DOWNLOAD_FAILED"
        temporary = False
        attempts = 1
    else:
        prefix = message.split(":", 1)[0]
        stable = {
            "RAW_ARTIFACT_INCOMPLETE",
            "RAW_HASH_MISMATCH",
            "RAW_IDENTITY_MISMATCH",
            "RAW_DOWNLOAD_FAILED",
        }
        code = prefix if prefix in stable else "RAW_DOWNLOAD_FAILED"
        temporary = False
        attempts = 0 if prefix in stable - {"RAW_DOWNLOAD_FAILED"} else config.download_attempts
    return AcquisitionFailureEvidence(
        identity_key=source.identity_key,
        error_code=code,
        message=message,
        http_status=http_status,
        attempt_count=attempts,
        temporary=temporary,
    )
