"""Ingreso auditable del estado privado sanitizado por el browser aislado."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from mova_fpl.data.private_state import seal, validate
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB, new_id
from mova_fpl.ops.tick import phase_for


def ingest(config: RuntimeConfig, db: OpsDB, payload: dict) -> dict:
    normalized, quality = validate(payload, expected_team_id=config.team_id)
    gw = int(normalized["event"]["id"])
    deadline = str(normalized["event"]["deadline_time"])
    cycle_id = db.upsert_cycle(
        config.season, gw, deadline,
        phase=phase_for(deadline, datetime.now(timezone.utc)),
    )
    fingerprint = quality["fingerprint"]
    correlation_id = new_id("corr")
    job_id, reused = db.start_job(
        "private_team_state",
        f"private-team-state:{config.season}:{gw}:{fingerprint}",
        correlation_id,
        cycle_id=cycle_id,
        input_sha256=fingerprint,
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
    except Exception as exc:
        db.finish_job(job_id, "failed", error_code=type(exc).__name__,
                      error_detail=str(exc)[:2000])
        raise
    result = {
        "status": "completed", "job_id": job_id, "cycle_id": cycle_id,
        "team_state_id": team_state_id, "artifact_path": str(dest),
        "manifest_sha256": manifest_sha, **quality,
    }
    db.finish_job(job_id, "completed", output_sha256=manifest_sha, metrics=result)
    return result
