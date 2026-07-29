import json
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from bian_quant.data.adapters.raw import fetch_raw_http
from bian_quant.data.contracts import RawArtifactManifest

SOURCE_URL = "https://api.alternative.me/fng/?limit=0&format=json"


class RevisionRisk(StrEnum):
    POINT_IN_TIME = "point_in_time"
    PUBLICATION_DELAY_ASSUMED = "publication_delay_assumed"
    BACKFILLED_REVISED = "backfilled_revised"


PUBLICATION_DELAY_24H = timedelta(hours=24)


def download_fear_greed(path: Path) -> RawArtifactManifest:
    return fetch_raw_http(path, url=SOURCE_URL)


def parse_fear_greed(payload: bytes) -> list[dict[str, Any]]:
    data = json.loads(payload)
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise ValueError("EXTERNAL_SCHEMA_CHANGED: Fear & Greed data must be a list")
    if not data["data"]:
        raise ValueError("EXTERNAL_EMPTY: Fear & Greed response contains no observations")
    result = []
    for item in data["data"]:
        if not isinstance(item, dict) or not {"timestamp", "value"} <= item.keys():
            raise ValueError("EXTERNAL_SCHEMA_CHANGED: Fear & Greed observation is incomplete")
        event_time = datetime.fromtimestamp(int(item["timestamp"]), tz=UTC)
        result.append(
            {
                "event_time": event_time,
                "available_time": event_time + PUBLICATION_DELAY_24H,
                "value": int(item["value"]),
                "classification": item.get("value_classification", ""),
                "revision_risk": RevisionRisk.PUBLICATION_DELAY_ASSUMED.value,
                "availability_assumption": "FGN_DAILY_24H_DELAY",
                "source": "alternative.me/fng",
            }
        )
    return result
