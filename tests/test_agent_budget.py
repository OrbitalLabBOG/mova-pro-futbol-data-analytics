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


def _queue(db, cycle_id, run_id, policy=POLICY):
    return db.queue_research_run({
        "research_run_id": run_id,
        "cycle_id": cycle_id,
        "manifest_id": "manifest_budget",
        "provider": "fixture",
        "request_path": f"{run_id}.json",
        "request_sha256": run_id.removeprefix("research_").ljust(64, "0")[:64],
        "budget_policy": policy,
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
    assert report["gameweek"]["reserved_tokens"] == 0
    assert report["gameweek"]["charged_estimate_tokens"] == 100
    assert report["gameweek"]["committed_tokens"] == 100
    metrics = db.cost_prometheus(POLICY, season="2026-27")
    assert 'mova_agent_budget_tokens{scope="gameweek",kind="reserved"} 0' in metrics
    assert (
        'mova_agent_budget_tokens{scope="gameweek",kind="charged_estimate"} 100'
        in metrics
    )
    with db.connect(readonly=True) as con:
        row = con.execute(
            "SELECT status,actual_tokens FROM agent_budget_reservations"
        ).fetchone()
        assert dict(row) == {"status": "charged", "actual_tokens": 100}


def test_overrun_real_del_job_es_visible_sin_contarlo_como_reserva(tmp_path):
    db, cycle_id = _runtime(tmp_path)
    run_id = "research_cccccccccccccccccccccccccccccccc"
    _queue(db, cycle_id, run_id)
    imported = db.import_research_result(run_id, {
        "documents": [], "signals": [], "conflicts": [],
        "usage": {"model": "fixture", "input_tokens": 100, "output_tokens": 30},
    }, result_path="result.json", result_sha256="c" * 64)

    assert imported["budget_settlement"] == {
        "status": "settled", "reservation_id": imported["budget_settlement"]["reservation_id"],
        "reserved_tokens": 100, "actual_tokens": 130, "job_limit": 120,
        "overrun": True, "reused": False,
    }

    report = db.cost_report(POLICY, season="2026-27", gw=3)
    assert report["status"] == "job_overrun_observed"
    assert report["gameweek"]["consumed_tokens"] == 130
    assert report["gameweek"]["reserved_tokens"] == 0
    assert report["gameweek"]["charged_estimate_tokens"] == 0
    assert report["job_overruns"]["status"] == "unreviewed"
    assert report["job_overruns"]["gameweek"] == {
        "status": "unreviewed", "uses": 1, "excess_tokens": 10,
        "max_actual_tokens": 130,
        "states": {"open": 1, "reviewed": 0, "resolved": 0, "waived": 0},
    }
    metrics = db.cost_prometheus(POLICY, season="2026-27")
    assert 'mova_agent_budget_job_overruns{scope="gameweek"} 1' in metrics
    assert 'mova_agent_budget_job_overrun_tokens{scope="gameweek"} 10' in metrics
    assert (
        'mova_agent_budget_overrun_reviews{scope="gameweek",status="open"} 1'
        in metrics
    )
    with db.connect(readonly=True) as con:
        audit = con.execute(
            "SELECT severity,payload_json FROM audit_events "
            "WHERE event_type='agent_budget_settled'"
        ).fetchone()
        assert audit["severity"] == "warning"
        assert '"overrun":true' in audit["payload_json"]


def test_overrun_review_transition_is_idempotent_and_requires_verified_followup(tmp_path):
    policy = {**POLICY, "gw_tokens": 400, "month_tokens": 600,
              "gw_uses": 4, "month_uses": 6}
    db, cycle_id = _runtime(tmp_path)
    overrun_run = "research_eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    _queue(db, cycle_id, overrun_run, policy)
    imported = db.import_research_result(overrun_run, {
        "documents": [], "signals": [], "conflicts": [],
        "usage": {"model": "fixture", "input_tokens": 100, "output_tokens": 30},
    }, result_path="result.json", result_sha256="e" * 64)
    reservation_id = imported["budget_settlement"]["reservation_id"]

    reviewed = db.transition_budget_overrun(
        reservation_id, to_status="reviewed", action="optimize_prompt",
        followup_reservation_id=None, actor="codex", reason="reducir discovery repetitivo",
        idempotency_key="overrun-review-v1",
    )
    replay = db.transition_budget_overrun(
        reservation_id, to_status="reviewed", action="optimize_prompt",
        followup_reservation_id=None, actor="codex", reason="reducir discovery repetitivo",
        idempotency_key="overrun-review-v1",
    )
    assert reviewed["to_status"] == "reviewed"
    assert reviewed["runtime_mutated"] is False
    assert replay["status"] == "reused"
    assert db.cost_report(policy, season="2026-27", gw=3)["job_overruns"][
        "status"
    ] == "reviewed_pending"
    with pytest.raises(ValueError, match="followup_reservation_id"):
        db.transition_budget_overrun(
            reservation_id, to_status="resolved", action="verified_followup",
            followup_reservation_id=None, actor="codex", reason="sin followup",
            idempotency_key="overrun-resolve-invalid",
        )

    followup_run = "research_ffffffffffffffffffffffffffffffff"
    _queue(db, cycle_id, followup_run, policy)
    followup = db.import_research_result(followup_run, {
        "documents": [], "signals": [], "conflicts": [],
        "usage": {"model": "fixture", "input_tokens": 50, "output_tokens": 20},
    }, result_path="followup.json", result_sha256="f" * 64)
    resolved = db.transition_budget_overrun(
        reservation_id, to_status="resolved", action="verified_followup",
        followup_reservation_id=followup["budget_settlement"]["reservation_id"],
        actor="codex", reason="followup equivalente bajo límite",
        idempotency_key="overrun-resolve-v1",
    )
    assert resolved["to_status"] == "resolved"
    report = db.cost_report(policy, season="2026-27", gw=3)
    assert report["status"] == "within_budget"
    assert report["job_overruns"]["status"] == "closed"
    assert report["job_overruns"]["gameweek"]["states"]["resolved"] == 1
    with pytest.raises(ValueError, match="otro contenido"):
        db.transition_budget_overrun(
            reservation_id, to_status="resolved", action="verified_followup",
            followup_reservation_id=followup["budget_settlement"]["reservation_id"],
            actor="otro", reason="followup equivalente bajo límite",
            idempotency_key="overrun-resolve-v1",
        )


def test_reserva_huerfana_es_visible_y_sigue_comprometiendo_presupuesto(tmp_path):
    db, cycle_id = _runtime(tmp_path)
    run_id = "research_dddddddddddddddddddddddddddddddd"
    _queue(db, cycle_id, run_id)
    # Simula un crash histórico entre el terminal del job y su reconciliación de budget.
    with db.transaction() as con:
        con.execute(
            "UPDATE research_runs SET status='rejected' WHERE research_run_id=?", (run_id,)
        )

    report = db.cost_report(POLICY, season="2026-27", gw=3)
    assert report["status"] == "orphaned_reservation_observed"
    assert report["gameweek"]["reserved_tokens"] == 100
    assert report["gameweek"]["committed_tokens"] == 100
    assert report["orphaned_reservations"]["gameweek"] == {"uses": 1, "tokens": 100}
    metrics = db.cost_prometheus(POLICY, season="2026-27")
    assert 'mova_agent_budget_orphaned_reservations{scope="gameweek"} 1' in metrics
