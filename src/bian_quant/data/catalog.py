import sqlite3
from pathlib import Path

from bian_quant.data.contracts import DatasetManifest


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
