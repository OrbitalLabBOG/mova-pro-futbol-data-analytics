"""Audited orchestration for the PostgreSQL read-path cutover drill."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from mova_fpl.ops.db import OpsDB, new_id, sha256_json
from mova_fpl.postgres.cutover import JOB_TYPE, SCHEMA, ReadCutoverSession
from mova_fpl.postgres.importer import verify_shadow
from mova_fpl.postgres.read_repository import PostgresReadRepository, SQLiteReadRepository
from mova_fpl.postgres.store import connect


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_cutover_drill(config, db: OpsDB, *, actor: str, reason: str,
                      idempotency_key: str) -> dict:
    """Exercise PostgreSQL reads and prove rollback without changing the writer."""
    if not actor.strip() or not reason.strip() or not idempotency_key.strip():
        raise ValueError("actor, reason e idempotency_key son obligatorios")
    key = f"postgres-read-cutover-drill:{idempotency_key}"
    cycle = (db.status().get("cycle") or {}).get("cycle_id")
    input_sha = sha256_json({"actor": actor.strip(), "reason": reason.strip(), "key": key})
    job_id, reused = db.start_job(
        JOB_TYPE, key, new_id("corr"), cycle_id=cycle,
        input_sha256=input_sha,
    )
    if reused:
        row = db.get_job_by_key(key) or {}
        if row.get("input_sha256") != input_sha:
            raise ValueError("idempotency_key reutilizada con actor o razón distintos")
        metrics = json.loads(row.get("metrics_json") or "{}")
        return {"status": "reused", "job_id": job_id,
                "job_status": row.get("status"), **metrics}
    rollback_verified = False
    try:
        verification = verify_shadow(config)
        if verification.get("status") != "pass":
            raise RuntimeError("latest PostgreSQL import does not pass full verification")
        import_run_id = str(verification["import_run_id"])
        with connect(config, autocommit=True) as pg:
            latest = pg.execute(
                "select artifact_path from mova_meta.import_runs where import_run_id=%s",
                (import_run_id,),
            ).fetchone()
            if not latest:
                raise RuntimeError("verified import disappeared before drill")
            root = Path(str(latest["artifact_path"]))
            sqlite_repo = SQLiteReadRepository({
                "ops": root / config.ops_db.name,
                "canonical": root / config.canonical_db.name,
                "trace": root / config.trace_db.name,
            })
            drill = ReadCutoverSession(
                sqlite_repo, PostgresReadRepository(pg)
            ).exercise()
            rollback_verified = drill["rollback_verified"] is True
        evidence = {
            "schema": SCHEMA,
            "drill_id": new_id("pgcutover"),
            "job_id": job_id,
            "import_run_id": import_run_id,
            "actor": actor.strip(),
            "reason": reason.strip(),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "full_verification": {
                "status": verification["status"],
                "all_targets_checked": verification["all_targets_checked"],
                "checked_tables": verification["read_parity"]["checked_tables"],
                "failed_tables": verification["read_parity"]["failed_tables"],
                "content_sha256": verification["read_parity"]["content_sha256"],
            },
            **drill,
        }
        evidence["content_sha256"] = sha256_json(evidence)
        target = config.artifact_root / "postgres-cutover-drills" / f"{evidence['drill_id']}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
        if drill["status"] != "pass":
            raise RuntimeError("read cutover/rollback drill failed")
        metrics = {
            "drill_status": "pass", "drill_id": evidence["drill_id"],
            "import_run_id": import_run_id, "checked_tables": len(drill["checks"]),
            "rollback_verified": True, "runtime_writer_mutated": False,
            "artifact_path": str(target), "artifact_sha256": _file_sha(target),
            "content_sha256": evidence["content_sha256"],
        }
        db.finish_job(job_id, "completed", output_sha256=evidence["content_sha256"],
                      metrics=metrics)
        return {"status": "completed", "job_id": job_id, **metrics}
    except Exception as exc:
        db.finish_job(job_id, "failed", error_code=type(exc).__name__,
                      error_detail=str(exc)[:2000],
                      metrics={"drill_status": "fail",
                               "rollback_verified": rollback_verified,
                               "runtime_writer_mutated": False})
        raise
