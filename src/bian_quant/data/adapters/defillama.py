import json
from datetime import UTC, datetime, timedelta
from typing import Any

from bian_quant.data.adapters.fear_greed import RevisionRisk

PUBLICATION_DELAY_24H = timedelta(hours=24)


def parse_stablecoin_supply(payload: bytes) -> list[dict[str, Any]]:
    data = json.loads(payload)
    if not isinstance(data, list):
        raise ValueError("DeFiLlama stablecoin response is not a list")
    result = []
    for row in data:
        date_str = row.get("date", "")
        event_time = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
        result.append(
            {
                "event_time": event_time,
                "available_time": event_time + PUBLICATION_DELAY_24H,
                "total_supply": float(row.get("totalCirculating", 0) or 0),
                "revision_risk": RevisionRisk.BACKFILLED_REVISED.value,
                "availability_assumption": "DEFILLAMA_24H_DELAY",
                "source": "defillama/stablecoins",
            }
        )
    return result
