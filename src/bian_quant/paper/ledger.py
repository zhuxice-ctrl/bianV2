"""Append-only SQLite ledger for forward paper-trading state.

Decisions, captures, and positions are write-once: ``UPDATE`` and ``DELETE``
triggers reject every mutation.  The ledger also answers continuity questions
(missing four-hour slots) and the 30-day human-review readiness gate.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from bian_quant.paper.models import (
    MarketDataCapture,
    PaperDecision,
    PaperPortfolioState,
    PaperPosition,
    PaperRunConfig,
)

_INTERVAL = timedelta(hours=4)


class PaperLedger:
    """Append-only state store for one paper run (or many, keyed by run_id)."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> PaperLedger:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- schema ------------------------------------------------------------

    def _create_schema(self) -> None:
        conn = self._conn
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS paper_runs (
                run_id      TEXT PRIMARY KEY,
                config_json TEXT NOT NULL,
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS paper_decisions (
                run_id         TEXT NOT NULL,
                scheduled_time TEXT NOT NULL,
                decision_json  TEXT NOT NULL,
                status         TEXT NOT NULL,
                reason_code    TEXT NOT NULL,
                timing_violation INTEGER NOT NULL DEFAULT 0,
                risk_breach    INTEGER NOT NULL DEFAULT 0,
                equity_after   TEXT NOT NULL,
                PRIMARY KEY (run_id, scheduled_time)
            );

            CREATE TABLE IF NOT EXISTS paper_captures (
                run_id         TEXT NOT NULL,
                scheduled_time TEXT NOT NULL,
                endpoint       TEXT NOT NULL,
                body_sha256    TEXT NOT NULL,
                capture_json   TEXT NOT NULL,
                seq            INTEGER NOT NULL,
                PRIMARY KEY (run_id, scheduled_time, seq)
            );

            CREATE TABLE IF NOT EXISTS paper_positions (
                run_id         TEXT NOT NULL,
                scheduled_time TEXT NOT NULL,
                asset          TEXT NOT NULL,
                position_json  TEXT NOT NULL,
                PRIMARY KEY (run_id, scheduled_time, asset)
            );
            """
        )
        for table in ("paper_decisions", "paper_captures", "paper_positions"):
            conn.execute(
                f"CREATE TRIGGER IF NOT EXISTS {table}_block_update "
                f"BEFORE UPDATE ON {table} BEGIN "
                f"SELECT RAISE(ABORT, 'APPEND_ONLY:{table}'); END"
            )
            conn.execute(
                f"CREATE TRIGGER IF NOT EXISTS {table}_block_delete "
                f"BEFORE DELETE ON {table} BEGIN "
                f"SELECT RAISE(ABORT, 'APPEND_ONLY:{table}'); END"
            )
        conn.commit()

    # -- writes ------------------------------------------------------------

    def register_run(self, config: PaperRunConfig) -> None:
        """Record the immutable run configuration (idempotent on run_id)."""
        self._conn.execute(
            "INSERT OR IGNORE INTO paper_runs(run_id, config_json, created_at) VALUES (?, ?, ?)",
            (
                config.run_id,
                config.model_dump_json(),
                datetime.now(UTC).isoformat(),
            ),
        )
        self._conn.commit()

    def record(
        self,
        decision: PaperDecision,
        captures: Iterable[MarketDataCapture] = (),
        positions: Iterable[PaperPosition] = (),
    ) -> None:
        """Append one decision (and its captures/positions) write-once."""
        self._record_decision(decision)
        for seq, capture in enumerate(captures):
            self._record_capture(decision.run_id, decision.scheduled_time, seq, capture)
        for position in positions:
            self._record_position(decision.run_id, decision.scheduled_time, position)
        self._conn.commit()

    # alias matching the plan's vocabulary
    record_cycle = record

    def _record_decision(self, decision: PaperDecision) -> None:
        self._conn.execute(
            """
            INSERT INTO paper_decisions
                (run_id, scheduled_time, decision_json, status, reason_code,
                 timing_violation, risk_breach, equity_after)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision.run_id,
                _iso(decision.scheduled_time),
                decision.model_dump_json(),
                decision.status.value,
                decision.reason_code,
                int(decision.timing_violation),
                int(decision.risk_breach),
                str(decision.equity_after),
            ),
        )

    def _record_capture(
        self,
        run_id: str,
        scheduled_time: datetime,
        seq: int,
        capture: MarketDataCapture,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO paper_captures
                (run_id, scheduled_time, endpoint, body_sha256, capture_json, seq)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                _iso(scheduled_time),
                capture.endpoint,
                capture.body_sha256,
                capture.model_dump_json(),
                seq,
            ),
        )

    def _record_position(
        self, run_id: str, scheduled_time: datetime, position: PaperPosition
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO paper_positions
                (run_id, scheduled_time, asset, position_json)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, _iso(scheduled_time), position.asset, position.model_dump_json()),
        )

    # -- reads -------------------------------------------------------------

    def load_state(self, config: PaperRunConfig) -> PaperPortfolioState:
        """Reconstruct the current portfolio state for *config.run_id*."""
        rows = self._conn.execute(
            """
            SELECT scheduled_time, equity_after, risk_breach, timing_violation
              FROM paper_decisions
             WHERE run_id = ?
             ORDER BY scheduled_time ASC
            """,
            (config.run_id,),
        ).fetchall()
        if not rows:
            return PaperPortfolioState(
                run_id=config.run_id,
                equity=config.initial_equity_usdt,
                high_water_mark=config.initial_equity_usdt,
            )

        equity = Decimal(str(rows[-1][1]))
        high_water_mark = max(
            (Decimal(str(r[1])) for r in rows), default=config.initial_equity_usdt
        )
        last_time = _parse_iso(rows[-1][0])

        # Daily loss aggregated over the last UTC day.
        day_start = last_time.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        day_rows = [r for r in rows if _parse_iso(r[0]) >= day_start]
        # Equity at day start = equity_after of prior slot, or initial equity.
        if day_rows:
            idx = rows.index(day_rows[0])
            equity_at_day_start = (
                Decimal(str(rows[idx - 1][1])) if idx > 0 else config.initial_equity_usdt
            )
        else:
            equity_at_day_start = config.initial_equity_usdt
        daily_loss = max(Decimal("0"), equity_at_day_start - equity)

        # Latest open positions.
        position_rows = self._conn.execute(
            """
            SELECT position_json FROM paper_positions
             WHERE run_id = ? AND scheduled_time = ?
            """,
            (config.run_id, _iso(last_time)),
        ).fetchall()
        positions = tuple(PaperPosition.model_validate_json(row[0]) for row in position_rows)

        # Pause window.
        pause_until: datetime | None = None
        next_midnight = _next_utc_midnight(last_time)
        if daily_loss >= config.daily_loss_pause_usdt:
            pause_until = next_midnight
        if (high_water_mark - equity) >= config.drawdown_pause_usdt:
            pause_until = datetime.max.replace(tzinfo=UTC)

        return PaperPortfolioState(
            run_id=config.run_id,
            equity=equity,
            high_water_mark=high_water_mark,
            positions=positions,
            daily_loss=daily_loss,
            daily_reset_time=next_midnight,
            pause_until=pause_until,
        )

    def missing_slots(
        self,
        start: datetime,
        end: datetime,
        *,
        now: datetime | None = None,
        run_id: str | None = None,
    ) -> tuple[datetime, ...]:
        """Return overdue four-hour slots with no recorded decision.

        A slot *t* is checked when ``start < t < end``; when *now* is given a
        slot is only reported once ``t + grace`` has passed (the grace window
        lets an in-flight cycle finish before it is flagged missing).
        """
        frontier = now or end
        recorded: set[str] = set()
        if run_id is not None:
            recorded = {
                row[0]
                for row in self._conn.execute(
                    "SELECT scheduled_time FROM paper_decisions WHERE run_id = ?",
                    (run_id,),
                )
            }
        missing: list[datetime] = []
        slot = start + _INTERVAL
        while slot < end:
            overdue = slot + _GRACE <= frontier
            if overdue and _iso(slot) not in recorded:
                missing.append(slot)
            slot += _INTERVAL
        return tuple(missing)

    def review_readiness(self, config: PaperRunConfig, *, now: datetime) -> bool:
        """True only after 30 clean calendar days with no violation or breach."""
        rows = self._conn.execute(
            """
            SELECT scheduled_time, timing_violation, risk_breach
              FROM paper_decisions
             WHERE run_id = ?
             ORDER BY scheduled_time ASC
            """,
            (config.run_id,),
        ).fetchall()
        if not rows:
            return False
        first_time = _parse_iso(rows[0][0])
        if (now - first_time) < timedelta(days=config.minimum_calendar_days):
            return False
        for _scheduled, timing_violation, risk_breach in rows:
            if timing_violation or risk_breach:
                return False
        return not self.missing_slots(first_time, now, now=now, run_id=config.run_id)

    def decision_count(self, run_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM paper_decisions WHERE run_id = ?", (run_id,)
        ).fetchone()
        return int(row[0]) if row else 0


_GRACE = timedelta(minutes=5)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _next_utc_midnight(now: datetime) -> datetime:
    midnight = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    if midnight <= now.astimezone(UTC):
        midnight += timedelta(days=1)
    return midnight
