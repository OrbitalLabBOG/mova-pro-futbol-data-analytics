from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from mova_fpl.ops.cli import main, parser
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB
from mova_fpl.ops.orchestration import (
    build_workflow,
    evaluate_workflow,
    orchestration_drill,
    prometheus,
)


NOW = datetime(2026, 9, 4, 16, 0, tzinfo=timezone.utc)


def _base() -> dict:
    return {
        "cycle": {"cycle_id": "2026-27-gw03", "gw": 3,
                  "deadline_at": "2026-09-04T17:30:00Z"},
        "source": {"snapshot_id": "snapshot_1", "quality_status": "valid"},
        "team_state": {"team_state_id": "team_1", "quality_status": "valid"},
        "manifest": {"manifest_id": "manifest_1"},
        "research": {"research_run_id": "research_1", "status": "imported"},
        "envelope": {"envelope_id": "envelope_1", "status": "blocked"},
        "deliberation": {"deliberation_id": "deliberation_1", "status": "blocked"},
        "preflight": {"plan_id": "plan_1", "status": "blocked"},
        "execution": {}, "settlement": {}, "review": {},
        "learning": {"lesson_count": 0},
    }


def test_workflow_explains_fail_closed_agent_chain_without_granting_authority():
    report = evaluate_workflow(_base(), now=NOW)

    assert report["schema"] == "mova-orchestration-status-v1"
    assert report["verdict"] == "safe_to_wait"
    assert report["violations"] == []
    assert report["runtime_mutated"] is False
    assert report["timing_policy_version"] == "workflow-timing-1.0.0"
    stages = {row["name"]: row for row in report["stages"]}
    assert stages["research"]["status"] == "complete"
    assert stages["propose_validate"]["outcome"] == "blocked"
    assert stages["deliberate"]["status"] == "complete"
    assert stages["execute_verify"]["status"] == "skipped_policy"
    assert stages["settle"]["status"] == "not_due"
    assert stages["research"]["timing"]["target_at"] == "2026-09-04T11:30:00+00:00"
    assert stages["preflight"]["timing"]["recovery_until"] == "2026-09-04T16:30:00+00:00"
    assert stages["execute_verify"]["timing"]["hard_stop_at"] == "2026-09-04T17:15:00+00:00"
    assert stages["settle"]["timing"]["basis"] == "official_finished_data_checked"
    assert stages["settle"]["timing"]["hard_stop_at"] is None
    assert set(report["roles"]["llm"]) == {"researcher", "strategist", "critic"}


def test_stale_source_and_private_state_cannot_complete_workflow_context():
    observed = _base()
    observed["source"]["captured_at"] = "2026-09-04T13:00:00Z"
    observed["team_state"]["observed_at"] = "2026-09-04T15:00:00Z"
    observed["source_max_age_seconds"] = 3600
    observed["team_state_max_age_seconds"] = 900

    report = evaluate_workflow(observed, now=NOW)
    stages = {row["name"]: row for row in report["stages"]}
    assert stages["observe"]["status"] == "blocked"
    assert stages["observe"]["outcome"] == "stale"
    assert stages["contextualize"]["status"] == "pending"
    assert stages["contextualize"]["outcome"] == "stale_team_state"
    assert report["freshness"]["team_state_age_seconds"] == 3600
    assert report["verdict"] == "blocked"


def test_workflow_detects_illegal_downstream_execution_and_review():
    observed = _base()
    observed.update(
        preflight={},
        execution={"execution_id": "execution_orphan", "status": "verified"},
        review={"review_id": "review_orphan"},
        learning={"lesson_count": 1},
    )
    report = evaluate_workflow(observed, now=NOW)

    assert report["verdict"] == "blocked"
    assert {row["code"] for row in report["violations"]} == {
        "EXECUTION_WITHOUT_AUTHORIZED_PLAN", "REVIEW_WITHOUT_SETTLEMENT",
    }


def test_verified_attempt_for_another_plan_cannot_complete_current_plan():
    observed = _base()
    observed["preflight"] = {"plan_id": "plan_current", "status": "authorized"}
    observed["execution"] = {
        "execution_id": "execution_old", "plan_id": "plan_old", "status": "verified",
    }

    report = evaluate_workflow(observed, now=NOW)

    assert report["verdict"] == "blocked"
    assert {row["code"] for row in report["violations"]} == {
        "EXECUTION_PLAN_MISMATCH",
    }
    execution = next(row for row in report["stages"] if row["name"] == "execute_verify")
    assert execution["status"] == "blocked"
    assert execution["outcome"] == "verified"


def test_workflow_reads_attempt_only_for_displayed_plan(tmp_path: Path):
    config = RuntimeConfig(ops_db=tmp_path / "ops.db", artifact_root=tmp_path / "artifacts")
    path = tmp_path / "ledger.db"
    with sqlite3.connect(path) as con:
        con.executescript("""
            CREATE TABLE source_snapshots (cycle_id TEXT, snapshot_id TEXT,
                quality_status TEXT, captured_at TEXT);
            CREATE TABLE team_state_snapshots (cycle_id TEXT, team_state_id TEXT,
                quality_status TEXT, observed_at TEXT);
            CREATE TABLE cycle_manifests (cycle_id TEXT, manifest_id TEXT,
                revision INTEGER, created_at TEXT);
            CREATE TABLE research_runs (cycle_id TEXT, research_run_id TEXT,
                status TEXT, provider TEXT, finished_at TEXT, queued_at TEXT);
            CREATE TABLE decision_envelopes (cycle_id TEXT, envelope_id TEXT,
                status TEXT, created_at TEXT);
            CREATE TABLE execution_plans (cycle_id TEXT, plan_id TEXT,
                status TEXT, risk_class TEXT, created_at TEXT);
            CREATE TABLE execution_attempts (plan_id TEXT, execution_id TEXT,
                status TEXT, created_at TEXT);
            CREATE TABLE gameweek_settlements (cycle_id TEXT, settlement_id TEXT,
                settled_at TEXT);
            CREATE TABLE gameweek_reviews (settlement_id TEXT, review_id TEXT,
                created_at TEXT);
        """)
        con.execute("INSERT INTO execution_plans VALUES (?,?,?,?,?)",
                    ("cycle_1", "plan_old", "authorized", "R2", "2026-09-04T10:00:00Z"))
        con.execute("INSERT INTO execution_plans VALUES (?,?,?,?,?)",
                    ("cycle_1", "plan_current", "authorized", "R2", "2026-09-04T11:00:00Z"))
        con.execute("INSERT INTO execution_attempts VALUES (?,?,?,?)",
                    ("plan_old", "attempt_old", "verified", "2026-09-04T12:00:00Z"))

    class ReadOnlyLedger:
        def status(self):
            return {"cycle": {"cycle_id": "cycle_1", "gw": 3,
                              "deadline_at": "2026-09-04T17:30:00Z"}}

        @contextmanager
        def connect(self, readonly=True):
            assert readonly
            with sqlite3.connect(path) as con:
                con.row_factory = sqlite3.Row
                yield con

        def deliberation_status(self, cycle_id):
            return {"latest": {}}

        def cost_report(self, policy, *, season, gw):
            return {"status": "within_budget",
                    "orphaned_reservations": {"status": "none"}}

    report = build_workflow(config, ReadOnlyLedger(), now=NOW)
    execution = next(row for row in report["stages"] if row["name"] == "execute_verify")
    assert execution["status"] == "pending"
    assert execution["subject_id"] is None


def test_orchestration_drill_covers_deadline_fail_closed_and_zero_external_calls():
    result = orchestration_drill()

    assert result["schema"] == "mova-orchestration-drill-v1"
    assert result["status"] == "pass"
    assert len(result["checks"]) == 13
    assert all(result["checks"].values())
    assert result["external_calls"] == 0
    assert result["runtime_mutated"] is False


def test_empty_workflow_is_read_only_pending_and_metrics_have_bounded_labels(tmp_path: Path):
    config = RuntimeConfig(
        ops_db=tmp_path / "ops.db", artifact_root=tmp_path / "artifacts",
        canonical_db=tmp_path / "canonical.db", trace_db=tmp_path / "trace.db",
        analytics_root=tmp_path / "analytics", strategic_root=tmp_path / "strategy",
        research_root=tmp_path / "research", lock_path=tmp_path / "runtime.lock",
    )
    db = OpsDB(config.ops_db, enforce_version=False)
    db.migrate()
    report = build_workflow(config, db, now=NOW)

    assert report["cycle_id"] is None
    assert report["runtime_mutated"] is False
    assert report["verdict"] == "attention_required"
    metrics = prometheus(report)
    assert 'mova_orchestration_status{status="attention_required"} 1' in metrics
    assert "2026-27" not in metrics


def test_orchestration_cli_is_audited_idempotent_and_conflict_safe(
    tmp_path: Path, monkeypatch, capsys,
):
    config = RuntimeConfig(
        ops_db=tmp_path / "ops.db", artifact_root=tmp_path / "artifacts",
        canonical_db=tmp_path / "canonical.db", trace_db=tmp_path / "trace.db",
        analytics_root=tmp_path / "analytics", strategic_root=tmp_path / "strategy",
        research_root=tmp_path / "research", lock_path=tmp_path / "runtime.lock",
        sqlite_min_version="3.0.0",
    )
    config.ops_db.parent.mkdir(parents=True, exist_ok=True)
    OpsDB(config.ops_db, enforce_version=False).migrate()
    monkeypatch.setattr(RuntimeConfig, "from_env", classmethod(lambda _cls: config))
    argv = [
        "drill", "orchestration", "--actor", "codex", "--reason", "contract test",
        "--idempotency-key", "orchestration:test:v1",
    ]
    assert main(argv) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["status"] == "pass"
    assert main(argv) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "reused"

    conflict = [*argv]
    conflict[conflict.index("contract test")] = "different intent"
    assert main(conflict) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "conflict"
    db = OpsDB(config.ops_db, enforce_version=False)
    assert db.orchestration_drill_status()["passed"] == 13
    with db.connect(readonly=True) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM job_runs WHERE job_type='orchestration_drill'"
        ).fetchone()[0] == 1


def test_parser_exposes_workflow_and_orchestration_drill():
    assert parser().parse_args(["harness", "workflow"]).harness_command == "workflow"
    parsed = parser().parse_args([
        "drill", "orchestration", "--actor", "codex", "--reason", "test",
        "--idempotency-key", "orchestration:v1",
    ])
    assert parsed.drill_command == "orchestration"
