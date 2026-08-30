from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mova_fpl.ops.browser_driver import DRIVER_CONTRACT_VERSION
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.cli import parser
from mova_fpl.ops.db import OpsDB, sha256_json
from mova_fpl.ops.execution import ExecutionService


NOW = datetime(2026, 8, 30, 23, 0, tzinfo=timezone.utc)


def _service(tmp_path: Path) -> tuple[ExecutionService, str]:
    config = RuntimeConfig(
        ops_db=tmp_path / "db" / "ops.db",
        artifact_root=tmp_path / "artifacts",
    )
    db = OpsDB(config.ops_db, enforce_version=False)
    db.migrate()
    cycle_id = db.upsert_cycle(
        "2026-27", 3, "2026-09-04T17:30:00+00:00", phase="preflight"
    )
    return ExecutionService(config, db), cycle_id


def _evidence(service: ExecutionService, cycle_id: str, *, passed: bool = True,
              writes_attempted: bool = False, suffix: str = "one") -> Path:
    source = service.config.artifact_root / "host-probes" / f"{suffix}.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b'{"probe":"read-only"}\n')
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    payload = {
        "schema": "mova-browser-rehearsal-evidence-v1",
        "cycle_id": cycle_id,
        "capability": "captaincy",
        "contract_version": DRIVER_CONTRACT_VERSION,
        "observed_at": NOW.isoformat(),
        "mode": "read_only_probe",
        "status": "passed" if passed else "failed",
        "writes_attempted": writes_attempted,
        "checks": [{"code": f"semantic_controls_{suffix}", "passed": passed}],
        "source_artifacts": [{"path": f"host-probes/{suffix}.json", "sha256": source_sha}],
    }
    payload["content_sha256"] = sha256_json(payload)
    path = service.config.artifact_root / "browser-rehearsals" / f"{suffix}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_rehearsal_is_counted_once_per_gameweek_and_contract(tmp_path: Path):
    service, cycle_id = _service(tmp_path)
    first = service.record_rehearsal(
        evidence_file=_evidence(service, cycle_id), actor="test", reason="read only",
        idempotency_key="rehearsal:gw3:captaincy", now=NOW,
    )
    same_key = service.record_rehearsal(
        evidence_file=first["evidence_path"], actor="test", reason="read only",
        idempotency_key="rehearsal:gw3:captaincy", now=NOW,
    )
    duplicate_gw = service.record_rehearsal(
        evidence_file=_evidence(service, cycle_id, suffix="two"), actor="test",
        reason="retry must not inflate", idempotency_key="rehearsal:gw3:captaincy:retry",
        now=NOW,
    )
    assert first["reused"] is False
    assert same_key["reused"] is True
    assert duplicate_gw["reused"] is True
    assert duplicate_gw["deduplicated_by"] == "evidence_or_gameweek"
    assert service.status()["browser_driver"]["captaincy"]["observed_rehearsals"] == 1


def test_failed_rehearsal_is_audited_but_not_counted(tmp_path: Path):
    service, cycle_id = _service(tmp_path)
    result = service.record_rehearsal(
        evidence_file=_evidence(service, cycle_id, passed=False), actor="test",
        reason="failed validation", idempotency_key="rehearsal:failed", now=NOW,
    )
    assert result["status"] == "failed"
    assert service.status()["browser_driver"]["captaincy"]["observed_rehearsals"] == 0


def test_write_attempt_and_contract_mismatch_are_rejected(tmp_path: Path):
    service, cycle_id = _service(tmp_path)
    write_path = _evidence(service, cycle_id, writes_attempted=True)
    with pytest.raises(ValueError, match="escritura"):
        service.record_rehearsal(
            evidence_file=write_path, actor="test", reason="unsafe",
            idempotency_key="rehearsal:unsafe", now=NOW,
        )

    path = _evidence(service, cycle_id, suffix="wrong-contract")
    payload = json.loads(path.read_text())
    payload["contract_version"] = "stale-contract"
    unsigned = {key: value for key, value in payload.items() if key != "content_sha256"}
    payload["content_sha256"] = sha256_json(unsigned)
    path.write_text(json.dumps(payload) + "\n")
    with pytest.raises(ValueError, match="contract_version"):
        service.record_rehearsal(
            evidence_file=path, actor="test", reason="stale",
            idempotency_key="rehearsal:stale", now=NOW,
        )


def test_rehearsal_evidence_must_live_under_artifact_root(tmp_path: Path):
    service, cycle_id = _service(tmp_path)
    outside = tmp_path / "outside.json"
    source = _evidence(service, cycle_id)
    outside.write_bytes(source.read_bytes())
    with pytest.raises(ValueError, match="artifact root"):
        service.record_rehearsal(
            evidence_file=outside, actor="test", reason="outside",
            idempotency_key="rehearsal:outside", now=NOW,
        )


def test_cli_and_metrics_expose_rehearsal_ledger(tmp_path: Path):
    parsed = parser().parse_args([
        "execute", "rehearsal", "--file", "evidence.json", "--actor", "operator",
        "--reason", "read only proof", "--idempotency-key", "gw3:captaincy",
    ])
    assert parsed.execute_command == "rehearsal"
    service, cycle_id = _service(tmp_path)
    service.record_rehearsal(
        evidence_file=_evidence(service, cycle_id), actor="test", reason="metrics",
        idempotency_key="rehearsal:metrics", now=NOW,
    )
    metrics = service.db.prometheus()
    assert 'mova_browser_rehearsals{capability="captaincy"} 1' in metrics
    assert 'mova_browser_rehearsals{capability="lineup"} 0' in metrics


def test_missing_or_tampered_source_artifact_is_rejected(tmp_path: Path):
    service, cycle_id = _service(tmp_path)
    path = _evidence(service, cycle_id)
    source = service.config.artifact_root / "host-probes" / "one.json"
    source.write_text('{"probe":"tampered"}\n')
    with pytest.raises(ValueError, match="sha256"):
        service.record_rehearsal(
            evidence_file=path, actor="test", reason="tampered source",
            idempotency_key="rehearsal:tampered", now=NOW,
        )
