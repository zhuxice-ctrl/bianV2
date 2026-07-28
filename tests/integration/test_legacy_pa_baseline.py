import json
from pathlib import Path

from bian_quant.legacy.pa_baseline import replay_all


def test_legacy_pa_metrics_match_tracked_golden() -> None:
    repo = Path(__file__).parents[2]
    expected = json.loads((repo / "tests/golden/baseline_summary.json").read_text(encoding="utf-8"))
    actual = replay_all(repo)
    assert actual == expected
