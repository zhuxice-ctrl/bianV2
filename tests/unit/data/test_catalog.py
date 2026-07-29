from datetime import UTC, datetime
from pathlib import Path

from bian_quant.data.catalog import DatasetCatalog
from bian_quant.data.contracts import DatasetLayer, DatasetManifest


def test_catalog_rejects_snapshot_id_reuse_with_different_content(tmp_path: Path) -> None:
    catalog = DatasetCatalog(tmp_path / "registry.sqlite")
    base = DatasetManifest(
        snapshot_id="legacy-v1",
        layer=DatasetLayer.CANONICAL,
        name="ohlcv_4h",
        content_sha256="a" * 64,
        row_count=1,
        min_event_time=datetime(2026, 1, 1, tzinfo=UTC),
        max_event_time=datetime(2026, 1, 1, tzinfo=UTC),
        parent_snapshot_ids=[],
        config_json="{}",
    )
    catalog.register(base, path=tmp_path / "one.parquet")

    changed = base.model_copy(update={"content_sha256": "b" * 64})

    try:
        catalog.register(changed, path=tmp_path / "two.parquet")
    except ValueError as error:
        assert "snapshot_id already exists" in str(error)
    else:
        raise AssertionError("catalog allowed evidence replacement")
