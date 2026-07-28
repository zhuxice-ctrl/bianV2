from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectPaths:
    var: Path
    raw: Path
    canonical: Path
    research: Path
    artifacts: Path
    logs: Path
    registry: Path

    @classmethod
    def from_var_dir(cls, var: Path) -> "ProjectPaths":
        return cls(
            var=var,
            raw=var / "lake" / "raw",
            canonical=var / "lake" / "canonical",
            research=var / "lake" / "research",
            artifacts=var / "artifacts",
            logs=var / "logs",
            registry=var / "registry.sqlite",
        )

    def create(self) -> None:
        for path in (self.raw, self.canonical, self.research, self.artifacts, self.logs):
            path.mkdir(parents=True, exist_ok=True)
