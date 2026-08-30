"""Pure read-path cutover/rollback selector for the PostgreSQL shadow.

Persistence and audit orchestration deliberately live in
``mova_fpl.ops.postgres_cutover`` so this infrastructure layer never imports
the operational layer.
"""

from __future__ import annotations

from mova_fpl.postgres.importer import TABLES
from mova_fpl.postgres.read_repository import PostgresReadRepository, SQLiteReadRepository


SCHEMA = "mova-postgres-read-cutover-drill-v1"
JOB_TYPE = "postgres_read_cutover_drill"
CRITICAL_TABLES = {
    ("ops", "runtime_controls"),
    ("ops", "gameweek_cycles"),
    ("ops", "team_state_snapshots"),
    ("ops", "research_runs"),
    ("ops", "decision_envelopes"),
    ("ops", "execution_plans"),
    ("ops", "browser_rehearsals"),
}


class ReadCutoverSession:
    """Finite selector used only inside the drill; it cannot mutate runtime config."""

    def __init__(self, sqlite_repo: SQLiteReadRepository,
                 postgres_repo: PostgresReadRepository):
        self.sqlite = sqlite_repo
        self.postgres = postgres_repo
        self.active_backend = "sqlite"
        self.sequence = ["sqlite_baseline"]

    def exercise(self, specs=tuple(
        item for item in TABLES
        if (item.source_db, item.source_table) in CRITICAL_TABLES
    )) -> dict:
        baseline = {spec.target_table: self.sqlite.table(spec) for spec in specs}
        checks: list[dict] = []
        candidate_error: Exception | None = None
        try:
            self.active_backend = "postgres"
            self.sequence.append("postgres_candidate")
            for spec in specs:
                source = baseline[spec.target_table]
                target = self.postgres.table(spec, source.columns)
                checks.append({
                    "source": f"{spec.source_db}.{spec.source_table}",
                    "target": spec.target_table,
                    "rows": source.row_count,
                    "sqlite_sha256": source.content_sha256,
                    "postgres_sha256": target.content_sha256,
                    "candidate_status": "pass" if (
                        source.row_count == target.row_count
                        and source.content_sha256 == target.content_sha256
                    ) else "fail",
                })
        except Exception as exc:  # rollback must run even when candidate read fails
            candidate_error = exc
        finally:
            self.active_backend = "sqlite"
            self.sequence.append("sqlite_rollback")
            rollback = {spec.target_table: self.sqlite.table(spec) for spec in specs}
            by_target = {item["target"]: item for item in checks}
            for spec in specs:
                source = baseline[spec.target_table]
                restored = rollback[spec.target_table]
                item = by_target.get(spec.target_table)
                if item is None:
                    item = {
                        "source": f"{spec.source_db}.{spec.source_table}",
                        "target": spec.target_table,
                        "rows": source.row_count,
                        "sqlite_sha256": source.content_sha256,
                        "postgres_sha256": None,
                        "candidate_status": "error",
                    }
                    checks.append(item)
                item["rollback_sha256"] = restored.content_sha256
                item["rollback_status"] = "pass" if (
                    source.row_count == restored.row_count
                    and source.content_sha256 == restored.content_sha256
                ) else "fail"
        passed = (
            candidate_error is None
            and self.active_backend == "sqlite"
            and len(checks) == len(specs)
            and all(item["candidate_status"] == "pass" for item in checks)
            and all(item["rollback_status"] == "pass" for item in checks)
        )
        return {
            "status": "pass" if passed else "fail",
            "sequence": self.sequence,
            "writer_before": "sqlite",
            "candidate_reader": "postgres",
            "writer_after": self.active_backend,
            "runtime_writer_mutated": False,
            "rollback_verified": all(
                item["rollback_status"] == "pass" for item in checks
            ),
            "candidate_error": type(candidate_error).__name__ if candidate_error else None,
            "checks": sorted(checks, key=lambda item: item["target"]),
        }
