"""Ingreso auditable del estado privado sanitizado por el browser aislado."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from mova_fpl.data.private_state import seal, validate
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB, new_id, sha256_json
from mova_fpl.ops.schedule import phase_for


def ingest(config: RuntimeConfig, db: OpsDB, payload: dict, *,
           trigger: str = "scheduled") -> dict:
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
        f"private-team-state:{config.season}:{gw}:{observation_sha}",
        correlation_id,
        cycle_id=cycle_id,
        input_sha256=observation_sha,
    )
    if reused:
        return {"status": "reused", "job_id": job_id, "cycle_id": cycle_id,
                "fingerprint": fingerprint}
    try:
        dest, manifest, normalized = seal(
            normalized,
            config.season,
            config.artifact_root / "team_state",
            expected_team_id=config.team_id,
        )
        manifest_sha = hashlib.sha256((dest / "manifest.json").read_bytes()).hexdigest()
        team_state_id = db.add_team_state(
            job_id=job_id,
            cycle_id=cycle_id,
            observed_at=normalized["observed_at"],
            source_name="fpl_authenticated_api",
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
        "manifest_sha256": manifest_sha, "trigger": trigger, **quality,
    }
    db.finish_job(job_id, "completed", output_sha256=manifest_sha, metrics=result)
    return result
