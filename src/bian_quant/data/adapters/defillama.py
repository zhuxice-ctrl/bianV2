import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from bian_quant.data.adapters.fear_greed import RevisionRisk
from bian_quant.data.adapters.raw import fetch_raw_http
from bian_quant.data.contracts import RawArtifactManifest

SOURCE_URL = "https://stablecoins.llama.fi/stablecoincharts/all"

PUBLICATION_DELAY_24H = timedelta(hours=24)


def download_stablecoin_supply(path: Path) -> RawArtifactManifest:
    return fetch_raw_http(path, url=SOURCE_URL)


def parse_stablecoin_supply(payload: bytes) -> list[dict[str, Any]]:
    data = json.loads(payload)
    if not isinstance(data, list):
        raise ValueError("DeFiLlama stablecoin response is not a list")
    if not data:
        raise ValueError("EXTERNAL_EMPTY: DeFiLlama response contains no observations")
    result = []
    for row in data:
        if not isinstance(row, dict) or "date" not in row or "totalCirculating" not in row:
            raise ValueError("EXTERNAL_SCHEMA_CHANGED: DeFiLlama observation is incomplete")
        date_str = str(row["date"])
        event_time = (
            datetime.fromtimestamp(int(date_str), tz=UTC)
            if date_str.isdigit()
            else datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
        )
        circulating = row["totalCirculating"]
        if isinstance(circulating, dict):
            if "peggedUSD" not in circulating:
                raise ValueError("EXTERNAL_SCHEMA_CHANGED: peggedUSD supply is missing")
            circulating = circulating["peggedUSD"]
        result.append(
            {
                "event_time": event_time,
                "available_time": event_time + PUBLICATION_DELAY_24H,
                "total_supply": float(circulating),
                "revision_risk": RevisionRisk.BACKFILLED_REVISED.value,
                "availability_assumption": "DEFILLAMA_24H_DELAY",
                "source": "defillama/stablecoins",
            }
        )
    return result
