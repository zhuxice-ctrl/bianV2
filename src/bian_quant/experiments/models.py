import hashlib
import json
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


class LockedHoldout(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: datetime
    end: datetime

    @model_validator(mode="after")
    def validate_boundary(self) -> "LockedHoldout":
        for timestamp in (self.start, self.end):
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("locked holdout timestamps must be timezone-aware")
        if self.start >= self.end:
            raise ValueError("locked holdout start must precede end")
        return self


class RunManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    identity_sha256: str
    created_at: datetime
    strategy_name: str = Field(min_length=1)
    code_sha: str = Field(min_length=1)
    dataset_snapshot_ids: tuple[str, ...]
    config_json: str
    seed: int
    locked_holdout: LockedHoldout | None = None
    parent_run_id: str | None = None
    status: RunStatus = RunStatus.QUEUED

    @classmethod
    def create(
        cls,
        *,
        strategy_name: str,
        code_sha: str,
        dataset_snapshot_ids: list[str],
        config: dict[str, Any],
        seed: int,
        locked_holdout: LockedHoldout | None = None,
        parent_run_id: str | None = None,
    ) -> "RunManifest":
        if not dataset_snapshot_ids:
            raise ValueError("at least one dataset snapshot is required")
        config_json = json.dumps(config, sort_keys=True, separators=(",", ":"), default=str)
        identity_payload = json.dumps(
            {
                "strategy_name": strategy_name,
                "code_sha": code_sha,
                "dataset_snapshot_ids": sorted(dataset_snapshot_ids),
                "config": json.loads(config_json),
                "seed": seed,
                "locked_holdout": (
                    locked_holdout.model_dump(mode="json") if locked_holdout is not None else None
                ),
                "parent_run_id": parent_run_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return cls(
            run_id=str(uuid.uuid4()),
            identity_sha256=hashlib.sha256(identity_payload.encode("utf-8")).hexdigest(),
            created_at=datetime.now(UTC),
            strategy_name=strategy_name,
            code_sha=code_sha,
            dataset_snapshot_ids=tuple(dataset_snapshot_ids),
            config_json=config_json,
            seed=seed,
            locked_holdout=locked_holdout,
            parent_run_id=parent_run_id,
        )

    @model_validator(mode="after")
    def validate_identity(self) -> "RunManifest":
        try:
            uuid.UUID(self.run_id)
        except ValueError as error:
            raise ValueError("run_id must be a UUID") from error
        if len(self.identity_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.identity_sha256
        ):
            raise ValueError("identity_sha256 must be lowercase SHA-256")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return self
