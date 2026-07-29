import csv
import io
from datetime import UTC, datetime

from bian_quant.data.adapters.fear_greed import RevisionRisk


def parse_fred_csv(payload: bytes, series_id: str = "WALCL") -> list[dict]:
    text = payload.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    result = []
    for row in reader:
        date_str = row.get("observation_date", row.get("DATE", ""))
        value_str = row.get(series_id, row.get("WALCL", ""))
        if not date_str or not value_str:
            continue
        event_time = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
        result.append({
            "event_time": event_time,
            "available_time": event_time,
            "value": float(value_str),
            "revision_risk": RevisionRisk.BACKFILLED_REVISED.value,
            "availability_assumption": "FRED_CSV_NOT_POINT_IN_TIME",
            "source": "fred.stlouisfed.org",
        })
    return result
