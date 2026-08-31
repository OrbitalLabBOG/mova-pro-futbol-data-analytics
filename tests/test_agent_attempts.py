"""Recibos append-only y replay acotado del worker Codex."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from mova_fpl.ops.agent_attempts import AgentAttemptService
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB


def _runtime(tmp_path):
    config = RuntimeConfig(
        ops_db=tmp_path / "ops.db", research_root=tmp_path / "research",
        sqlite_min_version="0.0.0",
    )
    db = OpsDB(config.ops_db, enforce_version=False)
    db.migrate()
    cycle_id = db.upsert_cycle(
        "2026-27", 3, "2026-09-04T17:30:00+00:00", phase="preflight"
    )
    with db.transaction() as con:
        con.execute(
            """INSERT INTO cycle_manifests(
            manifest_id,cycle_id,revision,as_of_at,deadline_at,phase,team_state_id,plan_id,
            source_manifest_json,analytics_manifest_json,research_summary_json,artifact_path,
            content_sha256,created_at) VALUES(
            'manifest_attempt',?,1,'2026-08-30T12:00:00+00:00',
            '2026-09-04T17:30:00+00:00','preflight',NULL,NULL,'[]','{}','{}',
            'manifest.json',?, '2026-08-30T12:00:00+00:00')""",
            (cycle_id, "a" * 64),
        )
    run_id = "research_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    request_sha = "b" * 64
    request_path = config.research_root / "inbox" / f"{run_id}.request.json"
    request_path.parent.mkdir(parents=True)
    request_path.write_text("{}\n", encoding="utf-8")
    db.queue_research_run({
        "research_run_id": run_id, "cycle_id": cycle_id,
        "manifest_id": "manifest_attempt", "provider": "fixture",
        "request_path": str(request_path), "request_sha256": request_sha,
        "budget_policy": {"reservation_tokens": 100, "job_tokens": 120,
                          "gw_tokens": 300, "month_tokens": 600,
                          "gw_uses": 3, "month_uses": 6},
    })
    return config, db, run_id, request_sha, request_path


def _receipt(config, run_id, request_sha, attempt, phase, status, **values):
    payload = {
        "schema": "mova-agent-attempt-v1", "attempt_id": attempt,
        "subject_type": "research", "subject_id": run_id,
        "request_sha256": request_sha, "event_type": phase, "status": status,
        "model": "fixture", "input_tokens": values.get("input_tokens"),
        "output_tokens": values.get("output_tokens"),
        "duration_ms": values.get("duration_ms"), "error_code": values.get("error_code"),
        "output_present": values.get("output_present"),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }
    root = config.research_root / "receipts"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{run_id}.{attempt}.{phase}.json"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return path


def test_receipts_son_idempotentes_y_replay_alterado_se_cuarentena(tmp_path):
    config, db, run_id, request_sha, _ = _runtime(tmp_path)
    attempt = "attempt_11111111111111111111111111111111"
    path = _receipt(config, run_id, request_sha, attempt, "started", "running")
    service = AgentAttemptService(config, db)
    first = service.import_ready()
    replay = service.import_ready()
    assert first["results"][0]["reused"] is False
    assert replay["results"][0]["reused"] is True

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["model"] = "tampered"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    rejected = service.import_ready()
    assert rejected["rejected"][0]["error"] == "receipt replay con contenido diferente"
    assert not path.exists()


def test_dos_intentos_fallidos_terminalizan_request_y_cargan_estimate(tmp_path):
    config, db, run_id, request_sha, request_path = _runtime(tmp_path)
    for value in ("1" * 32, "2" * 32):
        attempt = f"attempt_{value}"
        _receipt(config, run_id, request_sha, attempt, "started", "running")
        _receipt(config, run_id, request_sha, attempt, "finished", "failed",
                 input_tokens=10, output_tokens=2, duration_ms=50,
                 error_code="codex_exec_failed", output_present=False)
    result = AgentAttemptService(config, db).import_ready()
    assert result["exhausted"] == [{
        "subject_type": "research", "subject_id": run_id, "attempts": 2,
        "request_path": str(config.research_root / "quarantine" / request_path.name),
    }]
    assert db.research_run(run_id)["status"] == "rejected"
    assert not request_path.exists()
    with db.connect(readonly=True) as con:
        reservation = con.execute(
            "SELECT status,actual_tokens,attempt_count,accounting_mode,estimated_tokens "
            "FROM agent_budget_reservations"
        ).fetchone()
        assert dict(reservation) == {
            "status": "charged", "actual_tokens": 24, "attempt_count": 2,
            "accounting_mode": "exact", "estimated_tokens": 0,
        }
        assert con.execute(
            "SELECT COUNT(*) FROM agent_worker_attempt_events"
        ).fetchone()[0] == 4


def test_success_receipt_impide_terminalizar_aunque_haya_dos_starts(tmp_path):
    config, db, run_id, request_sha, request_path = _runtime(tmp_path)
    for index, status in (("3" * 32, "failed"), ("4" * 32, "succeeded")):
        attempt = f"attempt_{index}"
        _receipt(config, run_id, request_sha, attempt, "started", "running")
        _receipt(config, run_id, request_sha, attempt, "finished", status,
                 input_tokens=10, output_tokens=2, duration_ms=50,
                 error_code="codex_exec_failed" if status == "failed" else None,
                 output_present=status == "succeeded")
    result = AgentAttemptService(config, db).import_ready()
    assert result["exhausted"] == []
    assert db.research_run(run_id)["status"] == "queued"
    assert request_path.exists()
    metrics = db.agent_worker_attempt_prometheus()
    assert 'mova_agent_worker_attempts{status="started"} 2' in metrics
    assert 'mova_agent_worker_attempts{status="failed"} 1' in metrics
    assert 'mova_agent_worker_attempts{status="succeeded"} 1' in metrics


def test_resultado_logico_suma_ambos_intentos_sin_doble_conteo(tmp_path):
    config, db, run_id, request_sha, _ = _runtime(tmp_path)
    for index, status in (("5" * 32, "failed"), ("6" * 32, "succeeded")):
        attempt = f"attempt_{index}"
        _receipt(config, run_id, request_sha, attempt, "started", "running")
        _receipt(config, run_id, request_sha, attempt, "finished", status,
                 input_tokens=10, output_tokens=2, duration_ms=50,
                 error_code="codex_exec_failed" if status == "failed" else None,
                 output_present=status == "succeeded")
    AgentAttemptService(config, db).import_ready()
    imported = db.import_research_result(run_id, {
        "documents": [], "signals": [], "conflicts": [],
        "usage": {"model": "fixture", "input_tokens": 10, "output_tokens": 2},
    }, result_path="result.json", result_sha256="c" * 64)

    assert imported["budget_settlement"]["actual_tokens"] == 24
    assert imported["budget_settlement"]["attempt_count"] == 2
    assert imported["budget_settlement"]["accounting_mode"] == "exact"
    report = db.cost_report({"reservation_tokens": 100, "job_tokens": 120,
                             "gw_tokens": 300, "month_tokens": 600,
                             "gw_uses": 3, "month_uses": 6},
                            season="2026-27", gw=3)
    assert report["gameweek"]["consumed_tokens"] == 24
    assert report["gameweek"]["consumed_uses"] == 2
    assert report["gameweek"]["committed_tokens"] == 24


def test_intentos_sin_fin_se_cargan_conservadoramente_por_intento(tmp_path):
    config, db, run_id, request_sha, _ = _runtime(tmp_path)
    for value in ("7" * 32, "8" * 32):
        _receipt(config, run_id, request_sha, f"attempt_{value}", "started", "running")
    AgentAttemptService(config, db).import_ready()

    report = db.cost_report({"reservation_tokens": 100, "job_tokens": 120,
                             "gw_tokens": 300, "month_tokens": 600,
                             "gw_uses": 3, "month_uses": 6},
                            season="2026-27", gw=3)
    assert report["gameweek"]["charged_tokens"] == 200
    assert report["gameweek"]["charged_uses"] == 2
    assert report["gameweek"]["charged_estimate_tokens"] == 200
    assert report["gameweek"]["charged_estimate_uses"] == 2
