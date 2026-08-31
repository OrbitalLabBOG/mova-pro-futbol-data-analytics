from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mova_fpl.ops.browser_driver import DRIVER_CONTRACT_VERSION, R3_DRIVER_CONTRACT_VERSION
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


def _captaincy_probe(service: ExecutionService, *, valid: bool = True) -> Path:
    subchecks = {
        "eleven_starter_sheets": valid, "semantic_checkboxes": True,
        "one_captain": True, "one_vice_captain": True,
        "captain_matches_api": True, "vice_captain_matches_api": True,
    }
    probe = {
        "schema": "mova-browser-dom-probe-v1",
        "contract_version": "fpl-pick-team-a11y-2026.08.2",
        "observed_at": NOW.isoformat(), "team_id": service.config.team_id,
        "status": "pass" if valid else "fail",
        "checks": {
            "signed_in": valid, "fifteen_api_picks": True,
            "fifteen_player_controls": True, "fifteen_switch_controls": True,
            "positional_order_matches": True, "captain_controls": valid,
        },
        "slots": [],
        "captain_controls": {
            "status": "pass" if valid else "fail",
            "selector_strategy": "player_button_index_then_accessible_checkbox",
            "checks": subchecks,
            "starters": [
                {"position": index + 1, "element": index + 1,
                 "player_button_index": index, "captain_checkbox": True,
                 "vice_captain_checkbox": True, "captain_checked": index == 0,
                 "vice_captain_checked": index == 1}
                for index in range(11)
            ],
        },
    }
    path = service.config.artifact_root / "browser-probes" / "captaincy.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(probe) + "\n")
    return path


def _lineup_probe(service: ExecutionService, *, valid: bool = True) -> Path:
    path = _captaincy_probe(service, valid=valid)
    probe = json.loads(path.read_text())
    probe["slots"] = [
        {
            "position": index + 1, "element": index + 1,
            "web_name": f"Player {index + 1}", "player_button_index": index,
            "switch_button_index": index, "label_matches": valid,
        }
        for index in range(15)
    ]
    path.write_text(json.dumps(probe) + "\n")
    return path


def _r3_probe(service: ExecutionService, *, valid: bool = True) -> Path:
    checks = {
        "signed_in": valid, "fifteen_api_picks": True,
        "squad_remove_controls_present": True, "squad_labels_complete": True,
        "targets_complete": True, "make_transfers": True, "player_search": True,
        "wildcard": True, "free_hit": True,
    }
    probe = {
        "schema": "mova-browser-transfer-dom-probe-v1",
        "contract_version": "fpl-transfers-a11y-2026.08.1",
        "observed_at": NOW.isoformat(), "team_id": service.config.team_id,
        "status": "pass" if valid else "fail", "checks": checks,
        "squad": [
            {"element": index + 1, "position": index + 1,
             "web_name": f"Player {index + 1}"}
            for index in range(15)
        ],
        "targets": [{
            "element": 101, "element_type": 3, "web_name": "Target",
            "team": "ARS", "price": 75,
        }],
        "controls": {
            "make_transfers": "Make Transfers", "player_search": "Find a player",
            "chip_buttons": ["Wildcard Play", "Free Hit Play"],
        },
    }
    path = service.config.artifact_root / "browser-probes" / "r3.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(probe) + "\n")
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


def test_live_captaincy_probe_is_sealed_without_browser_writes(tmp_path: Path):
    service, cycle_id = _service(tmp_path)
    result = service.record_captaincy_probe(
        source_file=_captaincy_probe(service), cycle_id=cycle_id, actor="test",
        reason="live read-only probe", idempotency_key="captaincy-probe:gw3", now=NOW,
    )
    assert result["status"] == "passed"
    assert result["browser_writes_performed"] is False
    evidence = json.loads(Path(result["evidence_path"]).read_text())
    assert evidence["writes_attempted"] is False
    assert len(evidence["checks"]) == 12
    assert service.status()["browser_driver"]["captaincy"]["observed_rehearsals"] == 1


def test_failed_captaincy_probe_cannot_be_sealed_as_passed(tmp_path: Path):
    service, cycle_id = _service(tmp_path)
    with pytest.raises(ValueError, match="no supera"):
        service.record_captaincy_probe(
            source_file=_captaincy_probe(service, valid=False), cycle_id=cycle_id,
            actor="test", reason="failed probe", idempotency_key="captaincy-probe:failed",
            now=NOW,
        )


@pytest.mark.parametrize(
    ("capability", "probe_factory", "contract"),
    [
        ("lineup", _lineup_probe, DRIVER_CONTRACT_VERSION),
        ("r3", _r3_probe, R3_DRIVER_CONTRACT_VERSION),
    ],
)
def test_capability_probe_is_allowlisted_sealed_and_counted(
    tmp_path: Path, capability: str, probe_factory, contract: str,
):
    service, cycle_id = _service(tmp_path)
    result = service.record_capability_probe(
        source_file=probe_factory(service), cycle_id=cycle_id,
        capability=capability, actor="test", reason="live read-only selector proof",
        idempotency_key=f"probe:{capability}:gw3", now=NOW,
    )
    assert result["status"] == "passed"
    assert result["contract_version"] == contract
    assert result["browser_writes_performed"] is False
    evidence = json.loads(Path(result["evidence_path"]).read_text())
    assert evidence["capability"] == capability
    assert evidence["writes_attempted"] is False
    assert service.status()["browser_driver"][capability]["observed_rehearsals"] == 1


def test_capability_probe_rejects_failed_or_incomplete_sources(tmp_path: Path):
    service, cycle_id = _service(tmp_path)
    with pytest.raises(ValueError, match="lineup no supera"):
        service.record_capability_probe(
            source_file=_lineup_probe(service, valid=False), cycle_id=cycle_id,
            capability="lineup", actor="test", reason="invalid",
            idempotency_key="probe:lineup:failed", now=NOW,
        )
    r3 = _r3_probe(service)
    payload = json.loads(r3.read_text())
    payload["targets"] = []
    r3.write_text(json.dumps(payload) + "\n")
    with pytest.raises(ValueError, match="R3 no supera"):
        service.record_capability_probe(
            source_file=r3, cycle_id=cycle_id, capability="r3", actor="test",
            reason="missing target", idempotency_key="probe:r3:empty", now=NOW,
        )


def test_cli_parses_capability_probe_command():
    parsed = parser().parse_args([
        "execute", "rehearsal-capability-probe", "--source", "probe.json",
        "--cycle-id", "2026-27-gw03", "--capability", "r3",
        "--actor", "operator", "--reason", "read only",
        "--idempotency-key", "probe:r3:gw3",
    ])
    assert parsed.execute_command == "rehearsal-capability-probe"
    assert parsed.capability == "r3"
