from __future__ import annotations

import json
from pathlib import Path

import pytest

from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.host_drill import import_evidence, validate


def _payload() -> dict:
    return {
        "schema": "mova-host-drill-v1", "scenario": "api_recovery", "status": "pass",
        "started_at": "2026-08-31T01:00:00Z",
        "finished_at": "2026-08-31T01:00:08Z", "downtime_seconds": 8,
        "revision": "abc1234",
        "checks": {
            "ready_before": True, "unavailable_during": True, "ready_after": True,
            "revision_unchanged": True, "sqlite_integrity_after": True,
        },
        "fpl_state_mutated": False,
    }


def test_host_drill_import_is_allowlisted_atomic_and_consumes_inbox(tmp_path: Path):
    config = RuntimeConfig(artifact_root=tmp_path / "artifacts", git_sha="abc1234")
    source = config.artifact_root / "host-drills" / "inbox" / "api.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps(_payload()), encoding="utf-8")

    result = import_evidence(config, source)

    assert result["status"] == "pass"
    assert result["fpl_state_mutated"] is False
    assert not source.exists()
    imported = Path(result["artifact_path"])
    assert imported.is_file()
    persisted = json.loads(imported.read_text(encoding="utf-8"))
    assert persisted["checks"] == _payload()["checks"]
    assert set(persisted) == {
        "schema", "scenario", "status", "started_at", "finished_at",
        "downtime_seconds", "revision", "checks", "fpl_state_mutated",
        "host_service_restarted",
    }


@pytest.mark.parametrize("mutation", [
    {"revision": "wrong"},
    {"status": "fail"},
    {"fpl_state_mutated": True},
    {"downtime_seconds": 121},
    {"checks": {"ready_before": True}},
])
def test_host_drill_rejects_untrusted_or_failed_evidence(mutation):
    payload = {**_payload(), **mutation}
    with pytest.raises(ValueError):
        validate(payload, expected_revision="abc1234")


def test_host_drill_rejects_files_outside_inbox(tmp_path: Path):
    config = RuntimeConfig(artifact_root=tmp_path / "artifacts", git_sha="abc1234")
    source = tmp_path / "api.json"
    source.write_text(json.dumps(_payload()), encoding="utf-8")
    with pytest.raises(ValueError, match="inbox"):
        import_evidence(config, source)


def test_host_script_has_recovery_trap_and_never_mentions_fpl_writes():
    script = Path("deploy/bin/api-recovery-drill.sh").read_text(encoding="utf-8")
    assert "trap recover_api EXIT" in script
    assert "flock -n 9" in script
    assert "drill host-status" in script
    assert "docker compose stop --timeout 10 api" in script
    assert "fpl_state_mutated" in script
    assert not any(token in script for token in ("my-team", "transfers", "agent-browser"))
