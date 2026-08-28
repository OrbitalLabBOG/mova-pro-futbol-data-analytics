"""HV1-04/05: plan, manifiesto y frontera de investigación."""

from __future__ import annotations

import json
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
    assert manifest["manifest"]["plan_revision"] == 1
    assert Path(manifest["artifact_path"]).is_file()
    assert db.strategic_status(cycle_id)["status"] == "ready"


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
            "published_at": now.isoformat(), "source_tier": "official",
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

    imported = service.import_ready()
    assert imported["processed"] == 1
    assert imported["results"][0]["accepted"] == 1
    assert db.research_run(run_id)["status"] == "imported"
    with db.connect(readonly=True) as con:
        signal = con.execute(
            "SELECT validation_status,source_tier FROM research_signals "
            "WHERE research_run_id=?", (run_id,),
        ).fetchone()
        cost = con.execute(
            "SELECT subscription_usage,estimated_cost_usd FROM cost_ledger "
            "WHERE research_run_id=?", (run_id,),
        ).fetchone()
    assert dict(signal) == {"validation_status": "accepted", "source_tier": "official"}
    assert dict(cost) == {"subscription_usage": 1, "estimated_cost_usd": None}


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
