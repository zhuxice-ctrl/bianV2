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


def is_cutoff_month_funding(source: SourceObject, config: DualHorizonAcquisition) -> bool:
    return (
        source.dataset == SourceDataset.FUNDING
        and source.granularity == SourceGranularity.MONTHLY
        and (source.period_start.year, source.period_start.month)
        == (config.as_of.year, config.as_of.month)
    )


def classify_acquisition_failure(
    source: SourceObject,
    config: DualHorizonAcquisition,
    error: Exception,
) -> AcquisitionFailureEvidence:
    message = str(error)
    http_status = error.code if isinstance(error, HTTPError) else None
    if http_status == 404 and is_cutoff_month_funding(source, config):
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
