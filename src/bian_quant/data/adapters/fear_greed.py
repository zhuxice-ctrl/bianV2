import json
from datetime import UTC, datetime, timedelta
from enum import StrEnum


class RevisionRisk(StrEnum):
    POINT_IN_TIME = "point_in_time"
    PUBLICATION_DELAY_ASSUMED = "publication_delay_assumed"
    BACKFILLED_REVISED = "backfilled_revised"


PUBLICATION_DELAY_24H = timedelta(hours=24)


def parse_fear_greed(payload: bytes) -> list[dict]:
    data = json.loads(payload)
    result = []
    for item in data.get("data", []):
        event_time = datetime.fromtimestamp(int(item["timestamp"]), tz=UTC)
        result.append({
            "event_time": event_time,
            "available_time": event_time + PUBLICATION_DELAY_24H,
            "value": int(item["value"]),
            "classification": item.get("value_classification", ""),
            "revision_risk": RevisionRisk.PUBLICATION_DELAY_ASSUMED.value,
            "availability_assumption": "FGN_DAILY_24H_DELAY",
            "source": "alternative.me/fng",
        })
    return result
