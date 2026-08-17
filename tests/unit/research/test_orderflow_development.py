"""Tests for immutable research family ledger and BH inference."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest

from bian_quant.research.orderflow_development import (
    BH_KEY_COLUMNS,
    FamilySnapshot,
    ResearchFamilyLedger,
    benjamini_hochberg,
    run_bh_inference,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FakeEval:
    """Minimal evaluation object for BH testing."""

    factor_name: str
    horizon: str
    fold: str
    asset: str
    regime: str
    p_value: float
    q: float = 0.2


def _make_snapshot() -> FamilySnapshot:
    return FamilySnapshot(
        family_id="microstructure_orderflow",
        members=("taker_orderflow_imbalance@1.0.0",),
        protocol_sha="abc123def456",
        bh_boundary="development",
    )


# ---------------------------------------------------------------------------
# ResearchFamilyLedger — immutability
# ---------------------------------------------------------------------------


def test_freeze_and_retrieve_snapshot(tmp_path: object) -> None:
    db = tmp_path / "ledger.db"  # type: ignore[operator]
    with ResearchFamilyLedger(db) as ledger:
        ledger.freeze_family(_make_snapshot())
        snap = ledger.get_snapshot("microstructure_orderflow")
        assert snap is not None
        assert snap.family_id == "microstructure_orderflow"
        assert snap.protocol_sha == "abc123def456"
        assert snap.bh_boundary == "development"
        assert "taker_orderflow_imbalance@1.0.0" in snap.members


def test_get_snapshot_returns_none_for_unknown_family(tmp_path: object) -> None:
    db = tmp_path / "ledger.db"  # type: ignore[operator]
    with ResearchFamilyLedger(db) as ledger:
        assert ledger.get_snapshot("nonexistent") is None


def test_family_snapshot_mismatch_is_rejected(tmp_path: object) -> None:
    db = tmp_path / "ledger.db"  # type: ignore[operator]
    with ResearchFamilyLedger(db) as ledger:
        snapshot = _make_snapshot()
        ledger.freeze_family(snapshot)
        with pytest.raises(ValueError, match="FAMILY_MEMBERSHIP_MISMATCH"):
            ledger.assert_frozen(
                snapshot.family_id,
                ("other@1.0.0",),
                protocol_sha=snapshot.protocol_sha,
                bh_boundary=snapshot.bh_boundary,
            )


def test_update_on_members_is_rejected(tmp_path: object) -> None:
    db = tmp_path / "ledger.db"  # type: ignore[operator]
    with ResearchFamilyLedger(db) as ledger:
        ledger.freeze_family(_make_snapshot())
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            ledger._conn.execute(  # noqa: SLF001
                "UPDATE research_family_members SET factor_id = 'hacked' WHERE 1=1",
            )


def test_delete_on_members_is_rejected(tmp_path: object) -> None:
    db = tmp_path / "ledger.db"  # type: ignore[operator]
    with ResearchFamilyLedger(db) as ledger:
        ledger.freeze_family(_make_snapshot())
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            ledger._conn.execute(  # noqa: SLF001
                "DELETE FROM research_family_members WHERE 1=1",
            )


def test_update_on_snapshots_is_rejected(tmp_path: object) -> None:
    db = tmp_path / "ledger.db"  # type: ignore[operator]
    with ResearchFamilyLedger(db) as ledger:
        ledger.freeze_family(_make_snapshot())
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            ledger._conn.execute(  # noqa: SLF001
                "UPDATE family_snapshots SET protocol_sha = 'hacked' WHERE 1=1",
            )


def test_delete_on_snapshots_is_rejected(tmp_path: object) -> None:
    db = tmp_path / "ledger.db"  # type: ignore[operator]
    with ResearchFamilyLedger(db) as ledger:
        ledger.freeze_family(_make_snapshot())
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            ledger._conn.execute(  # noqa: SLF001
                "DELETE FROM family_snapshots WHERE 1=1",
            )


def test_double_freeze_raises(tmp_path: object) -> None:
    db = tmp_path / "ledger.db"  # type: ignore[operator]
    with ResearchFamilyLedger(db) as ledger:
        ledger.freeze_family(_make_snapshot())
        with pytest.raises(sqlite3.IntegrityError):
            ledger.freeze_family(_make_snapshot())


# ---------------------------------------------------------------------------
# BH correction — benjamini_hochberg
# ---------------------------------------------------------------------------


def test_bh_key_is_six_tuple() -> None:
    assert BH_KEY_COLUMNS == (
        "factor_id",
        "horizon",
        "fold",
        "asset",
        "regime",
        "q",
    )


def test_bh_single_p_value_unchanged() -> None:
    p = np.array([0.05])
    adj = benjamini_hochberg(p)
    assert adj[0] == pytest.approx(0.05)


def test_bh_known_values() -> None:
    """Hand-calculated BH for 4 p-values.

    p = [0.01, 0.02, 0.03, 0.04], m = 4
    Sorted: [0.01, 0.02, 0.03, 0.04]
    Ranks:  1, 2, 3, 4
    Raw adj: 0.01*4/1=0.04, 0.02*4/2=0.04, 0.03*4/3=0.04, 0.04*4/4=0.04
    Monotone: all 0.04
    """
    p = np.array([0.01, 0.02, 0.03, 0.04])
    adj = benjamini_hochberg(p)
    assert np.allclose(adj, 0.04)


def test_bh_nan_excluded_from_denominator() -> None:
    """NaN p-values are excluded; m = count of valid p-values only."""
    p = np.array([0.01, np.nan, 0.04])
    adj = benjamini_hochberg(p)
    assert np.isnan(adj[1])
    # m = 2 (two valid), sorted [0.01, 0.04]
    # adj: 0.01*2/1=0.02, 0.04*2/2=0.04 → monotone [0.02, 0.04]
    assert adj[0] == pytest.approx(0.02)
    assert adj[2] == pytest.approx(0.04)


def test_bh_monotonicity_enforced() -> None:
    """Adjusted p-values must be non-decreasing in sorted order."""
    p = np.array([0.001, 0.01, 0.5, 0.9])
    adj = benjamini_hochberg(p)
    sorted_adj = np.sort(adj)
    assert np.allclose(adj[np.argsort(p)], sorted_adj)


def test_bh_clipped_to_one() -> None:
    p = np.array([0.9, 0.95])
    adj = benjamini_hochberg(p)
    assert adj.max() <= 1.0


# ---------------------------------------------------------------------------
# run_bh_inference — integration
# ---------------------------------------------------------------------------


def test_run_bh_inference_basic() -> None:
    evals = [
        FakeEval("f1", "primary", "fold1", "BTC", "trending", 0.01),
        FakeEval("f1", "primary", "fold1", "ETH", "trending", 0.04),
        FakeEval("f1", "primary", "fold1", "BTC", "ranging", 0.50),
    ]
    df = run_bh_inference(evals)
    assert len(df) == 3
    assert "bh_adjusted" in df.columns
    # All valid p-values → m = 3
    # Sorted: [0.01, 0.04, 0.50], ranks 1, 2, 3
    # Raw: 0.01*3/1=0.03, 0.04*3/2=0.06, 0.50*3/3=0.50
    # Monotone: [0.03, 0.06, 0.50]
    btc_trending = df[(df["asset"] == "BTC") & (df["regime"] == "trending")]
    assert btc_trending["bh_adjusted"].iloc[0] == pytest.approx(0.03)


def test_run_bh_inference_multi_horizon() -> None:
    """BH denominator spans all horizons."""
    evals = [
        FakeEval("f1", "1h", "fold1", "BTC", "trending", 0.01),
        FakeEval("f1", "2h", "fold1", "BTC", "trending", 0.02),
        FakeEval("f1", "4h", "fold1", "BTC", "trending", 0.03),
        FakeEval("f1", "1h", "fold1", "ETH", "trending", 0.04),
    ]
    df = run_bh_inference(evals)
    # m = 4
    # Sorted: [0.01, 0.02, 0.03, 0.04], ranks 1,2,3,4
    # Raw: 0.04, 0.04, 0.04, 0.04 → monotone all 0.04
    assert np.allclose(df["bh_adjusted"].values, 0.04)


def test_run_bh_inference_empty() -> None:
    df = run_bh_inference([])
    assert df.empty
    assert "bh_adjusted" in df.columns


def test_run_bh_inference_with_nan_p_values() -> None:
    evals = [
        FakeEval("f1", "1h", "fold1", "BTC", "trending", float("nan")),
        FakeEval("f1", "1h", "fold1", "ETH", "trending", 0.02),
    ]
    df = run_bh_inference(evals)
    # m = 1 (only one valid)
    btc = df[df["asset"] == "BTC"]
    eth = df[df["asset"] == "ETH"]
    assert np.isnan(btc["bh_adjusted"].iloc[0])
    assert eth["bh_adjusted"].iloc[0] == pytest.approx(0.02)


def test_bh_results_stored_in_ledger(tmp_path: object) -> None:
    db = tmp_path / "ledger.db"  # type: ignore[operator]
    evals = [
        FakeEval("f1", "1h", "fold1", "BTC", "trending", 0.01),
        FakeEval("f1", "2h", "fold1", "ETH", "ranging", 0.02),
    ]
    df = run_bh_inference(evals)
    with ResearchFamilyLedger(db) as ledger:
        ledger.freeze_family(_make_snapshot())
        n = ledger.store_bh_results(df)
        assert n == 2


def test_bh_results_update_rejected(tmp_path: object) -> None:
    db = tmp_path / "ledger.db"  # type: ignore[operator]
    with ResearchFamilyLedger(db) as ledger:
        ledger.freeze_family(_make_snapshot())
        df = pd.DataFrame(
            {
                "factor_id": ["f1"],
                "horizon": ["1h"],
                "fold": ["fold1"],
                "asset": ["BTC"],
                "regime": ["trending"],
                "p_value": [0.01],
                "bh_adjusted": [0.02],
            },
        )
        ledger.store_bh_results(df)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            ledger._conn.execute(  # noqa: SLF001
                "UPDATE bh_results SET p_value = 0.99 WHERE 1=1",
            )


# ---------------------------------------------------------------------------
# Six-tuple schema migration and q-sensitivity BH
# ---------------------------------------------------------------------------


def test_run_bh_inference_emits_q_column() -> None:
    evals = [
        FakeEval("f1", "1h", "fold1", "BTC", "trending", 0.01, q=0.2),
        FakeEval("f1", "1h", "fold1", "BTC", "trending", 0.02, q=0.1),
    ]
    df = run_bh_inference(evals)
    assert "q" in df.columns
    assert set(df["q"].tolist()) == {0.1, 0.2}


def test_q_sensitivity_inflates_bh_denominator() -> None:
    """q ∈ {0.1, 0.2, 0.3} p-values must all enter the BH denominator."""
    # Three q values for the same slice → m = 3.
    evals = [
        FakeEval("f1", "1h", "fold1", "BTC", "trending", 0.01, q=0.1),
        FakeEval("f1", "1h", "fold1", "BTC", "trending", 0.01, q=0.2),
        FakeEval("f1", "1h", "fold1", "BTC", "trending", 0.5, q=0.3),
    ]
    df = run_bh_inference(evals)
    # m = 3, sorted [0.01, 0.01, 0.5], ranks 1, 2, 3
    # raw: 0.01*3/1=0.03, 0.01*3/2=0.015, 0.5*3/3=0.5
    # monotone (cumulative min from right): [0.015, 0.015, 0.5]
    assert np.allclose(np.sort(df["bh_adjusted"].values), [0.015, 0.015, 0.5])
    # Compare against a single-q family (m = 1): the small p is adjusted to
    # 0.01 (m=1) rather than 0.015 (m=3) — denominator inflation is visible.
    single = run_bh_inference([FakeEval("f1", "1h", "fold1", "BTC", "trending", 0.01, q=0.2)])
    assert single["bh_adjusted"].iloc[0] == pytest.approx(0.01)


def test_fresh_ledger_has_six_tuple_bh_schema(tmp_path: object) -> None:
    db = tmp_path / "ledger.db"  # type: ignore[operator]
    with ResearchFamilyLedger(db) as ledger:
        cols = {
            row[1]
            for row in ledger._conn.execute("PRAGMA table_info(bh_results)").fetchall()  # noqa: SLF001
        }
        assert "q" in cols


def test_legacy_fivetuple_ledger_is_migrated(tmp_path: object) -> None:
    """A pre-migration five-tuple ledger is migrated in place, history kept."""
    db = tmp_path / "ledger.db"  # type: ignore[operator]
    # Build a legacy five-tuple schema by hand.
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE research_family_members (
            factor_id TEXT NOT NULL, family_id TEXT NOT NULL,
            horizon TEXT NOT NULL, registered_at TEXT NOT NULL,
            PRIMARY KEY (factor_id, horizon));
        CREATE TABLE family_snapshots (
            family_id TEXT PRIMARY KEY, protocol_sha TEXT NOT NULL,
            bh_boundary TEXT NOT NULL, frozen_at TEXT NOT NULL);
        CREATE TABLE bh_results (
            factor_id TEXT NOT NULL, horizon TEXT NOT NULL, fold TEXT NOT NULL,
            asset TEXT NOT NULL, regime TEXT NOT NULL,
            p_value REAL NOT NULL, bh_adjusted REAL NOT NULL,
            PRIMARY KEY (factor_id, horizon, fold, asset, regime));
        INSERT INTO bh_results VALUES ('f1','1h','fold1','BTC','trending',0.01,0.02);
        """,
    )
    conn.commit()
    conn.close()

    # Opening via ResearchFamilyLedger triggers the migration.
    with ResearchFamilyLedger(db) as ledger:
        cols = {
            row[1]
            for row in ledger._conn.execute("PRAGMA table_info(bh_results)").fetchall()  # noqa: SLF001
        }
        assert "q" in cols
        row = ledger._conn.execute(  # noqa: SLF001
            "SELECT q, p_value, bh_adjusted FROM bh_results",
        ).fetchone()
        assert row == (0.2, 0.01, 0.02)
        # Legacy table preserved (history retained, not dropped).
        legacy = ledger._conn.execute(  # noqa: SLF001
            "SELECT name FROM sqlite_master WHERE name = 'bh_results_legacy_fivetuple'",
        ).fetchone()
        assert legacy is not None


def test_migration_is_idempotent(tmp_path: object) -> None:
    db = tmp_path / "ledger.db"  # type: ignore[operator]
    with ResearchFamilyLedger(db) as ledger:
        ledger.freeze_family(_make_snapshot())
    # Re-opening must be a no-op (no error, schema unchanged).
    with ResearchFamilyLedger(db) as ledger:
        cols = {
            row[1]
            for row in ledger._conn.execute("PRAGMA table_info(bh_results)").fetchall()  # noqa: SLF001
        }
        assert "q" in cols
