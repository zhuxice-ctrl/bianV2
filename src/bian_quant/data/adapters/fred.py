import csv
import io
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bian_quant.data.adapters.fear_greed import RevisionRisk
from bian_quant.data.adapters.raw import fetch_raw_http
from bian_quant.data.contracts import RawArtifactManifest

SOURCE_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"


def download_fred(path: Path, *, series_id: str = "WALCL") -> RawArtifactManifest:
    return fetch_raw_http(path, url=SOURCE_URL.format(series_id=series_id))


def parse_fred_csv(
    payload: bytes, *, observed_at: datetime, series_id: str = "WALCL"
) -> list[dict[str, Any]]:
    if observed_at.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    text = payload.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or not {"observation_date", series_id} <= set(reader.fieldnames):
        raise ValueError("EXTERNAL_SCHEMA_CHANGED: FRED columns are missing")
    result = []
    for row in reader:
        date_str = row.get("observation_date", row.get("DATE", ""))
        value_str = row.get(series_id, row.get("WALCL", ""))
        if not date_str or not value_str:
            continue
        event_time = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
        result.append(
            {
                "event_time": event_time,
                "available_time": observed_at,
                "ingested_at": observed_at,
                "value": float(value_str),
                "revision_risk": RevisionRisk.BACKFILLED_REVISED.value,
                "availability_assumption": "FRED_CSV_NOT_POINT_IN_TIME",
                "source": "fred.stlouisfed.org",
            }
        )
    if not result:
        raise ValueError("EXTERNAL_EMPTY: FRED response contains no observations")
    return result
