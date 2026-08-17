"""Immutable research family ledger and development-only BH inference.

This module provides:
- ``ResearchFamilyLedger``: append-only SQLite store with immutability
  triggers (BEFORE UPDATE/DELETE → RAISE(ABORT)).
- ``benjamini_hochberg``: BH multiple-testing correction.
- ``run_bh_inference``: BH correction across a full family, with the
  five-tuple key ``(factor_id, horizon, fold, asset, regime)`` and
  denominator = count of all valid p-values in the family.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

BH_KEY_COLUMNS = ("factor_id", "horizon", "fold", "asset", "regime")


@dataclass(frozen=True)
class FamilySnapshot:
    """Frozen snapshot of a research family."""

    family_id: str
    members: tuple[str, ...]
    protocol_sha: str
    bh_boundary: str  # "development" or "production"


def _create_ledger_schema(conn: sqlite3.Connection) -> None:
    """Create tables and immutability triggers."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS research_family_members (
            factor_id     TEXT NOT NULL,
            family_id     TEXT NOT NULL,
            horizon       TEXT NOT NULL,
            registered_at TEXT NOT NULL,
            PRIMARY KEY (factor_id, horizon)
        );

        CREATE TABLE IF NOT EXISTS family_snapshots (
            family_id    TEXT PRIMARY KEY NOT NULL,
            protocol_sha TEXT NOT NULL,
            bh_boundary  TEXT NOT NULL,
            frozen_at    TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS bh_results (
            factor_id   TEXT NOT NULL,
            horizon     TEXT NOT NULL,
            fold        TEXT NOT NULL,
            asset       TEXT NOT NULL,
            regime      TEXT NOT NULL,
            p_value     REAL NOT NULL,
            bh_adjusted REAL NOT NULL,
            PRIMARY KEY (factor_id, horizon, fold, asset, regime)
        );

        CREATE TRIGGER IF NOT EXISTS no_update_members
        BEFORE UPDATE ON research_family_members
        BEGIN
            SELECT RAISE(ABORT, 'research_family_members is append-only');
        END;

        CREATE TRIGGER IF NOT EXISTS no_delete_members
        BEFORE DELETE ON research_family_members
        BEGIN
            SELECT RAISE(ABORT, 'research_family_members is append-only');
        END;

        CREATE TRIGGER IF NOT EXISTS no_update_snapshots
        BEFORE UPDATE ON family_snapshots
        BEGIN
            SELECT RAISE(ABORT, 'family_snapshots is immutable');
        END;

        CREATE TRIGGER IF NOT EXISTS no_delete_snapshots
        BEFORE DELETE ON family_snapshots
        BEGIN
            SELECT RAISE(ABORT, 'family_snapshots is immutable');
        END;

        CREATE TRIGGER IF NOT EXISTS no_update_bh
        BEFORE UPDATE ON bh_results
        BEGIN
            SELECT RAISE(ABORT, 'bh_results is append-only');
        END;

        CREATE TRIGGER IF NOT EXISTS no_delete_bh
        BEFORE DELETE ON bh_results
        BEGIN
            SELECT RAISE(ABORT, 'bh_results is append-only');
        END;
        """,
    )


class ResearchFamilyLedger:
    """Append-only ledger for research family membership and BH inference.

    All tables have ``BEFORE UPDATE`` and ``BEFORE DELETE`` triggers that
    raise ``ABORT``, making the ledger effectively immutable after insert.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path)
        _create_ledger_schema(self._conn)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> ResearchFamilyLedger:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def freeze_family(self, snapshot: FamilySnapshot) -> None:
        """Freeze a family snapshot and register its members.

        Raises ``sqlite3.IntegrityError`` if the family is already frozen.
        """
        now = pd.Timestamp.utcnow().isoformat()
        self._conn.execute(
            "INSERT INTO family_snapshots "
            "(family_id, protocol_sha, bh_boundary, frozen_at) "
            "VALUES (?, ?, ?, ?)",
            (snapshot.family_id, snapshot.protocol_sha, snapshot.bh_boundary, now),
        )
        for member in snapshot.members:
            self._conn.execute(
                "INSERT INTO research_family_members "
                "(factor_id, family_id, horizon, registered_at) "
                "VALUES (?, ?, ?, ?)",
                (member, snapshot.family_id, "primary", now),
            )
        self._conn.commit()

    def get_snapshot(self, family_id: str) -> FamilySnapshot | None:
        """Retrieve a frozen family snapshot, or ``None`` if not found."""
        row = self._conn.execute(
            "SELECT family_id, protocol_sha, bh_boundary FROM family_snapshots WHERE family_id = ?",
            (family_id,),
        ).fetchone()
        if row is None:
            return None
        members = tuple(
            r[0]
            for r in self._conn.execute(
                "SELECT factor_id FROM research_family_members WHERE family_id = ?",
                (family_id,),
            ).fetchall()
        )
        return FamilySnapshot(
            family_id=row[0],
            members=members,
            protocol_sha=row[1],
            bh_boundary=row[2],
        )

    def assert_frozen(
        self,
        family_id: str,
        members: tuple[str, ...],
        *,
        protocol_sha: str,
        bh_boundary: str,
    ) -> None:
        """Fail closed if a frozen family identity has changed."""
        snapshot = self.get_snapshot(family_id)
        if snapshot is None:
            raise ValueError(f"FAMILY_SNAPSHOT_MISSING:{family_id}")
        if (
            snapshot.members != tuple(sorted(members))
            or snapshot.protocol_sha != protocol_sha
            or snapshot.bh_boundary != bh_boundary
        ):
            raise ValueError(f"FAMILY_MEMBERSHIP_MISMATCH:{family_id}")

    def store_bh_results(self, results: pd.DataFrame) -> int:
        """Store BH-adjusted p-values. Returns number of rows inserted."""
        rows_inserted = 0
        for _, row in results.iterrows():
            try:
                self._conn.execute(
                    "INSERT INTO bh_results "
                    "(factor_id, horizon, fold, asset, regime, p_value, bh_adjusted) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(row["factor_id"]),
                        str(row["horizon"]),
                        str(row["fold"]),
                        str(row["asset"]),
                        str(row["regime"]),
                        float(row["p_value"]),
                        float(row["bh_adjusted"]),
                    ),
                )
                rows_inserted += 1
            except sqlite3.IntegrityError:
                pass
        self._conn.commit()
        return rows_inserted


def benjamini_hochberg(p_values: np.ndarray) -> np.ndarray:
    """Compute BH-adjusted p-values.

    NaN values are excluded from correction and remain NaN in the output.
    The denominator *m* is the count of all valid (non-NaN) p-values.
    """
    result = np.full_like(p_values, np.nan, dtype=float)
    valid_mask = np.isfinite(p_values)
    valid_p = p_values[valid_mask]
    m = len(valid_p)
    if m == 0:
        return result

    order = np.argsort(valid_p)
    ranked = valid_p[order]

    adjusted = ranked * m / (np.arange(m) + 1)
    for i in range(m - 2, -1, -1):
        adjusted[i] = min(adjusted[i], adjusted[i + 1])
    adjusted = np.clip(adjusted, 0.0, 1.0)

    unsorted = np.empty(m, dtype=float)
    unsorted[order] = adjusted
    result[valid_mask] = unsorted
    return result


def run_bh_inference(
    evaluations: list[Any],
    *,
    family_id: str = "microstructure_orderflow",
) -> pd.DataFrame:
    """Run BH correction across all evaluations in a family.

    The BH denominator is the count of all valid p-values across the
    entire family and all horizons. The BH key is the five-tuple
    ``(factor_id, horizon, fold, asset, regime)``.

    Parameters
    ----------
    evaluations
        List of objects with attributes: ``factor_name`` (or
        ``factor_id``), ``horizon``, ``fold``, ``asset``, ``regime``,
        ``p_value``.

    Returns
    -------
    DataFrame with columns: factor_id, horizon, fold, asset, regime,
    p_value, bh_adjusted.
    """
    records: list[dict[str, object]] = []
    for ev in evaluations:
        factor_id = getattr(ev, "factor_name", getattr(ev, "factor_id", ""))
        horizon = getattr(ev, "horizon", "primary")
        records.append(
            {
                "factor_id": factor_id,
                "horizon": horizon,
                "fold": ev.fold,
                "asset": ev.asset,
                "regime": ev.regime,
                "p_value": ev.p_value,
            },
        )
    df = pd.DataFrame(records)
    if df.empty:
        return df.assign(bh_adjusted=pd.Series(dtype=float))

    p_vals = df["p_value"].to_numpy(dtype=float)
    df["bh_adjusted"] = benjamini_hochberg(p_vals)
    return df
