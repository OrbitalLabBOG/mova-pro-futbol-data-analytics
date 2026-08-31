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
SCENARIOS = {
    "api_recovery": {
        "checks": {
            "ready_before", "unavailable_during", "ready_after",
            "revision_unchanged", "sqlite_integrity_after",
        },
        "max_downtime_seconds": 120,
    },
    "postgres_recovery": {
        "checks": {
            "postgres_ready_before", "postgres_unavailable_during",
            "api_ready_during", "sqlite_integrity_during",
            "postgres_ready_after", "postgres_parity_after",
            "revision_unchanged", "team_state_unchanged",
        },
        "max_downtime_seconds": 180,
    },
    "browser_recovery": {
        "checks": {
            "browser_ready_before", "session_authenticated_before",
            "browser_unavailable_during", "browser_ready_after",
            "session_authenticated_after", "revision_unchanged",
            "team_state_unchanged", "controls_fail_closed",
            "initial_service_state_restored",
        },
        "max_downtime_seconds": 180,
    },
    "combined_recovery": {
        "checks": {
            "services_ready_before", "all_services_unavailable_during",
            "sqlite_integrity_during", "stored_team_state_unchanged_during",
            "postgres_ready_after", "postgres_parity_after", "api_ready_after",
            "browser_ready_after", "session_authenticated_after",
            "revisions_unchanged", "private_state_unchanged",
            "controls_fail_closed", "initial_browser_state_restored",
        },
        "max_downtime_seconds": 240,
    },
    "reboot_recovery": {
        "checks": {
            "boot_id_changed", "stack_ready_after", "timers_active_after",
            "scheduler_resumed", "sqlite_integrity_after", "postgres_parity_after",
            "revision_unchanged", "controls_fail_closed", "team_state_unchanged",
            "idempotency_unique", "backup_prepared",
        },
        "max_downtime_seconds": 1200,
    },
}
MAX_BYTES = 64 * 1024


def _time(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("host drill timestamp requires timezone")
    return parsed.astimezone(timezone.utc)


def validate(payload: dict, *, expected_revision: str,
             expected_scenario: str | None = None) -> dict:
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ValueError("invalid host drill schema")
    scenario = str(payload.get("scenario") or "")
    contract = SCENARIOS.get(scenario)
    if not contract:
        raise ValueError("unsupported host drill scenario")
    if expected_scenario is not None and scenario != expected_scenario:
        raise ValueError("host drill scenario mismatch")
    if set(payload.get("checks") or {}) != contract["checks"]:
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
    if (finished < started
            or not 0 <= duration <= int(contract["max_downtime_seconds"])):
        raise ValueError("host drill timing invalid")
    if payload.get("fpl_state_mutated") is not False:
        raise ValueError("host drill must prove FPL state remained untouched")
    normalized = {
        "schema": SCHEMA, "scenario": scenario, "status": "pass",
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": finished.isoformat(timespec="seconds"),
        "downtime_seconds": duration, "revision": revision, "checks": checks,
        "fpl_state_mutated": False, "host_service_restarted": True,
    }
    if scenario in {
        "postgres_recovery", "browser_recovery", "combined_recovery", "reboot_recovery",
    }:
        before = str(payload.get("team_state_sha256_before") or "")
        after = str(payload.get("team_state_sha256_after") or "")
        if (len(before) != 64 or any(char not in "0123456789abcdef" for char in before)
                or before != after):
            raise ValueError("host drill team state fingerprint mismatch")
        normalized.update({
            "team_state_sha256_before": before,
            "team_state_sha256_after": after,
        })
    return normalized


def import_evidence(config: RuntimeConfig, path: Path, *,
                    expected_scenario: str | None = None) -> dict:
    inbox = (config.artifact_root / "host-drills" / "inbox").resolve()
    source = path.resolve()
    if inbox not in source.parents or not source.is_file() or source.is_symlink():
        raise ValueError("host drill evidence must be a regular inbox file")
    raw = source.read_bytes()
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("host drill evidence size invalid")
    payload = validate(
        json.loads(raw), expected_revision=config.git_sha,
        expected_scenario=expected_scenario,
    )
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
