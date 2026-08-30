"""Audited provisioning of dedicated PostgreSQL LOGIN identities."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

from mova_fpl.ops.db import OpsDB, new_id, sha256_json
from mova_fpl.postgres.store import (
    provision_roles,
    publish_status,
    status as postgres_status,
)


JOB_TYPE = "postgres_role_provision"
SCHEMA = "mova-postgres-role-provision-v1"


def _file_sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_role_provision(config, db: OpsDB, *, actor: str, reason: str,
                       idempotency_key: str) -> dict:
    """Rotate role credentials once per audited identity and seal the result."""
    if not actor.strip() or not reason.strip() or not idempotency_key.strip():
        raise ValueError("actor, reason e idempotency_key son obligatorios")
    config.validate_postgres_roles()
    key = f"postgres-role-provision:{idempotency_key}"
    input_sha = sha256_json({
        "actor": actor.strip(), "reason": reason.strip(), "key": key,
        "app_user": config.postgres_app_user,
        "readonly_user": config.postgres_readonly_user,
    })
    cycle_id = (db.status().get("cycle") or {}).get("cycle_id")
    job_id, reused = db.start_job(
        JOB_TYPE, key, new_id("corr"), cycle_id=cycle_id,
        input_sha256=input_sha,
    )
    if reused:
        row = db.get_job_by_key(key) or {}
        if row.get("input_sha256") != input_sha:
            raise ValueError("idempotency_key reutilizada con identidad o razón distinta")
        metrics = json.loads(row.get("metrics_json") or "{}")
        return {"status": "reused", "job_id": job_id,
                "job_status": row.get("status"), **metrics}
    try:
        separation = provision_roles(config)
        if separation.get("status") != "pass":
            raise RuntimeError("PostgreSQL role separation verification failed")
        full_status = postgres_status(config)
        publish_status(config, full_status)
        evidence = {
            "schema": SCHEMA,
            "provision_id": new_id("pgroles"),
            "job_id": job_id,
            "actor": actor.strip(),
            "reason": reason.strip(),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "role_separation": separation,
        }
        evidence["content_sha256"] = sha256_json(evidence)
        target = (config.artifact_root / "postgres-role-provision" /
                  f"{evidence['provision_id']}.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
        metrics = {
            "provision_id": evidence["provision_id"],
            "role_status": "pass",
            "app_user": separation["app"]["current_user"],
            "readonly_user": separation["readonly"]["current_user"],
            "secrets_distinct": separation["secrets_distinct"],
            "migration_count": len(full_status.get("migrations") or []),
            "read_parity": (full_status.get("read_parity") or {}).get("status"),
            "artifact_path": str(target),
            "artifact_sha256": _file_sha(target),
            "content_sha256": evidence["content_sha256"],
        }
        db.finish_job(job_id, "completed", output_sha256=evidence["content_sha256"],
                      metrics=metrics)
        return {"status": "completed", "job_id": job_id, **metrics}
    except Exception as exc:
        db.finish_job(job_id, "failed", error_code=type(exc).__name__,
                      error_detail=str(exc)[:2000],
                      metrics={"role_status": "fail"})
        raise
