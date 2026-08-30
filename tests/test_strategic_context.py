"""HV1-04/05: plan, manifiesto y frontera de investigación."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB
from mova_fpl.ops.strategy import StrategicContextService


def _runtime(tmp_path: Path) -> tuple[RuntimeConfig, OpsDB, StrategicContextService, str]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    config = RuntimeConfig(
        ops_db=tmp_path / "db" / "ops.db",
        trace_db=tmp_path / "db" / "trace.db",
        canonical_db=tmp_path / "db" / "canonical.db",
        artifact_root=tmp_path / "artifacts",
        analytics_root=tmp_path / "artifacts" / "analytics",
        strategic_root=tmp_path / "artifacts" / "strategic",
        research_root=tmp_path / "artifacts" / "research",
        backup_root=tmp_path / "backups",
        host_probe_path=tmp_path / "runtime" / "probe.json",
        lock_path=tmp_path / "runtime" / "tick.lock",
        research_deadline_window_seconds=48 * 3600,
        research_min_interval_seconds=3600,
        disk_gate_bytes=1,
        memory_gate_bytes=1,
    )
    db = OpsDB(config.ops_db, enforce_version=False)
    db.migrate()
    deadline = now + timedelta(hours=12)
    cycle_id = db.upsert_cycle(
        config.season, 2, deadline.isoformat(), phase="press_conferences"
    )
    job_id, _ = db.start_job("tick", "test:strategic", "corr_strategic", cycle_id=cycle_id)
    db.add_snapshot(
        job_id=job_id, cycle_id=cycle_id, source_name="fpl_official",
        captured_at=now.isoformat(), artifact_path=str(tmp_path / "source"),
        manifest_sha256="a" * 64, payload_sha256="b" * 64, freshness_seconds=0,
        quality_status="valid", quality={"schema": "test"},
    )
    db.add_team_state(
        job_id=job_id, cycle_id=cycle_id, observed_at=now.isoformat(),
        source_name="fpl_authenticated_api",
        squad=[{"element": value} for value in range(1, 16)],
        free_transfers=1, bank_tenths=5,
        chips=[{"name": "wildcard", "status_for_entry": "available"}],
        fingerprint="c" * 64, artifact_path=str(tmp_path / "team"),
        manifest_sha256="d" * 64,
    )
    db.finish_job(job_id, "completed", metrics={"gw": 2})
    return config, db, StrategicContextService(config, db), cycle_id


def _plan() -> dict:
    return {
        "horizon_start_gw": 2,
        "horizon_end_gw": 8,
        "assumptions": ["Priorizar minutos y flexibilidad en las primeras jornadas."],
        "chip_windows": [{"chip": "wildcard", "earliest_gw": 4, "latest_gw": 8}],
        "guardrails": {"max_hit": 0, "preserve_free_transfer_when_marginal": True},
        "rationale": "Plan inicial revisable con evidencia y scorecards semanales.",
    }


def test_plan_y_manifest_son_versionados_e_idempotentes(tmp_path):
    _config, db, service, cycle_id = _runtime(tmp_path)
    plan = service.activate_plan(_plan(), actor="test", reason="bootstrap estratégico")
    reused_plan = service.activate_plan(_plan(), actor="test", reason="misma evidencia")
    manifest = service.prepare()

    assert plan["revision"] == 1
    assert reused_plan["reused"] is True
    assert manifest["cycle_id"] == cycle_id
    assert manifest["manifest"]["team_state"]["free_transfers"] == 1
    assert len(manifest["manifest"]["research_summary"]["focus"]) == 15
    assert manifest["manifest"]["research_summary"]["focus"][0]["focus_reason"] == [
        "current_squad"
    ]
    assert manifest["manifest"]["plan_revision"] == 1
    assert manifest["manifest"]["memory_summary"]["schema"] == (
        "mova-strategic-memory-v1"
    )
    assert manifest["manifest"]["memory_summary"]["status"] == "empty"
    assert manifest["manifest"]["memory_summary"]["policy"]["chat_history_allowed"] is False
    assert Path(manifest["artifact_path"]).is_file()
    strategic_status = db.strategic_status(cycle_id)
    assert strategic_status["status"] == "ready"
    assert strategic_status["memory_summary"]["content_sha256"] == (
        manifest["manifest"]["memory_summary"]["content_sha256"]
    )


def test_manifest_embeds_only_promoted_prior_gameweek_memory(tmp_path):
    config, db, service, current_cycle = _runtime(tmp_path)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    first_plan = service.activate_plan(
        _plan(), actor="test", reason="plan inicial",
    )
    revised_plan = _plan()
    revised_plan["rationale"] = "Plan revisado después del primer cierre causal."
    second_plan = service.activate_plan(
        revised_plan, actor="test", reason="revisión post-GW1",
    )

    prior_cycle = db.upsert_cycle(
        config.season, 1, (now - timedelta(days=7)).isoformat(), phase="settlement"
    )
    prior_job, _ = db.start_job(
        "gameweek_review", "memory:gw1", "corr_memory_gw1", cycle_id=prior_cycle,
    )
    prior_decision = db.record_decision(
        job_id=prior_job, cycle_id=prior_cycle, mode="shadow", status="reconciled",
        policy_version="fixture", expected_points=52.5, chip=None,
        fingerprint="decision-gw1", manifest_sha256="a" * 64,
        artifact_path="decision-gw1.json",
    )
    current_job, _ = db.start_job(
        "decision", "memory:gw2", "corr_memory_gw2", cycle_id=current_cycle,
    )
    current_decision = db.record_decision(
        job_id=current_job, cycle_id=current_cycle, mode="shadow", status="blocked",
        policy_version="fixture", expected_points=60.0, chip="wildcard",
        fingerprint="decision-gw2", manifest_sha256="b" * 64,
        artifact_path="decision-gw2.json",
    )
    with db.transaction() as con:
        con.execute(
            """INSERT INTO gameweek_settlements(
            settlement_id,idempotency_key,job_id,cycle_id,source_artifact_id,settled_at,
            entry_points,entry_rank,average_points,bench_points,hit_cost,captain_points,
            auto_subs_json,official_json,artifact_path,artifact_sha256)
            VALUES('settlement_memory','memory:settlement:gw1',?,?,?, ?,50,NULL,48,7,0,12,
            '[]','{}','settlement.json',?)""",
            (prior_job, prior_cycle, "source-gw1", now.isoformat(), "c" * 64),
        )
        con.execute(
            """INSERT INTO gameweek_reviews(
            review_id,job_id,settlement_id,decision_id,review_type,causality_status,
            expected_points,actual_points,comparator_label,comparator_expected_points,
            comparator_actual_points,realized_delta,metrics_json,findings_json,
            artifact_path,artifact_sha256,created_at)
            VALUES('review_memory',?,'settlement_memory',?,'causal','eligible',52.5,50,
            'hold',51.0,49,-1,'{}',?,'review.json',?,?)""",
            (prior_job, prior_decision, json.dumps([{
                "category": "strategy", "summary": "Conservar flexibilidad tuvo valor."
            }]), "d" * 64, now.isoformat()),
        )
        for proposal_id, title in (
            ("proposal_validated", "Memoria válida"),
            ("proposal_retired", "Memoria retirada"),
        ):
            con.execute(
                """INSERT INTO change_proposals(
                proposal_id,review_id,category,change_level,priority,title,hypothesis,
                evidence_json,acceptance_json,status,created_at)
                VALUES(?,'review_memory','strategy','C1','P2',?,?,'{}','{}','accepted',?)""",
                (proposal_id, title, title, now.isoformat()),
            )
        con.execute(
            """INSERT INTO lessons(
            lesson_id,proposal_id,review_id,category,statement,evidence_json,status,created_at)
            VALUES('lesson_validated','proposal_validated','review_memory','strategy',
            'Preservar una transferencia cuando el margen sea pequeño.',
            '{"experiment_id":"memory-fixture"}','validated',?)""",
            (now.isoformat(),),
        )
        con.execute(
            """INSERT INTO lessons(
            lesson_id,proposal_id,review_id,category,statement,evidence_json,status,
            created_at,retired_at)
            VALUES('lesson_retired','proposal_retired','review_memory','strategy',
            'Supuesto retirado.','{}','retired',?,?)""",
            (now.isoformat(), now.isoformat()),
        )

    manifest = service.prepare(now=now)["manifest"]
    memory = manifest["memory_summary"]

    assert memory["status"] == "ready"
    assert memory["plan_comparison"] == {
        "active_plan_id": second_plan["plan_id"],
        "active_revision": 2,
        "previous_plan_id": first_plan["plan_id"],
        "previous_revision": 1,
        "changed_from_previous": True,
    }
    assert [item["gw"] for item in memory["decision_records"]] == [1]
    assert all(item["decision_id"] != current_decision for item in memory["decision_records"])
    assert [item["review_id"] for item in memory["gw_reviews"]] == ["review_memory"]
    assert [item["lesson_id"] for item in memory["lessons"]] == ["lesson_validated"]
    assert memory["lessons"][0]["promotion_status"] == "validated"
    assert memory["coverage"]["lessons"] == {
        "available": 1, "included": 1, "truncated": False,
    }
    assert len(memory["content_sha256"]) == 64
    persisted = db.latest_cycle_manifest(current_cycle)
    assert persisted["memory_summary"] == memory
    metrics = db.prometheus()
    assert 'mova_strategic_memory_status{status="ready"} 1' in metrics
    assert 'mova_strategic_memory_items{type="decisions"} 1' in metrics
    assert 'mova_strategic_memory_items{type="reviews"} 1' in metrics
    assert 'mova_strategic_memory_items{type="lessons"} 1' in metrics
    assert "mova_strategic_plan_revision 2" in metrics


def test_manifest_resuelve_plantilla_y_candidatos_para_research(tmp_path, monkeypatch):
    config, db, _service, _cycle_id = _runtime(tmp_path)
    credential = tmp_path / "postgres-password"
    credential.write_text("fixture", encoding="utf-8")
    config = replace(config, postgres_credential_file=credential)

    resolved = [{
        "element": 1, "player_name": "Player One", "team": "Test FC",
        "position": "MID", "focus_reason": ["current_squad"],
        "official_news": "75% chance of playing",
    }]

    def focus(_self, *, squad, batch_id, candidate_limit):
        assert len(squad) == 15
        assert candidate_limit == 10
        return list(resolved)

    monkeypatch.setattr(
        "mova_fpl.ops.analytics_store.AnalyticsStore.research_focus", focus
    )
    service = StrategicContextService(config, db)
    observed = datetime.now(timezone.utc).replace(microsecond=0)
    first = service.prepare(now=observed)
    manifest = first["manifest"]
    assert manifest["research_summary"]["focus"] == [{
        "element": 1, "player_name": "Player One", "team": "Test FC",
        "position": "MID", "focus_reason": ["current_squad"],
        "official_news": "75% chance of playing",
    }]
    resolved.append({
        "element": 2, "player_name": "Player Two", "team": "Test FC",
        "position": "FWD", "focus_reason": ["top_projection_candidate"],
        "official_news": None,
    })
    changed = service.prepare(now=observed)
    assert changed["revision"] == first["revision"] + 1
    assert changed["content_sha256"] != first["content_sha256"]


def test_manifest_usa_el_servicio_analitico_si_sqlite_no_tiene_proyeccion(tmp_path):
    config, _db, service, _cycle_id = _runtime(tmp_path)
    config.analytics_root.mkdir(parents=True, exist_ok=True)
    (config.analytics_root / "status.json").write_text(json.dumps({
        "schema": "mova-analytics-service-status-v1",
        "status": "healthy",
        "latest_projection_batches": [{
            "batch_id": "batch_gw02_baseline", "season": config.season,
            "target_gw": 2, "variant": "baseline", "status": "approved",
            "model_versions": {"minutes": "1.1.0", "points": "1.1.0"},
            "cutoff_at": "2026-08-28T05:00:00+00:00",
            "generated_at": "2026-08-28T05:01:00+00:00", "player_count": 616,
        }],
    }), encoding="utf-8")

    manifest = service.prepare()["manifest"]["analytics_manifest"]
    assert manifest["source"] == "published_status"
    assert manifest["status"] == "approved"
    assert manifest["batch_id"] == "batch_gw02_baseline"
    assert manifest["player_count"] == 616


def test_manifest_incluye_solo_el_snapshot_mas_reciente_por_fuente(tmp_path):
    _config, db, service, cycle_id = _runtime(tmp_path)
    job_id = db.recent("job_runs", 1)[0]["job_id"]
    db.add_snapshot(
        job_id=job_id, cycle_id=cycle_id, source_name="fpl_official",
        captured_at=datetime.now(timezone.utc).isoformat(),
        artifact_path=str(tmp_path / "source-new"),
        manifest_sha256="e" * 64, payload_sha256="f" * 64, freshness_seconds=0,
        quality_status="valid", quality={"schema": "test"},
    )

    sources = service.prepare()["manifest"]["source_manifest"]
    assert len(sources) == 1
    assert sources[0]["manifest_sha256"] == "e" * 64
    assert sources[0]["artifact_path"].endswith("source-new")


def test_resultado_codex_se_valida_antes_de_entrar(tmp_path):
    config, db, service, cycle_id = _runtime(tmp_path)
    service.activate_plan(_plan(), actor="test", reason="bootstrap estratégico")
    queued = service.enqueue(
        force=True, actor="test", reason="prueba de frontera",
        idempotency_key="research:test",
    )
    run_id = queued["research_run_id"]
    run = db.research_run(run_id)
    assert run and run["status"] == "queued"
    now = datetime.now(timezone.utc)
    source = "https://www.premierleague.com/news/example"
    result = {
        "schema": "mova-research-brief-v1",
        "research_run_id": run_id,
        "cycle_id": cycle_id,
        "request_sha256": run["request_sha256"],
        "generated_at": now.isoformat(),
        "summary": "No hay una alerta adicional fuera de la declaración oficial.",
        "documents": [{
            "source_url": source, "title": "Team news", "publisher": "Premier League",
            "published_at": now.date().isoformat(), "source_tier": "official",
        }],
        "signals": [{
            "subject_name": "Player 1", "player_element": 1,
            "claim_type": "availability", "claim_text": "Disponible para selección.",
            "direction": "positive", "confidence": 0.9,
            "source_urls": [source],
            "expires_at": (now + timedelta(days=1)).isoformat(),
        }],
        "conflicts": [], "limitations": ["Sujeto a cambios posteriores."],
        "usage": {"model": "fixture", "input_tokens": 10, "output_tokens": 20},
    }
    result_path = config.research_root / "outbox" / f"{run_id}.result.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result), encoding="utf-8")
    db.reject_research_run(
        run_id, error_code="ValueError", error_detail="intento recuperable",
    )

    imported = service.import_ready()
    assert imported["processed"] == 1
    assert imported["results"][0]["accepted"] == 1
    stored_run = db.research_run(run_id)
    assert stored_run["status"] == "imported"
    assert stored_run["error_code"] is None
    assert stored_run["error_detail"] is None
    assert stored_run["result_path"].endswith(f"archive/{run_id}.result.json")
    assert not result_path.exists()
    assert (config.research_root / "archive" / result_path.name).is_file()
    assert not Path(run["request_path"]).exists()
    assert (config.research_root / "archive" / Path(run["request_path"]).name).is_file()
    with db.connect(readonly=True) as con:
        document = con.execute(
            "SELECT published_at FROM research_documents WHERE research_run_id=?",
            (run_id,),
        ).fetchone()
        signal = con.execute(
            "SELECT validation_status,source_tier FROM research_signals "
            "WHERE research_run_id=?", (run_id,),
        ).fetchone()
        cost = con.execute(
            "SELECT subscription_usage,estimated_cost_usd FROM cost_ledger "
            "WHERE research_run_id=?", (run_id,),
        ).fetchone()
    assert document["published_at"].endswith("T00:00:00+00:00")
    assert dict(signal) == {"validation_status": "accepted", "source_tier": "official"}
    assert dict(cost) == {"subscription_usage": 1, "estimated_cost_usd": None}


def test_slot_final_es_obligatorio_aunque_cadencia_rutina_no_venza(tmp_path):
    _config, db, service, cycle_id = _runtime(tmp_path)
    current = datetime.now(timezone.utc).replace(microsecond=0)
    queued = service.enqueue(
        force=True, actor="test", reason="corrida rutinaria",
        idempotency_key="research:routine-before-final",
    )
    old = (current - timedelta(hours=3)).isoformat()
    deadline = (current + timedelta(minutes=90)).isoformat()
    with db.transaction() as con:
        con.execute(
            "UPDATE gameweek_cycles SET deadline_at=? WHERE cycle_id=?",
            (deadline, cycle_id),
        )
        con.execute(
            "UPDATE research_runs SET status='imported',queued_at=?,finished_at=?,"
            "imported_at=? WHERE research_run_id=?",
            (old, old, old, queued["research_run_id"]),
        )

    due = service.due(now=current)
    assert due["due"] is True
    assert due["run_kind"] == "final"

    final_observed = (current - timedelta(minutes=20)).isoformat()
    with db.transaction() as con:
        con.execute(
            "UPDATE research_runs SET queued_at=?,finished_at=?,imported_at=? "
            "WHERE research_run_id=?",
            (final_observed, final_observed, final_observed, queued["research_run_id"]),
        )
    completed = service.due(now=current)
    assert completed["due"] is False
    assert completed["reason"] == "final_already_completed"


def test_research_no_arranca_despues_del_cutoff_final(tmp_path):
    _config, db, service, cycle_id = _runtime(tmp_path)
    current = datetime.now(timezone.utc).replace(microsecond=0)
    with db.transaction() as con:
        con.execute(
            "UPDATE gameweek_cycles SET deadline_at=? WHERE cycle_id=?",
            ((current + timedelta(minutes=60)).isoformat(), cycle_id),
        )
    due = service.due(now=current)
    assert due["due"] is False
    assert due["reason"] == "final_cutoff_passed"


def test_url_privada_se_cuarentena_y_no_contamina_signals(tmp_path):
    config, db, service, cycle_id = _runtime(tmp_path)
    service.activate_plan(_plan(), actor="test", reason="bootstrap estratégico")
    queued = service.enqueue(
        force=True, actor="test", reason="prueba SSRF",
        idempotency_key="research:ssrf",
    )
    run_id = queued["research_run_id"]
    run = db.research_run(run_id)
    now = datetime.now(timezone.utc)
    result = {
        "schema": "mova-research-brief-v1", "research_run_id": run_id,
        "cycle_id": cycle_id, "request_sha256": run["request_sha256"],
        "generated_at": now.isoformat(), "summary": "Entrada hostil.",
        "documents": [{
            "source_url": "https://127.0.0.1/admin", "title": "internal",
            "publisher": "internal", "published_at": None, "source_tier": "other",
        }],
        "signals": [], "conflicts": [], "limitations": [],
        "usage": {"model": "fixture", "input_tokens": 1, "output_tokens": 1},
    }
    path = config.research_root / "outbox" / f"{run_id}.result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result), encoding="utf-8")

    imported = service.import_ready()
    assert imported["results"][0]["status"] == "rejected"
    assert "no pública" in imported["results"][0]["error"]
    assert db.recent("research_signals") == []
    assert (config.research_root / "quarantine" / path.name).is_file()
