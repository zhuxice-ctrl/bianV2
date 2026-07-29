import json
from datetime import UTC, datetime

import pytest

from bian_quant.data.adapters.defillama import parse_stablecoin_supply
from bian_quant.data.adapters.fear_greed import RevisionRisk, parse_fear_greed
from bian_quant.data.adapters.fred import parse_fred_csv
from bian_quant.data.external_policy import can_promote_to, enforce_ceiling


def test_parse_fear_greed() -> None:
    payload = json.dumps(
        {
            "data": [
                {"timestamp": "1738368000", "value": "50", "value_classification": "Neutral"},
            ]
        }
    ).encode("utf-8")

    result = parse_fear_greed(payload)

    assert len(result) == 1
    assert result[0]["value"] == 50
    assert result[0]["revision_risk"] == RevisionRisk.PUBLICATION_DELAY_ASSUMED.value


def test_parse_defillama() -> None:
    payload = json.dumps(
        [
            {"date": "1735689600", "totalCirculating": {"peggedUSD": 150000000000}},
        ]
    ).encode("utf-8")

    result = parse_stablecoin_supply(payload)

    assert len(result) == 1
    assert result[0]["total_supply"] == 150000000000.0
    assert result[0]["revision_risk"] == RevisionRisk.BACKFILLED_REVISED.value


def test_parse_fred_csv() -> None:
    payload = b"observation_date,WALCL\n2025-01-01,8000000\n2025-01-08,8100000\n"

    observed_at = datetime(2025, 2, 1, tzinfo=UTC)
    result = parse_fred_csv(payload, observed_at=observed_at)

    assert len(result) == 2
    assert result[0]["value"] == 8000000.0
    assert result[0]["revision_risk"] == RevisionRisk.BACKFILLED_REVISED.value
    assert result[0]["available_time"] == observed_at


def test_backfilled_risk_blocks_promotion() -> None:
    risks = [RevisionRisk.BACKFILLED_REVISED.value]

    assert can_promote_to("observed", risks) is True
    assert can_promote_to("validated", risks) is False
    assert can_promote_to("alpha", risks) is False


def test_enforce_ceiling_rejects_promotion() -> None:
    risks = [RevisionRisk.BACKFILLED_REVISED.value]

    with pytest.raises(ValueError, match="Cannot promote"):
        enforce_ceiling("validated", risks)


def test_enforce_ceiling_allows_observed() -> None:
    risks = [RevisionRisk.BACKFILLED_REVISED.value]

    enforce_ceiling("observed", risks)


def test_invalid_json_raises() -> None:
    with pytest.raises(json.JSONDecodeError):
        parse_fear_greed(b"not json")


def test_empty_fred_csv_is_not_a_successful_dataset() -> None:
    payload = b"observation_date,WALCL\n"

    with pytest.raises(ValueError, match="EXTERNAL_EMPTY"):
        parse_fred_csv(payload, observed_at=datetime(2025, 2, 1, tzinfo=UTC))


def test_live_defillama_shape_is_supported() -> None:
    payload = json.dumps(
        [{"date": "1511913600", "totalCirculating": {"peggedUSD": 109970}}]
    ).encode()

    result = parse_stablecoin_supply(payload)

    assert result[0]["total_supply"] == 109970.0
    assert result[0]["event_time"] == datetime(2017, 11, 29, tzinfo=UTC)


def test_unknown_promotion_level_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown promotion level"):
        enforce_ceiling("production", [])
