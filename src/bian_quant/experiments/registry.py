import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from bian_quant.experiments.models import LockedHoldout, RunManifest, RunStatus

LEGAL_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.QUEUED: frozenset({RunStatus.RUNNING, RunStatus.BLOCKED}),
    RunStatus.RUNNING: frozenset({RunStatus.PASSED, RunStatus.FAILED, RunStatus.BLOCKED}),
    RunStatus.PASSED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.BLOCKED: frozenset(),
}


_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    identity_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    code_sha TEXT NOT NULL,
    dataset_snapshot_ids_json TEXT NOT NULL,
    config_json TEXT NOT NULL,
    seed INTEGER NOT NULL,
    locked_holdout_json TEXT,
    parent_run_id TEXT,
    status TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_identity ON runs(identity_sha256);
CREATE TABLE IF NOT EXISTS run_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    from_status TEXT,
    to_status TEXT NOT NULL,
    transition_at TEXT NOT NULL
);
"""


class ExperimentRegistry:
    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._connection = sqlite3.connect(str(db_path))
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(_SCHEMA)

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "ExperimentRegistry":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def create(self, manifest: RunManifest) -> None:
        with self._connection:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._connection.execute(
                    "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        manifest.run_id,
                        manifest.identity_sha256,
                        manifest.created_at.isoformat(),
                        manifest.strategy_name,
                        manifest.code_sha,
                        json.dumps(manifest.dataset_snapshot_ids),
                        manifest.config_json,
                        manifest.seed,
                        (
                            manifest.locked_holdout.model_dump_json()
                            if manifest.locked_holdout is not None
                            else None
                        ),
                        manifest.parent_run_id,
                        manifest.status.value,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError("run_id already exists") from error
            self._append_transition(manifest.run_id, None, manifest.status)

    def transition(self, run_id: str, to_status: RunStatus) -> RunManifest:
        with self._connection:
            self._connection.execute("BEGIN IMMEDIATE")
            row = self._connection.execute(
                "SELECT status FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"run_id {run_id} not found")
            current = RunStatus(row["status"])
            if to_status not in LEGAL_TRANSITIONS[current]:
                raise ValueError("invalid run transition")
            self._connection.execute(
                "UPDATE runs SET status = ? WHERE run_id = ?", (to_status.value, run_id)
            )
            self._append_transition(run_id, current, to_status)
        return self.get(run_id)

    def get(self, run_id: str) -> RunManifest:
        row = self._connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"run_id {run_id} not found")
        return _row_to_manifest(row)

    def list_runs(self) -> list[RunManifest]:
        rows = self._connection.execute("SELECT * FROM runs ORDER BY created_at, run_id").fetchall()
        return [_row_to_manifest(row) for row in rows]

    def transition_history(self, run_id: str) -> list[dict[str, str | None]]:
        rows = self._connection.execute(
            "SELECT from_status, to_status, transition_at FROM run_transitions "
            "WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def _append_transition(
        self, run_id: str, from_status: RunStatus | None, to_status: RunStatus
    ) -> None:
        self._connection.execute(
            "INSERT INTO run_transitions "
            "(run_id, from_status, to_status, transition_at) VALUES (?, ?, ?, ?)",
            (
                run_id,
                from_status.value if from_status is not None else None,
                to_status.value,
                datetime.now(UTC).isoformat(),
            ),
        )


def _row_to_manifest(row: sqlite3.Row) -> RunManifest:
    holdout_json = row["locked_holdout_json"]
    return RunManifest(
        run_id=row["run_id"],
        identity_sha256=row["identity_sha256"],
        created_at=datetime.fromisoformat(row["created_at"]),
        strategy_name=row["strategy_name"],
        code_sha=row["code_sha"],
        dataset_snapshot_ids=tuple(json.loads(row["dataset_snapshot_ids_json"])),
        config_json=row["config_json"],
        seed=row["seed"],
        locked_holdout=(LockedHoldout.model_validate_json(holdout_json) if holdout_json else None),
        parent_run_id=row["parent_run_id"],
        status=RunStatus(row["status"]),
    )
