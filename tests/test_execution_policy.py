from datetime import datetime, timezone
from pathlib import Path

from mova_fpl.ops.cli import parser
import hashlib
import json

from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB, sha256_json
from mova_fpl.ops.execution import ExecutionService, build_execution_plan


NOW = datetime(2026, 9, 4, 16, 0, tzinfo=timezone.utc)


def _decision(*, squad=range(1, 16), starters=range(1, 12), captain=1,
              vice=2, bench=range(12, 16), transfers_in=(), transfers_out=(),
              hits=0, chip=None):
    return {
        "season": "2026-27", "gw": 3, "squad_15": list(squad),
        "starters": list(starters), "captain": captain, "vice_captain": vice,
        "bench_order": list(bench), "transfers_in": list(transfers_in),
        "transfers_out": list(transfers_out), "hits": hits, "chip": chip,
        "expected_points": 50.0,
    }


def _envelope(selected: dict) -> dict:
    current = _decision()
    return {
        "cycle_id": "2026-27-gw03", "season": "2026-27", "gw": 3,
        "selected_candidate_key": "milp_baseline",
        "manifest": {"content_sha256": "b" * 64},
        "team_state": {"fingerprint": "team-fingerprint"},
        "candidates": [
            {"candidate_key": "do_nothing", "decision": current},
            {"candidate_key": "milp_baseline", "decision": selected},
        ],
    }


def _inputs(selected: dict, *, controls: dict) -> dict:
    return {
        "envelope": _envelope(selected),
        "envelope_row": {
            "envelope_id": "envelope_1", "decision_id": "decision_1",
            "manifest_id": "manifest_1", "content_sha256": "a" * 64,
            "status": "staged",
        },
        "manifest_row": {
            "manifest_id": "manifest_1", "content_sha256": "b" * 64,
            "deadline_at": "2026-09-04T17:30:00+00:00",
        },
        "team_state": {
            "observed_at": "2026-09-04T15:55:00+00:00",
            "quality_status": "valid", "fingerprint": "team-fingerprint",
        },
        "controls": controls, "open_high_incidents": [], "prior_execution": None,
        "now": NOW, "idempotency_key": "preflight:gw03:v1",
        "actor": "test", "reason": "policy contract",
    }


AUTONOMOUS_A3 = {
    "mode": "autonomous", "action_level": "A3", "compliance_gate": "approved",
    "kill_switch": False, "browser_writes": True,
}


def test_r3_plan_is_authorized_only_with_all_a3_gates():
    selected = _decision(
        squad=range(2, 17), starters=range(2, 13), captain=2, vice=3,
        bench=range(13, 17), transfers_in=(16,), transfers_out=(1,),
    )
    plan = build_execution_plan(**_inputs(selected, controls=AUTONOMOUS_A3))

    assert plan["action"]["risk_class"] == "R3"
    assert plan["action"]["required_action_level"] == "A3"
    assert plan["authorization"]["status"] == "authorized"
    assert plan["authorization"]["authorized"] is True
    assert plan["action"]["exact_diff"]["transfers"] == {
        "out": [1], "in": [16], "hits": 0,
    }


def test_shadow_a0_fails_closed_with_explicit_blockers():
    selected = _decision(
        starters=(2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12), captain=2, vice=3,
        bench=(1, 13, 14, 15),
    )
    controls = {
        "mode": "shadow", "action_level": "A0", "compliance_gate": "pending",
        "kill_switch": True, "browser_writes": False,
    }
    plan = build_execution_plan(**_inputs(selected, controls=controls))

    assert plan["action"]["risk_class"] == "R2"
    assert plan["authorization"]["status"] == "blocked"
    assert {
        "KILL_SWITCH_OFF", "BROWSER_WRITES_ENABLED", "COMPLIANCE_APPROVED",
        "AUTONOMY_LEVEL_SUFFICIENT", "AUTONOMOUS_MODE",
    } <= set(plan["authorization"]["blocking_codes"])


def test_stale_or_changed_team_blocks_even_at_a3():
    inputs = _inputs(_decision(captain=2, vice=1), controls=AUTONOMOUS_A3)
    inputs["team_state"] = {
        **inputs["team_state"], "observed_at": "2026-09-04T14:00:00+00:00",
        "fingerprint": "changed",
    }
    plan = build_execution_plan(**inputs)

    assert {"TEAM_STATE_FRESH", "TEAM_STATE_FINGERPRINT_MATCH"} <= set(
        plan["authorization"]["blocking_codes"]
    )


def test_noop_is_never_sent_to_browser():
    plan = build_execution_plan(**_inputs(_decision(), controls={
        "mode": "shadow", "action_level": "A0", "compliance_gate": "pending",
        "kill_switch": True, "browser_writes": False,
    }))
    assert plan["action"]["risk_class"] == "R0"
    assert plan["authorization"]["status"] == "noop"
    assert plan["authorization"]["authorized"] is False
    assert plan["authorization"]["blocking_codes"] == []


def test_execution_schema_migrates_and_cli_requires_audited_preflight(tmp_path: Path):
    db = OpsDB(tmp_path / "ops.db", enforce_version=False)
    assert db.migrate()[-1] == 19
    with db.connect(readonly=True) as con:
        tables = {row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    assert {"execution_plans", "execution_preflight_checks"} <= tables
    args = parser().parse_args([
        "execute", "preflight", "--actor", "codex", "--reason", "test",
        "--idempotency-key", "preflight:test",
    ])
    assert args.execute_command == "preflight"


def test_preflight_service_persists_artifact_checks_and_reuses_key(tmp_path: Path):
    config = RuntimeConfig(
        ops_db=tmp_path / "db" / "ops.db", artifact_root=tmp_path / "artifacts",
        analytics_root=tmp_path / "analytics", strategic_root=tmp_path / "strategy",
        research_root=tmp_path / "research", host_probe_path=tmp_path / "host.json",
        collector_root=tmp_path / "collector", collector_browser_path=Path("/usr/bin/false"),
    )
    db = OpsDB(config.ops_db, enforce_version=False)
    db.migrate()
    db.ensure_defaults(mode="shadow", action_level="A0", compliance_gate="pending",
                       browser_writes=False)
    cycle = db.upsert_cycle("2026-27", 3, "2026-09-04T17:30:00+00:00", phase="preflight")
    source_job, _ = db.start_job("tick", "tick:fixture", "corr_fixture", cycle_id=cycle)
    team_id = db.add_team_state(
        job_id=source_job, cycle_id=cycle, observed_at="2026-09-04T15:55:00+00:00",
        source_name="fpl_authenticated_api",
        squad=[{"element": value} for value in range(1, 16)], free_transfers=1,
        bank_tenths=0, chips=[], fingerprint="team-fingerprint",
        artifact_path="team", manifest_sha256="c" * 64,
    )
    season_plan = db.activate_season_plan("2026-27", {
        "horizon_start_gw": 3, "horizon_end_gw": 8, "assumptions": [],
        "chip_windows": [], "guardrails": {}, "rationale": "fixture",
    }, actor="test", reason="fixture")
    manifest = db.add_cycle_manifest({
        "cycle_id": cycle, "as_of_at": "2026-09-04T16:00:00+00:00",
        "deadline_at": "2026-09-04T17:30:00+00:00", "phase": "preflight",
        "team_state_id": team_id, "plan_id": season_plan["plan_id"],
        "source_manifest": [], "analytics_manifest": {}, "research_summary": {},
        "artifact_path": "manifest.json",
    })
    selected = _decision(
        starters=(2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12), captain=2, vice=3,
        bench=(1, 13, 14, 15),
    )
    envelope = {
        **_envelope(selected), "schema": "mova-decision-envelope-v1",
        "policy_version": "decision-envelope-1.0.0", "mode": "shadow",
        "status": "staged", "manifest": {
            "manifest_id": manifest["manifest_id"],
            "content_sha256": manifest["content_sha256"],
        },
        "validation": {"status": "staged", "blocking_codes": [], "checks": []},
    }
    envelope["candidates"] = [
        {**row, "label": row["candidate_key"], "violations": []}
        for row in envelope["candidates"]
    ]
    content_sha = sha256_json(envelope)
    envelope = {**envelope, "envelope_id": f"envelope_{content_sha[:24]}",
                "content_sha256": content_sha}
    artifact = config.artifact_root / "decision-envelopes" / "envelope.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(json.dumps(envelope, sort_keys=True) + "\n", encoding="utf-8")
    recorded = db.record_decision_envelope(
        job_id=source_job, envelope=envelope, artifact_path=str(artifact),
        artifact_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
    )
    db.finish_job(source_job, "completed")

    service = ExecutionService(config, db)
    first = service.preflight(
        actor="test", reason="shadow rehearsal", idempotency_key="preflight:fixture",
        now=NOW,
    )
    second = service.preflight(
        actor="test", reason="shadow rehearsal", idempotency_key="preflight:fixture",
        now=NOW,
    )

    assert first["status"] == "blocked" and first["envelope_id"] == recorded["envelope_id"]
    assert second["reused"] is True and second["plan_id"] == first["plan_id"]
    with db.connect(readonly=True) as con:
        assert con.execute("SELECT COUNT(*) FROM execution_plans").fetchone()[0] == 1
        assert con.execute(
            "SELECT COUNT(*) FROM execution_preflight_checks"
        ).fetchone()[0] == 16
