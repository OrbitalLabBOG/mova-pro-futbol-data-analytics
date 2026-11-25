"""Ingreso auditable del estado privado sanitizado por el browser aislado."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from mova_fpl.data.private_state import (SOURCE_CAPTURE, SOURCE_IMPORT, normalize_import,
                                         seal, validate)
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB, new_id, sha256_json
from mova_fpl.ops.schedule import phase_for


def ingest(config: RuntimeConfig, db: OpsDB, payload: dict, *,
           trigger: str = "scheduled", source_name: str = SOURCE_CAPTURE,
           job_key: str | None = None) -> dict:
    if trigger not in {"scheduled", "forced"}:
        raise ValueError(f"trigger privado inválido: {trigger}")
    normalized, quality = validate(payload, expected_team_id=config.team_id)
    gw = int(normalized["event"]["id"])
    deadline = str(normalized["event"]["deadline_time"])
    cycle_id = db.upsert_cycle(
        config.season, gw, deadline,
        phase=phase_for(deadline, datetime.now(timezone.utc)),
    )
    fingerprint = quality["fingerprint"]
    observation_sha = sha256_json(normalized)
    correlation_id = new_id("corr")
    job_id, reused = db.start_job(
        "private_team_state",
        job_key or f"private-team-state:{config.season}:{gw}:{observation_sha}",
        correlation_id,
        cycle_id=cycle_id,
        input_sha256=observation_sha,
    )
    if reused:
        # Ya sellado por el job original: devuelve SU snapshot (no el último del ciclo).
        with db.connect(readonly=True) as con:
            row = con.execute(
                "SELECT team_state_id,artifact_path,fingerprint,observed_at "
                "FROM team_state_snapshots WHERE job_id=?", (job_id,)).fetchone()
        known = dict(row) if row else {}
        return {"status": "reused", "job_id": job_id, "cycle_id": cycle_id,
                "source_name": source_name, **{"fingerprint": fingerprint, **known}}
    try:
        dest, manifest, normalized = seal(
            normalized,
            config.season,
            config.artifact_root / "team_state",
            expected_team_id=config.team_id,
            source_label=None if source_name == SOURCE_CAPTURE else source_name,
        )
        manifest_sha = hashlib.sha256((dest / "manifest.json").read_bytes()).hexdigest()
        team_state_id = db.add_team_state(
            job_id=job_id,
            cycle_id=cycle_id,
            observed_at=normalized["observed_at"],
            source_name=source_name,
            squad=normalized["picks"],
            free_transfers=quality["free_transfers"],
            bank_tenths=quality["bank_tenths"],
            chips=normalized["chips"],
            fingerprint=fingerprint,
            artifact_path=str(dest),
            manifest_sha256=manifest_sha,
        )
        db.append_audit(
            "team_state_capture_trigger", correlation_id=correlation_id,
            cycle_id=cycle_id, job_id=job_id, subject_type="team_state",
            subject_id=team_state_id, payload={"trigger": trigger},
        )
    except Exception as exc:
        db.finish_job(job_id, "failed", error_code=type(exc).__name__,
                      error_detail=str(exc)[:2000])
        raise
    result = {
        "status": "completed", "job_id": job_id, "cycle_id": cycle_id,
        "team_state_id": team_state_id, "artifact_path": str(dest),
        "manifest_sha256": manifest_sha, "trigger": trigger,
        "source_name": source_name, **quality,
    }
    db.finish_job(job_id, "completed", output_sha256=manifest_sha, metrics=result)
    return result


def import_snapshot(config: RuntimeConfig, db: OpsDB, doc: dict, *, now: datetime | None = None,
                    deadline_lookup=None, element_types: dict | None = None,
                    actor: str = "", reason: str = "", idempotency_key: str = "") -> dict:
    """Importa un snapshot leído por el operador; mismo sello que la captura.

    Se etiqueta `operator_import` (DB y manifest) para que acta/brief reporten la
    procedencia. Devuelve `artifact_path`, que se pasa tal cual a `week acta
    --private-state-path` (sin depender de la ventana de cadencia).
    """
    payload = normalize_import(doc, expected_team_id=config.team_id, now=now,
                               deadline_lookup=deadline_lookup, element_types=element_types)
    # La key del CLI es la key del job: estable aunque `observed_at` se genere con
    # now() y cambie entre reintentos, así que repetir el import no duplica nada.
    job_key = (f"private-import:{config.season}:{actor}:{idempotency_key}"
               if actor and idempotency_key else None)
    result = ingest(config, db, payload, trigger="forced", source_name=SOURCE_IMPORT,
                    job_key=job_key)
    result.setdefault("schema", "mova-private-import-v1")
    if actor and result.get("status") == "completed":
        db.append_audit(
            "team_state_import", correlation_id=None, cycle_id=result["cycle_id"],
            job_id=result["job_id"], subject_type="team_state",
            subject_id=result["team_state_id"],
            payload={"actor": actor, "reason": reason[:300],
                     "idempotency_key": idempotency_key,
                     "fingerprint": result["fingerprint"]},
        )
    return result
