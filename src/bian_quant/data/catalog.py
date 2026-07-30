import sqlite3
from dataclasses import dataclass
from pathlib import Path

from bian_quant.data.contracts import DatasetManifest


@dataclass(frozen=True)
class CatalogEntry:
    """Resolved immutable catalog record."""

    manifest: DatasetManifest
    path: Path


class DatasetCatalog:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    snapshot_id TEXT PRIMARY KEY,
                    layer TEXT NOT NULL,
                    name TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    path TEXT NOT NULL,
                    manifest_json TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def register(self, manifest: DatasetManifest, *, path: Path) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT path, manifest_json FROM datasets WHERE snapshot_id = ?",
                (manifest.snapshot_id,),
            ).fetchone()
            manifest_json = manifest.model_dump_json()
            registered_path = str(path.resolve())
            if row is not None:
                if row != (registered_path, manifest_json):
                    raise ValueError("snapshot_id already exists with different evidence")
                return
            connection.execute(
                "INSERT INTO datasets VALUES (?, ?, ?, ?, ?, ?)",
                (
                    manifest.snapshot_id,
                    manifest.layer.value,
                    manifest.name,
                    manifest.content_sha256,
                    registered_path,
                    manifest_json,
                ),
            )

    def get(self, snapshot_id: str) -> CatalogEntry:
        """Resolve one snapshot and validate its stored manifest."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT path, manifest_json FROM datasets WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"snapshot_id {snapshot_id} not found")
        return CatalogEntry(
            manifest=DatasetManifest.model_validate_json(row[1]),
            path=Path(row[0]),
        )

    def find_by_name(self, name: str) -> tuple[CatalogEntry, ...]:
        """Return all snapshots with *name* in deterministic registration order."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT path, manifest_json FROM datasets WHERE name = ? ORDER BY rowid",
                (name,),
            ).fetchall()
        return tuple(
            CatalogEntry(
                manifest=DatasetManifest.model_validate_json(manifest_json),
                path=Path(path),
            )
            for path, manifest_json in rows
        )
