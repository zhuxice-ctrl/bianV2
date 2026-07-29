"""SQLite-backed append-only experiment registry.

Only status *transitions* are recorded; the manifest itself is immutable.
Each transition appends a new row to the ``run_transitions`` table, giving
a full audit trail.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .models import RunManifest, RunStatus

# Legal forward transitions: from_status -> {allowed_next_statuses}
LEGAL_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.PENDING: frozenset({RunStatus.RUNNING, RunStatus.CANCELLED}),
    RunStatus.RUNNING: frozenset({RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}),
    RunStatus.COMPLETED: frozenset(),
    RunStatus.FAILED: frozenset({RunStatus.PENDING}),
    RunStatus.CANCELLED: frozenset({RunStatus.PENDING}),
}


_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id           TEXT PRIMARY KEY,
    status           TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    strategy_name    TEXT NOT NULL,
    config_json      TEXT NOT NULL,
    code_sha256      TEXT NOT NULL,
    data_snapshot_id TEXT NOT NULL,
    parent_run_id    TEXT,
    notes            TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS run_transitions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL REFERENCES runs(run_id),
    from_status TEXT,
    to_status  TEXT NOT NULL,
    transition_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_run_transitions_run_id
    ON run_transitions(run_id);
"""


class ExperimentRegistry:
    """Append-only registry backed by SQLite."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> ExperimentRegistry:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # -- write operations -------------------------------------------------

    def create(self, manifest: RunManifest) -> RunManifest:
        """Insert a new run.  Raises ``ValueError`` if ``run_id`` already exists."""
        existing = self._conn.execute(
            "SELECT 1 FROM runs WHERE run_id = ?", (manifest.run_id,)
        ).fetchone()
        if existing is not None:
            raise ValueError(f"run_id {manifest.run_id} already exists")

        self._conn.execute(
            """
            INSERT INTO runs
                (run_id, status, created_at, strategy_name,
                 config_json, code_sha256, data_snapshot_id,
                 parent_run_id, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                manifest.run_id,
                manifest.status.value,
                manifest.created_at.isoformat(),
                manifest.strategy_name,
                manifest.config_json,
                manifest.code_sha256,
                manifest.data_snapshot_id,
                manifest.parent_run_id,
                manifest.notes,
            ),
        )
        self._conn.execute(
            """
            INSERT INTO run_transitions (run_id, from_status, to_status, transition_at)
            VALUES (?, NULL, ?, ?)
            """,
            (manifest.run_id, manifest.status.value, datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()
        return manifest

    def transition(
        self,
        run_id: str,
        to_status: RunStatus,
    ) -> RunManifest:
        """Transition a run to ``to_status``.

        Raises ``KeyError`` if the run does not exist, or ``ValueError``
        if the transition is not in ``LEGAL_TRANSITIONS``.
        """
        row = self._conn.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"run_id {run_id} not found")

        current = RunStatus(row["status"])
        if to_status not in LEGAL_TRANSITIONS.get(current, frozenset()):
            raise ValueError(
                f"illegal transition {current.value} -> {to_status.value}"
            )

        self._conn.execute(
            "UPDATE runs SET status = ? WHERE run_id = ?",
            (to_status.value, run_id),
        )
        self._conn.execute(
            """
            INSERT INTO run_transitions (run_id, from_status, to_status, transition_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                run_id,
                current.value,
                to_status.value,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()
        return self.get(run_id)

    # -- read operations --------------------------------------------------

    def get(self, run_id: str) -> RunManifest:
        row = self._conn.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"run_id {run_id} not found")
        return _row_to_manifest(row)

    def list_runs(self) -> list[RunManifest]:
        rows = self._conn.execute(
            "SELECT * FROM runs ORDER BY created_at"
        ).fetchall()
        return [_row_to_manifest(r) for r in rows]

    def transition_history(self, run_id: str) -> list[dict[str, str | None]]:
        rows = self._conn.execute(
            """
            SELECT from_status, to_status, transition_at
            FROM run_transitions WHERE run_id = ?
            ORDER BY id
            """,
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def _row_to_manifest(row: sqlite3.Row) -> RunManifest:
    return RunManifest(
        run_id=row["run_id"],
        status=RunStatus(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        strategy_name=row["strategy_name"],
        config_json=row["config_json"],
        code_sha256=row["code_sha256"],
        data_snapshot_id=row["data_snapshot_id"],
        parent_run_id=row["parent_run_id"],
        notes=row["notes"],
    )
