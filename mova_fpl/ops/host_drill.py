"""Importador allowlisted para evidencia de chaos drills ejecutados por el host."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from mova_fpl.ops.config import RuntimeConfig

SCHEMA = "mova-host-drill-v1"
REQUIRED_CHECKS = {
    "ready_before", "unavailable_during", "ready_after",
    "revision_unchanged", "sqlite_integrity_after",
}
MAX_BYTES = 64 * 1024


def _time(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("host drill timestamp requires timezone")
    return parsed.astimezone(timezone.utc)


def validate(payload: dict, *, expected_revision: str) -> dict:
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ValueError("invalid host drill schema")
    if payload.get("scenario") != "api_recovery":
        raise ValueError("unsupported host drill scenario")
    if set(payload.get("checks") or {}) != REQUIRED_CHECKS:
        raise ValueError("host drill checks must match allowlist")
    checks = {key: bool(value) for key, value in payload["checks"].items()}
    if not all(checks.values()) or payload.get("status") != "pass":
        raise ValueError("host drill did not pass all checks")
    revision = str(payload.get("revision") or "")
    if revision != expected_revision or not revision.isalnum() or len(revision) > 40:
        raise ValueError("host drill revision mismatch")
    started = _time(payload.get("started_at"))
    finished = _time(payload.get("finished_at"))
    duration = int(payload.get("downtime_seconds") or 0)
    if finished < started or not 0 <= duration <= 120:
        raise ValueError("host drill timing invalid")
    if payload.get("fpl_state_mutated") is not False:
        raise ValueError("host drill must prove FPL state remained untouched")
    return {
        "schema": SCHEMA, "scenario": "api_recovery", "status": "pass",
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": finished.isoformat(timespec="seconds"),
        "downtime_seconds": duration, "revision": revision, "checks": checks,
        "fpl_state_mutated": False, "host_service_restarted": True,
    }


def import_evidence(config: RuntimeConfig, path: Path) -> dict:
    inbox = (config.artifact_root / "host-drills" / "inbox").resolve()
    source = path.resolve()
    if inbox not in source.parents or not source.is_file() or source.is_symlink():
        raise ValueError("host drill evidence must be a regular inbox file")
    raw = source.read_bytes()
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("host drill evidence size invalid")
    payload = validate(json.loads(raw), expected_revision=config.git_sha)
    canonical = (json.dumps(payload, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":")) + "\n").encode()
    digest = hashlib.sha256(canonical).hexdigest()
    destination = config.artifact_root / "host-drills" / "imported" / f"{digest}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        fd, temporary = tempfile.mkstemp(prefix=".host-drill-", dir=destination.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(canonical)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    source.unlink()
    return {**payload, "artifact_path": str(destination), "artifact_sha256": digest}
