"""Paper-cycle artifact publishing and 30-day review summaries.

Cycle artifacts live in exclusive directories under
``{artifact_root}/{run_id}/{scheduled_time}`` and are written once via the
shared :class:`ArtifactWriter`.  The review summary reports every missing
four-hour slot and never labels a run ready while any timing violation or risk
breach is on record.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import cast

from bian_quant.paper.ledger import PaperLedger
from bian_quant.paper.models import PaperDecision, PaperRunConfig
from bian_quant.reporting.artifacts import ArtifactWriter

#: The seven immutable files written for every paper cycle.
CYCLE_FILES = (
    "decision.json",
    "captures.json",
    "orders.json",
    "fills.json",
    "equity.json",
    "risk.json",
    "summary.md",
)


def write_cycle_artifacts(artifact_root: Path | str, decision: PaperDecision) -> Path:
    """Publish the seven cycle artifacts for *decision* and return the dir."""
    writer = ArtifactWriter(artifact_root)
    scheduled = decision.scheduled_time.astimezone().isoformat().replace(":", "")
    run_dir = writer.create_run(f"{decision.run_id}/{scheduled}")

    writer.write_json(run_dir, "decision.json", _serializable(decision.model_dump()))
    writer.write_json(
        run_dir,
        "captures.json",
        [_serializable(c.model_dump()) for c in decision.captures],
    )
    writer.write_json(run_dir, "orders.json", _order_payload(decision))
    writer.write_json(run_dir, "fills.json", _fills_payload(decision))
    writer.write_json(
        run_dir,
        "equity.json",
        {
            "equity_before": str(decision.equity_before),
            "equity_after": str(decision.equity_after),
        },
    )
    writer.write_json(run_dir, "risk.json", _risk_payload(decision))
    writer.write_text(run_dir, "summary.md", _cycle_summary(decision))
    return run_dir.path


def build_review_summary(
    ledger: PaperLedger, config: PaperRunConfig, *, now: datetime
) -> dict[str, object]:
    """Build the 30-day operator review summary for *config.run_id*."""
    state = ledger.load_state(config)
    first_row = ledger._conn.execute(  # noqa: SLF001
        "SELECT MIN(scheduled_time) FROM paper_decisions WHERE run_id = ?",
        (config.run_id,),
    ).fetchone()
    first_time = datetime.fromisoformat(first_row[0]) if first_row and first_row[0] else None
    completed_days: float = 0.0
    if first_time is not None:
        completed_days = round((now - first_time).total_seconds() / 86400, 1)
    missing = (
        ledger.missing_slots(first_time, now, now=now, run_id=config.run_id)
        if first_time is not None
        else ()
    )
    ready = ledger.review_readiness(config, now=now)
    return {
        "run_id": config.run_id,
        "completed_days": completed_days,
        "missing_slots": [_iso(slot) for slot in missing],
        "current_equity": str(state.equity),
        "high_water_mark": str(state.high_water_mark),
        "daily_loss": str(state.daily_loss),
        "pause_until": _iso(state.pause_until) if state.pause_until else None,
        "review_ready": ready,
    }


def render_review_summary(summary: dict[str, object]) -> str:
    """Render a review summary dict as operator-facing markdown."""
    missing_slots = cast(list[str], summary["missing_slots"])
    lines = [
        f"# Paper status — {summary['run_id']}",
        "",
        f"- Completed days: {summary['completed_days']}",
        f"- Current equity: {summary['current_equity']} USDT",
        f"- High-water mark: {summary['high_water_mark']} USDT",
        f"- Daily loss: {summary['daily_loss']} USDT",
        f"- Pause until: {summary['pause_until'] or '—'}",
        f"- Missing slots: {len(missing_slots)}",
    ]
    for slot in missing_slots:
        lines.append(f"  - {slot}")
    lines.append(f"- Review ready: {'YES' if summary['review_ready'] else 'NO'}")
    return "\n".join(lines) + "\n"


# -- helpers -----------------------------------------------------------------


def _serializable(value: object) -> object:
    """Convert datetimes/Decimals/Paths to JSON-safe primitives."""
    if isinstance(value, dict):
        return {k: _serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serializable(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    from decimal import Decimal

    if isinstance(value, Decimal):
        return str(value)
    from pathlib import Path

    if isinstance(value, Path):
        return str(value)
    return value


def _order_payload(decision: PaperDecision) -> dict[str, object]:
    if decision.asset is None:
        return {"orders": []}
    return {
        "orders": [
            {
                "asset": decision.asset,
                "side": decision.side,
                "quantity": str(decision.quantity),
                "entry": str(decision.entry),
                "stop": str(decision.stop),
                "target": str(decision.target),
                "notional": str(decision.notional),
            }
        ]
    }


def _fills_payload(decision: PaperDecision) -> dict[str, object]:
    return {"fills": [], "note": "paper cycle records no exchange fills"}


def _risk_payload(decision: PaperDecision) -> dict[str, object]:
    return {
        "stop_risk": str(decision.stop_risk) if decision.stop_risk is not None else None,
        "notional": str(decision.notional) if decision.notional is not None else None,
        "risk_breach": decision.risk_breach,
        "timing_violation": decision.timing_violation,
        "reason_code": decision.reason_code,
    }


def _cycle_summary(decision: PaperDecision) -> str:
    lines = [
        f"# Cycle {decision.scheduled_time.isoformat()}",
        "",
        f"- Status: {decision.status.value}",
        f"- Reason: {decision.reason_code}",
        f"- Equity: {decision.equity_before} -> {decision.equity_after}",
    ]
    if decision.asset:
        lines.append(
            f"- Order: {decision.side} {decision.quantity} {decision.asset} "
            f"@ {decision.entry} (stop {decision.stop})"
        )
    return "\n".join(lines) + "\n"


def _iso(value: datetime) -> str:
    return value.isoformat()
