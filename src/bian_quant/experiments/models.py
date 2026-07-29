"""Models for the append-only experiment registry."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunManifest(BaseModel):
    """Immutable manifest describing a single experiment run.

    The ``run_id`` is deterministically derived from the run's identity
    fields via SHA-256, so two runs with identical configuration and
    code hash are the same run.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    status: RunStatus = RunStatus.PENDING
    created_at: datetime
    strategy_name: str
    config_json: str
    code_sha256: str
    data_snapshot_id: str
    parent_run_id: str | None = None
    notes: str = ""

    @model_validator(mode="after")
    def validate_run_id(self) -> RunManifest:
        if len(self.run_id) != 64 or any(
            c not in "0123456789abcdef" for c in self.run_id
        ):
            raise ValueError("run_id must be 64 lowercase hexadecimal characters")
        return self

    @classmethod
    def create(
        cls,
        *,
        strategy_name: str,
        config: dict[str, object],
        code_sha256: str,
        data_snapshot_id: str,
        parent_run_id: str | None = None,
        notes: str = "",
    ) -> RunManifest:
        """Create a manifest with a deterministic SHA-256 ``run_id``."""
        config_json = json.dumps(config, sort_keys=True, default=str)
        now = datetime.now(timezone.utc)

        identity_parts = [
            strategy_name,
            config_json,
            code_sha256,
            data_snapshot_id,
        ]
        if parent_run_id is not None:
            identity_parts.append(parent_run_id)

        identity_str = "\n".join(identity_parts)
        run_id = hashlib.sha256(identity_str.encode("utf-8")).hexdigest()

        return cls(
            run_id=run_id,
            status=RunStatus.PENDING,
            created_at=now,
            strategy_name=strategy_name,
            config_json=config_json,
            code_sha256=code_sha256,
            data_snapshot_id=data_snapshot_id,
            parent_run_id=parent_run_id,
            notes=notes,
        )
