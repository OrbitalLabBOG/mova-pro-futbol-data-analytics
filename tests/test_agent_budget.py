"""HV1-08: presupuesto fail-closed para trabajos agentic."""

from __future__ import annotations

import pytest

from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB


POLICY = {
    "reservation_tokens": 100,
    "job_tokens": 120,
    "gw_tokens": 200,
    "month_tokens": 300,
    "gw_uses": 2,
    "month_uses": 3,
}


def test_config_rechaza_presupuestos_incoherentes():
    config = RuntimeConfig(agent_budget_reservation_tokens=200_000,
                           agent_budget_job_tokens=100_000)
    with pytest.raises(ValueError, match="presupuestos de tokens"):
        config.validate()


def _runtime(tmp_path):
    db = OpsDB(tmp_path / "ops.db", enforce_version=False)
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
            'manifest_budget',?,1,'2026-08-30T12:00:00+00:00',
            '2026-09-04T17:30:00+00:00','preflight',NULL,NULL,'[]','{}','{}',
            'manifest.json',?, '2026-08-30T12:00:00+00:00')""",
            (cycle_id, "a" * 64),
        )
    return db, cycle_id


def _queue(db, cycle_id, run_id):
    return db.queue_research_run({
        "research_run_id": run_id,
        "cycle_id": cycle_id,
        "manifest_id": "manifest_budget",
        "provider": "fixture",
        "request_path": f"{run_id}.json",
        "request_sha256": run_id.removeprefix("research_").ljust(64, "0")[:64],
        "budget_policy": POLICY,
    })


def test_reserva_es_atomica_idempotente_y_bloquea_antes_de_encolar(tmp_path):
    db, cycle_id = _runtime(tmp_path)
    first = _queue(db, cycle_id, "research_11111111111111111111111111111111")
    reused = _queue(db, cycle_id, "research_11111111111111111111111111111111")
    second = _queue(db, cycle_id, "research_22222222222222222222222222222222")
    blocked = _queue(db, cycle_id, "research_33333333333333333333333333333333")

    assert first["status"] == "queued"
    assert reused["reused"] is True
    assert second["status"] == "queued"
    assert blocked["status"] == "blocked"
    assert blocked["budget"]["checks"]["gw_tokens"]["passed"] is False
    with db.connect(readonly=True) as con:
        assert con.execute("SELECT COUNT(*) FROM research_runs").fetchone()[0] == 2
        assert con.execute(
            "SELECT COUNT(*) FROM agent_budget_reservations"
        ).fetchone()[0] == 2
        assert con.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type='agent_budget_blocked'"
        ).fetchone()[0] == 1


def test_liquidacion_y_reporte_separan_consumido_de_reservado(tmp_path):
    db, cycle_id = _runtime(tmp_path)
    run_id = "research_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    _queue(db, cycle_id, run_id)
    db.import_research_result(run_id, {
        "documents": [], "signals": [], "conflicts": [],
        "usage": {"model": "fixture", "input_tokens": 40, "output_tokens": 20},
    }, result_path="result.json", result_sha256="b" * 64)

    report = db.cost_report(POLICY, season="2026-27", gw=3)
    assert report["gameweek"]["consumed_tokens"] == 60
    assert report["gameweek"]["reserved_tokens"] == 0
    assert report["gameweek"]["remaining_tokens"] == 140
    assert report["by_category"][0]["category"] == "news_research"
    with db.connect(readonly=True) as con:
        reservation = con.execute(
            "SELECT status,actual_tokens FROM agent_budget_reservations"
        ).fetchone()
        assert dict(reservation) == {"status": "settled", "actual_tokens": 60}


def test_resultado_rechazado_conserva_el_cargo_estimado(tmp_path):
    db, cycle_id = _runtime(tmp_path)
    run_id = "research_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    _queue(db, cycle_id, run_id)
    db.reject_research_run(run_id, error_code="invalid_output", error_detail="fixture")

    report = db.cost_report(POLICY, season="2026-27", gw=3)
    assert report["gameweek"]["consumed_tokens"] == 0
    assert report["gameweek"]["reserved_tokens"] == 100
    metrics = db.cost_prometheus(POLICY, season="2026-27")
    assert 'mova_agent_budget_tokens{scope="gameweek",kind="reserved"} 100' in metrics
    with db.connect(readonly=True) as con:
        row = con.execute(
            "SELECT status,actual_tokens FROM agent_budget_reservations"
        ).fetchone()
        assert dict(row) == {"status": "charged", "actual_tokens": 100}
