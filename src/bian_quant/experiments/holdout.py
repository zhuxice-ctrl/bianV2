"""Append-only holdout ledger and dual-horizon window partitioning.

The holdout ledger enforces one-time access per (snapshot_id, factor_id,
factor_version) and rejects non-CANDIDATE factors.  SQLite triggers prevent
UPDATE and DELETE on the access table, making it truly append-only.

Window partitioning uses the four explicit timestamps from the factor protocol:
development is start-inclusive/end-exclusive, holdout is start-inclusive/
end-inclusive, and the alignment buffer lies between them — returned for audit
but never used for fitting, selection, or holdout evaluation.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from bian_quant.factors.spec import FactorState

if TYPE_CHECKING:
    from bian_quant.data.acquisition import FactorProtocolConfig


@dataclass(frozen=True)
class DualHorizonWindows:
    """Partitioned index for development, alignment buffer, and holdout."""

    development: pd.DatetimeIndex
    alignment_buffer: pd.DatetimeIndex
    holdout: pd.DatetimeIndex


def partition_dual_horizon_windows(
    index: pd.DatetimeIndex,
    factor_protocol: FactorProtocolConfig,
) -> DualHorizonWindows:
    """Partition *index* into development, alignment buffer, and holdout.

    Development: [development_start, development_end_exclusive)
    Alignment:   [development_end_exclusive, holdout_start)
    Holdout:     [holdout_start, holdout_end]
    """
    dev_start = pd.Timestamp(factor_protocol.development_start)
    dev_end = pd.Timestamp(factor_protocol.development_end_exclusive)
    holdout_start = pd.Timestamp(factor_protocol.holdout_start)
    holdout_end = pd.Timestamp(factor_protocol.holdout_end)

    # Ensure tz-aware for comparison
    if index.tz is None:
        index = index.tz_localize("UTC")

    development = index[(index >= dev_start) & (index < dev_end)]
    alignment = index[(index >= dev_end) & (index < holdout_start)]
    holdout = index[(index >= holdout_start) & (index <= holdout_end)]

    return DualHorizonWindows(
        development=development,
        alignment_buffer=alignment,
        holdout=holdout,
    )


class HoldoutLedger:
    """Append-only SQLite ledger enforcing one-time holdout access.

    Only ``FactorState.CANDIDATE`` factors may access the holdout.
    Each (snapshot_id, factor_id, factor_version) combination can be
    opened exactly once.  Triggers reject UPDATE and DELETE.
    """

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        conn = self._connection()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS holdout_access (
                snapshot_id   TEXT NOT NULL,
                factor_id     TEXT NOT NULL,
                factor_version TEXT NOT NULL,
                factor_state  TEXT NOT NULL,
                access_run_id TEXT NOT NULL,
                accessed_at   TEXT NOT NULL,
                PRIMARY KEY (snapshot_id, factor_id, factor_version)
            )
            """
        )
        # Triggers to prevent UPDATE and DELETE
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS prevent_update_holdout_access
            BEFORE UPDATE ON holdout_access
            BEGIN
                SELECT RAISE(ABORT, 'HOLDOUT_ACCESS_DENIED: holdout_access is append-only');
            END
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS prevent_delete_holdout_access
            BEFORE DELETE ON holdout_access
            BEGIN
                SELECT RAISE(ABORT, 'HOLDOUT_ACCESS_DENIED: holdout_access is append-only');
            END
            """
        )
        conn.commit()

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def authorize(
        self,
        *,
        snapshot_id: str,
        factor_id: str,
        factor_version: str,
        factor_state: FactorState,
        access_run_id: str,
    ) -> dict:
        """Authorize holdout access for a candidate factor.

        Raises ``PermissionError`` if the factor is not CANDIDATE or if
        the same (snapshot_id, factor_id, factor_version) has already been
        authorized.
        """
        if factor_state != FactorState.CANDIDATE:
            raise PermissionError(
                "HOLDOUT_ACCESS_DENIED: only CANDIDATE factors may access the holdout"
            )

        conn = self._connection()
        existing = conn.execute(
            """
            SELECT 1 FROM holdout_access
            WHERE snapshot_id = ? AND factor_id = ? AND factor_version = ?
            """,
            (snapshot_id, factor_id, factor_version),
        ).fetchone()
        if existing is not None:
            raise PermissionError(
                "HOLDOUT_ACCESS_DENIED: holdout already accessed for "
                f"({snapshot_id}, {factor_id}, {factor_version})"
            )

        accessed_at = datetime.now(UTC).isoformat()
        conn.execute(
            """
            INSERT INTO holdout_access
                (snapshot_id, factor_id, factor_version, factor_state, access_run_id, accessed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                factor_id,
                factor_version,
                factor_state.value,
                access_run_id,
                accessed_at,
            ),
        )
        conn.commit()
        return {
            "snapshot_id": snapshot_id,
            "factor_id": factor_id,
            "factor_version": factor_version,
            "factor_state": factor_state.value,
            "access_run_id": access_run_id,
            "accessed_at": accessed_at,
        }

    def history(self) -> list[dict]:
        """Return all access records for audit."""
        conn = self._connection()
        rows = conn.execute(
            """
            SELECT snapshot_id, factor_id, factor_version, factor_state,
                   access_run_id, accessed_at
            FROM holdout_access
            ORDER BY accessed_at
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> HoldoutLedger:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
