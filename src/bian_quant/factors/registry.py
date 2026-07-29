"""SQLite-backed factor registry with append-only lifecycle transitions."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from bian_quant.factors.spec import FactorSpec, FactorState

LEGAL: dict[FactorState, set[FactorState]] = {
    FactorState.RESEARCHING: {FactorState.OBSERVED, FactorState.RETIRED},
    FactorState.OBSERVED: {FactorState.CANDIDATE, FactorState.RETIRED},
    FactorState.CANDIDATE: {FactorState.APPROVED, FactorState.OBSERVED, FactorState.RETIRED},
    FactorState.APPROVED: {FactorState.OBSERVED, FactorState.RETIRED},
    FactorState.RETIRED: {FactorState.RESEARCHING},
}


class FactorRegistry:
    """Append-only registry of factor specs and lifecycle transitions."""

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = Path(db_path)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_tables()

    def _init_tables(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS factor_specs (
                factor_id   TEXT NOT NULL,
                version     TEXT NOT NULL,
                spec_json   TEXT NOT NULL,
                code_sha    TEXT NOT NULL,
                created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                PRIMARY KEY (factor_id, version)
            );

            CREATE TABLE IF NOT EXISTS factor_transitions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                factor_id       TEXT NOT NULL,
                version         TEXT NOT NULL,
                from_state      TEXT,
                to_state        TEXT NOT NULL,
                evidence_run_id TEXT,
                restart_reason  TEXT,
                restart_evidence_run_id TEXT,
                created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                FOREIGN KEY (factor_id, version) REFERENCES factor_specs(factor_id, version)
            );
            """
        )
        self._conn.commit()

    def register(self, spec: FactorSpec, *, code_sha: str) -> None:
        """Register a new factor spec.  Re-registration is rejected."""
        cur = self._conn.execute(
            "SELECT 1 FROM factor_specs WHERE factor_id=? AND version=?",
            (spec.factor_id, spec.version),
        )
        if cur.fetchone() is not None:
            raise ValueError(f"factor {spec.factor_id}@{spec.version} already registered")
        self._conn.execute(
            "INSERT INTO factor_specs (factor_id, version, spec_json, code_sha)"
            " VALUES (?, ?, ?, ?)",
            (spec.factor_id, spec.version, spec.model_dump_json(), code_sha),
        )
        self._conn.execute(
            "INSERT INTO factor_transitions (factor_id, version, from_state, to_state)"
            " VALUES (?, ?, NULL, ?)",
            (spec.factor_id, spec.version, FactorState.RESEARCHING.value),
        )
        self._conn.commit()

    def get(self, factor_id: str, version: str) -> FactorSpec:
        cur = self._conn.execute(
            "SELECT spec_json FROM factor_specs WHERE factor_id=? AND version=?",
            (factor_id, version),
        )
        row = cur.fetchone()
        if row is None:
            raise KeyError(f"factor {factor_id}@{version} not found")
        return FactorSpec.model_validate_json(row[0])

    def state(self, factor_id: str, version: str) -> FactorState:
        cur = self._conn.execute(
            "SELECT to_state FROM factor_transitions WHERE factor_id=? AND"
            " version=? ORDER BY id DESC LIMIT 1",
            (factor_id, version),
        )
        row = cur.fetchone()
        if row is None:
            raise KeyError(f"factor {factor_id}@{version} not found")
        return FactorState(row[0])

    def transition(
        self,
        factor_id: str,
        version: str,
        to_state: FactorState,
        *,
        evidence_run_id: str | None = None,
        restart_reason: str | None = None,
        restart_evidence_run_id: str | None = None,
    ) -> None:
        """Transition a factor to a new lifecycle state.

        All transitions except initial registration require ``evidence_run_id``.
        ``RETIRED → RESEARCHING`` additionally requires ``restart_reason`` and
        ``restart_evidence_run_id``.
        """
        current = self.state(factor_id, version)

        if to_state not in LEGAL.get(current, set()):
            raise ValueError(f"illegal transition: {current.value} -> {to_state.value}")

        if (
            current == FactorState.RETIRED
            and to_state == FactorState.RESEARCHING
            and (not restart_reason or not restart_evidence_run_id)
        ):
            raise ValueError(
                "RETIRED -> RESEARCHING requires restart evidence "
                "(restart_reason and restart_evidence_run_id)"
            )

        if evidence_run_id is None:
            raise ValueError("evidence_run_id is required for transitions")

        self._conn.execute(
            """INSERT INTO factor_transitions
               (factor_id, version, from_state, to_state, evidence_run_id,
                restart_reason, restart_evidence_run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                factor_id,
                version,
                current.value,
                to_state.value,
                evidence_run_id,
                restart_reason,
                restart_evidence_run_id,
            ),
        )
        self._conn.commit()

    def history(self, factor_id: str, version: str) -> list[dict[str, str | None]]:
        cur = self._conn.execute(
            """SELECT from_state, to_state, evidence_run_id, restart_reason,
                      restart_evidence_run_id, created_at
               FROM factor_transitions
               WHERE factor_id=? AND version=? ORDER BY id ASC""",
            (factor_id, version),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> FactorRegistry:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
