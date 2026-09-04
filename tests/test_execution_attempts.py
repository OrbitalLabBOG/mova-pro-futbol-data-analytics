from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from mova_fpl.data.private_state import validate as validate_private_state
from mova_fpl.ops.browser_contract import (
    assess_pick_team_snapshot,
    assess_transfers_snapshot,
    compile_browser_commands,
    compile_r2_ui_action_plan,
    compile_r3_ui_action_plan,
    plan_position_swaps,
)
from mova_fpl.ops.cli import parser
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB, sha256_json
from mova_fpl.ops.execution import ExecutionService


NOW = datetime(2026, 9, 4, 16, 0, tzinfo=timezone.utc)


def _private_state(order: list[int], *, captain: int, vice: int,
                   observed_at: datetime = NOW - timedelta(minutes=5)) -> dict:
    element_types = {1: 1, 15: 1, **{n: 2 for n in range(2, 7)},
                     **{n: 3 for n in range(7, 12)}, **{n: 4 for n in range(12, 15)}}
    return {
        "schema": "mova-fpl-private-team-state-v1",
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "team_id": 3609854,
        "event": {"id": 3, "deadline_time": "2026-09-04T17:30:00Z"},
        "picks_last_updated": observed_at.isoformat().replace("+00:00", "Z"),
        "picks": [
            {"element": element, "element_type": element_types[element],
             "position": position, "multiplier": 2 if element == captain else
             1 if position <= 11 else 0, "is_captain": element == captain,
             "is_vice_captain": element == vice, "purchase_price": 50,
             "selling_price": 50}
            for position, element in enumerate(order, start=1)
        ],
        "transfers": {"bank": 10, "value": 1000, "limit": 1, "made": 0,
                      "cost": 0, "status": "cost"},
        "chips": [
            {"name": name, "number": 1, "status_for_entry": "available",
             "is_pending": False, "start_event": None, "stop_event": None}
            for name in ("wildcard", "freehit", "bboost", "3xc")
        ],
    }


def _seed_authorized_service(tmp_path: Path) -> tuple[ExecutionService, dict, dict]:
    config = RuntimeConfig(
        ops_db=tmp_path / "db" / "ops.db", artifact_root=tmp_path / "artifacts",
        analytics_root=tmp_path / "analytics", strategic_root=tmp_path / "strategy",
        research_root=tmp_path / "research", host_probe_path=tmp_path / "host.json",
        collector_root=tmp_path / "collector", collector_browser_path=Path("/usr/bin/false"),
        team_id=3609854,
    )
    db = OpsDB(config.ops_db, enforce_version=False)
    db.migrate()
    db.ensure_defaults(mode="autonomous", action_level="A2", compliance_gate="approved",
                       browser_writes=True)
    db.set_control("kill_switch", False, actor="test", reason="hermetic fixture")
    cycle = db.upsert_cycle("2026-27", 3, "2026-09-04T17:30:00+00:00",
                            phase="preflight")
    source_job, _ = db.start_job("tick", "tick:authorized", "corr_authorized", cycle_id=cycle)
    pre = _private_state(list(range(1, 16)), captain=1, vice=2)
    _, pre_quality = validate_private_state(pre, expected_team_id=config.team_id)
    team_id = db.add_team_state(
        job_id=source_job, cycle_id=cycle, observed_at=pre["observed_at"],
        source_name="fpl_authenticated_api", squad=pre["picks"], free_transfers=1,
        bank_tenths=10, chips=pre["chips"], fingerprint=pre_quality["fingerprint"],
        artifact_path="team", manifest_sha256="c" * 64,
    )
    season_plan = db.activate_season_plan("2026-27", {
        "horizon_start_gw": 3, "horizon_end_gw": 8, "assumptions": [],
        "chip_windows": [], "guardrails": {}, "rationale": "fixture",
    }, actor="test", reason="fixture")
    manifest = db.add_cycle_manifest({
        "cycle_id": cycle, "as_of_at": NOW.isoformat(),
        "deadline_at": "2026-09-04T17:30:00+00:00", "phase": "preflight",
        "team_state_id": team_id, "plan_id": season_plan["plan_id"],
        "source_manifest": [], "analytics_manifest": {}, "research_summary": {},
        "artifact_path": "manifest.json",
    })
    current = {
        "season": "2026-27", "gw": 3, "squad_15": list(range(1, 16)),
        "starters": list(range(1, 12)), "captain": 1, "vice_captain": 2,
        "bench_order": list(range(12, 16)), "transfers_in": [], "transfers_out": [],
        "hits": 0, "chip": None, "expected_points": 50.0,
    }
    selected = {**current, "starters": list(range(1, 11)) + [12],
                "bench_order": [15, 11, 13, 14], "captain": 7, "vice_captain": 8,
                "expected_points": 53.0}
    envelope = {
        "schema": "mova-decision-envelope-v1", "policy_version": "test-policy",
        "cycle_id": cycle, "season": "2026-27", "gw": 3, "mode": "autonomous",
        "status": "staged", "selected_candidate_key": "milp_baseline",
        "manifest": {"manifest_id": manifest["manifest_id"],
                     "content_sha256": manifest["content_sha256"]},
        "team_state": {"fingerprint": pre_quality["fingerprint"]},
        "candidates": [
            {"candidate_key": "do_nothing", "label": "current", "decision": current,
             "violations": []},
            {"candidate_key": "milp_baseline", "label": "selected", "decision": selected,
             "violations": []},
        ],
        "validation": {"status": "staged", "blocking_codes": [], "checks": []},
    }
    content_sha = sha256_json(envelope)
    envelope = {**envelope, "envelope_id": f"envelope_{content_sha[:24]}",
                "content_sha256": content_sha}
    artifact = config.artifact_root / "decision-envelopes" / "authorized.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(json.dumps(envelope, sort_keys=True) + "\n", encoding="utf-8")
    db.record_decision_envelope(
        job_id=source_job, envelope=envelope, artifact_path=str(artifact),
        artifact_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
    )
    db.finish_job(source_job, "completed")
    service = ExecutionService(config, db, allow_fixture=True)
    plan = service.preflight(actor="test", reason="authorized fixture",
                             idempotency_key="preflight:authorized", now=NOW)
    return service, plan, pre


def test_live_accessibility_fixture_satisfies_fail_closed_contract():
    snapshot = Path("tests/fixtures/fpl_pick_team_accessibility.txt").read_text()
    assessment = assess_pick_team_snapshot(snapshot)
    assert assessment["status"] == "pass"
    assert assessment["switch_player_controls"] == 15
    assert assess_pick_team_snapshot(snapshot.replace('link "Sign Out"', ""))["status"] == "fail"


def test_live_transfers_accessibility_fixture_satisfies_fail_closed_contract():
    snapshot = Path("tests/fixtures/fpl_transfers_accessibility.txt").read_text()
    assessment = assess_transfers_snapshot(snapshot)
    assert assessment["status"] == "pass"
    assert assessment["remove_player_controls"] == 15
    duplicated_market_controls = snapshot + ('button "Remove player"\n' * 6)
    assert assess_transfers_snapshot(duplicated_market_controls)["status"] == "pass"
    assert assess_transfers_snapshot(snapshot.replace('button "Make Transfers"', ""))[
        "status"
    ] == "fail"


def test_execution_cli_keeps_claim_token_out_of_argv():
    args = parser().parse_args([
        "execute", "finalize", "--execution-id", "execution_1",
        "--post-state", "/tmp/post.json", "--actor", "executor",
        "--reason", "post reload", "--claim-token-stdin",
    ])
    assert args.execute_command == "finalize"
    assert args.claim_token_stdin is True
    with pytest.raises(SystemExit):
        parser().parse_args([
            "execute", "finalize", "--execution-id", "execution_1",
            "--post-state", "/tmp/post.json", "--actor", "executor",
            "--reason", "post reload",
        ])


def test_r2_plan_compiles_to_typed_apply_once_commands(tmp_path: Path):
    service, plan_row, _ = _seed_authorized_service(tmp_path)
    plan = service._load_plan(service.db.execution_claim_source(plan_row["plan_id"])["plan"])
    bundle = compile_browser_commands(plan)
    assert [row["operation"] for row in bundle["commands"]] == [
        "read_private_pre_state", "set_lineup", "set_captain", "set_vice_captain",
        "commit_team_once", "reload_pick_team", "read_private_post_state",
    ]
    assert bundle["failure_policy"]["at_or_after_commit"] == "ambiguous_stop_and_reconcile"


def _r3_bundle(*, chip=None) -> dict:
    plan = {
        "plan_id": "execplan_r3_fixture", "content_sha256": "a" * 64,
        "cycle_id": "2026-27-gw03",
        "authorization": {"status": "authorized", "authorized": True},
        "action": {
            "risk_class": "R3", "expected_pre_team_fingerprint": "b" * 64,
            "expected_post_decision_fingerprint": "c" * 64,
            "exact_diff": {
                "transfers": {"out": [2], "in": [16], "hits": 0},
                "lineup": {"starters": list(range(1, 12)),
                           "bench_order": list(range(12, 16))},
                "captain": {"from": 1, "to": 1},
                "vice_captain": {"from": 2, "to": 2},
                "chip": {"from": None, "to": chip},
            },
        },
    }
    return {**compile_browser_commands(plan), "execution_id": "execution_r3_fixture"}


def _r3_dom_probe() -> dict:
    return {
        "schema": "mova-browser-transfer-dom-probe-v1",
        "contract_version": "fpl-transfers-a11y-2026.09.1", "status": "pass",
        "squad": [
            {"element": element, "position": position,
             "web_name": f"Player {element}"}
            for position, element in enumerate(range(1, 16), start=1)
        ],
        "targets": [{"element": 16, "element_type": 2, "web_name": "Player 16",
                     "team": "Test FC", "price": 45}],
        "controls": {
            "make_transfers": "Make Transfers", "player_search": "Find a player",
            "chip_buttons": ["Wildcard Play", "Free Hit Play"],
        },
    }


def test_r3_contract_binds_identity_economics_hits_and_apply_once():
    pre = _private_state(list(range(1, 16)), captain=1, vice=2)
    bundle = _r3_bundle()
    assert [row["operation"] for row in bundle["commands"]][:6] == [
        "read_private_pre_state", "open_transfers", "stage_exact_transfers",
        "stage_chip", "verify_transfer_preview", "commit_irreversible_once",
    ]
    result = compile_r3_ui_action_plan(
        bundle=bundle, pre_state=pre, dom_probe=_r3_dom_probe(),
        expected_team_id=3609854,
    )
    assert result["status"] == "ready"
    assert result["economics"] == {
        "bank_before": 10, "sale_proceeds": 50, "purchase_cost": 45,
        "bank_after": 15, "free_transfers": 1, "expected_hits": 0,
    }
    assert result["transfers"][0]["out"]["element"] == 2
    assert result["transfers"][0]["in"]["element"] == 16
    assert result["commit"]["max_confirmation_clicks"] == 1
    assert result["failure_policy"]["retry_after_commit"] is False


def test_r3_contract_fails_closed_on_target_or_cost_drift():
    pre = _private_state(list(range(1, 16)), captain=1, vice=2)
    missing = _r3_dom_probe()
    missing["targets"] = []
    result = compile_r3_ui_action_plan(
        bundle=_r3_bundle(), pre_state=pre, dom_probe=missing,
        expected_team_id=3609854,
    )
    assert result["status"] == "blocked"
    assert "TRANSFER_IN_IDENTITY_UNPROVEN" in result["blocking_codes"]
    paid = _r3_bundle()
    next(row for row in paid["commands"] if row["operation"] == "stage_exact_transfers")[
        "hits"
    ] = 1
    result = compile_r3_ui_action_plan(
        bundle=paid, pre_state=pre, dom_probe=_r3_dom_probe(),
        expected_team_id=3609854,
    )
    assert "TRANSFER_HIT_ACCOUNTING_MISMATCH" in result["blocking_codes"]


def _dom_probe(order: list[int]) -> dict:
    return {
        "schema": "mova-browser-dom-probe-v1",
        "contract_version": "fpl-pick-team-a11y-2026.09.1",
        "status": "pass",
        "slots": [
            {"position": position, "element": element,
             "web_name": f"Player {element}", "label_matches": True}
            for position, element in enumerate(order, start=1)
        ],
    }


def _dom_probe_with_captain_controls(order: list[int], captain: int, vice: int) -> dict:
    probe = _dom_probe(order)
    probe["captain_controls"] = {
        "status": "pass",
        "selector_strategy": "player_button_index_then_accessible_checkbox",
        "starters": [
            {
                "position": position,
                "element": element,
                "player_button_index": position - 1,
                "captain_checkbox": True,
                "vice_captain_checkbox": True,
                "captain_checked": element == captain,
                "vice_captain_checked": element == vice,
            }
            for position, element in enumerate(order[:11], start=1)
        ],
    }
    return probe


def test_position_swap_planner_is_minimal_deterministic_and_replayable():
    current = list(range(1, 16))
    target = list(range(1, 11)) + [12, 15, 11, 13, 14]
    swaps = plan_position_swaps(current, target)
    assert [(row["first_position"], row["second_position"]) for row in swaps] == [
        (11, 12), (12, 15), (13, 15), (14, 15),
    ]
    replay = current[:]
    for row in swaps:
        left, right = row["first_index"], row["second_index"]
        replay[left], replay[right] = replay[right], replay[left]
    assert replay == target


def test_r2_ui_plan_blocks_unproven_captain_controls(tmp_path: Path):
    service, plan_row, pre = _seed_authorized_service(tmp_path)
    plan = service._load_plan(service.db.execution_claim_source(plan_row["plan_id"])["plan"])
    bundle = {**compile_browser_commands(plan), "execution_id": "execution_fixture"}
    result = compile_r2_ui_action_plan(
        bundle=bundle, pre_state=pre, dom_probe=_dom_probe(list(range(1, 16))),
        expected_team_id=3609854,
    )
    assert result["status"] == "blocked"
    assert result["blocking_codes"] == [
        "CAPTAIN_CONTROL_UNPROVEN", "VICE_CAPTAIN_CONTROL_UNPROVEN",
    ]
    assert result["commit"]["enabled"] is False
    assert result["swaps"]


def test_r2_ui_plan_is_ready_when_only_lineup_changes(tmp_path: Path):
    service, plan_row, pre = _seed_authorized_service(tmp_path)
    plan = service._load_plan(service.db.execution_claim_source(plan_row["plan_id"])["plan"])
    bundle = {**compile_browser_commands(plan), "execution_id": "execution_fixture"}
    for row in bundle["commands"]:
        if row["operation"] == "set_captain":
            row["element"] = 1
        if row["operation"] == "set_vice_captain":
            row["element"] = 2
    result = compile_r2_ui_action_plan(
        bundle=bundle, pre_state=pre, dom_probe=_dom_probe(list(range(1, 16))),
        expected_team_id=3609854,
    )
    assert result["status"] == "ready"
    assert result["blocking_codes"] == []
    assert result["lineup"]["swap_count"] == 4
    assert result["lineup"]["target_slots"][10] == {
        "position": 11, "element": 12, "web_name": "Player 12",
    }
    assert result["commit"] == {
        "selector": "button", "accessible_name": "Confirm My Choices",
        "max_clicks": 1, "enabled": True,
    }


def test_r2_ui_plan_compiles_observed_captain_controls(tmp_path: Path):
    service, plan_row, pre = _seed_authorized_service(tmp_path)
    plan = service._load_plan(service.db.execution_claim_source(plan_row["plan_id"])["plan"])
    bundle = {**compile_browser_commands(plan), "execution_id": "execution_fixture"}
    result = compile_r2_ui_action_plan(
        bundle=bundle, pre_state=pre,
        dom_probe=_dom_probe_with_captain_controls(list(range(1, 16)), 1, 2),
        expected_team_id=3609854,
    )
    assert result["status"] == "ready"
    assert result["captain"]["action"]["checkbox_accessible_name"] == "Captain"
    assert result["captain"]["action"]["player_button_index"] == 6
    assert result["vice_captain"]["action"]["checkbox_accessible_name"] == "Vice Captain"
    assert result["vice_captain"]["action"]["player_button_index"] == 7


def test_r2_ui_plan_rejects_captain_control_pre_state_drift(tmp_path: Path):
    service, plan_row, pre = _seed_authorized_service(tmp_path)
    plan = service._load_plan(service.db.execution_claim_source(plan_row["plan_id"])["plan"])
    bundle = {**compile_browser_commands(plan), "execution_id": "execution_fixture"}
    with pytest.raises(RuntimeError, match="controles Captain/Vice"):
        compile_r2_ui_action_plan(
            bundle=bundle, pre_state=pre,
            dom_probe=_dom_probe_with_captain_controls(list(range(1, 16)), 3, 2),
            expected_team_id=3609854,
        )


def test_execution_service_compiles_ui_plan_only_after_claim(tmp_path: Path):
    service, plan, pre = _seed_authorized_service(tmp_path)
    prepared = service.prepare(
        plan_id=plan["plan_id"], adapter="fixture", actor="test", reason="E2E",
        idempotency_key="execute:ui-plan", now=NOW,
    )
    with pytest.raises(RuntimeError, match="exige un execution attempt claimed"):
        service.compile_ui_plan(
            execution_id=prepared["execution_id"], pre_state=pre,
            dom_probe=_dom_probe_with_captain_controls(list(range(1, 16)), 1, 2),
        )
    service.claim(
        execution_id=prepared["execution_id"], actor="fixture", reason="claim",
        now=NOW, lease_seconds=600,
    )
    result = service.compile_ui_plan(
        execution_id=prepared["execution_id"], pre_state=pre,
        dom_probe=_dom_probe_with_captain_controls(list(range(1, 16)), 1, 2),
        now=NOW + timedelta(seconds=1),
    )
    assert result["status"] == "ready"
    assert result["execution_id"] == prepared["execution_id"]


def test_execution_status_exposes_browser_driver_capabilities(tmp_path: Path):
    service, _, _ = _seed_authorized_service(tmp_path)
    capabilities = service.status()["browser_driver"]
    assert capabilities["captaincy"]["host_entrypoint_enabled"] is True
    assert capabilities["captaincy"]["autonomy_promoted"] is False
    assert capabilities["lineup"]["contract"] == "implemented"
    assert capabilities["lineup"]["host_entrypoint_enabled"] is False
    assert capabilities["r3"]["host_entrypoint_enabled"] is False


def test_r2_ui_plan_rejects_dom_pre_state_drift(tmp_path: Path):
    service, plan_row, pre = _seed_authorized_service(tmp_path)
    plan = service._load_plan(service.db.execution_claim_source(plan_row["plan_id"])["plan"])
    bundle = {**compile_browser_commands(plan), "execution_id": "execution_fixture"}
    with pytest.raises(RuntimeError, match="orden del DOM"):
        compile_r2_ui_action_plan(
            bundle=bundle, pre_state=pre,
            dom_probe=_dom_probe([2, 1] + list(range(3, 16))),
            expected_team_id=3609854,
        )


def test_apply_once_lifecycle_is_idempotent_and_verifies_post_reload(tmp_path: Path):
    service, plan, pre = _seed_authorized_service(tmp_path)
    prepared = service.prepare(
        plan_id=plan["plan_id"], adapter="fixture", actor="test", reason="E2E",
        idempotency_key="execute:authorized", now=NOW,
    )
    reused = service.prepare(
        plan_id=plan["plan_id"], adapter="fixture", actor="test", reason="E2E",
        idempotency_key="execute:authorized", now=NOW,
    )
    assert reused["reused"] is True and reused["execution_id"] == prepared["execution_id"]
    command_path = Path(prepared["command_path"])
    assert command_path.is_file()
    assert hashlib.sha256(command_path.read_bytes()).hexdigest() == prepared["command_sha256"]
    claim = service.claim(execution_id=prepared["execution_id"], actor="fixture",
                          reason="claim", now=NOW)
    with pytest.raises(RuntimeError, match="no reclamable"):
        service.claim(execution_id=prepared["execution_id"], actor="fixture",
                      reason="duplicate claim", now=NOW)
    service.begin(execution_id=prepared["execution_id"], claim_token=claim["claim_token"],
                  pre_state=pre, actor="fixture", reason="pre-state matched",
                  now=NOW + timedelta(seconds=1))
    post = _private_state(
        list(range(1, 11)) + [12, 15, 11, 13, 14], captain=7, vice=8,
        observed_at=NOW + timedelta(seconds=10),
    )
    result = service.finalize(
        execution_id=prepared["execution_id"], claim_token=claim["claim_token"],
        post_state=post, actor="fixture", reason="post reload", now=NOW + timedelta(seconds=11),
    )
    assert result["status"] == "verified"
    persisted = service.db.execution_attempt(prepared["execution_id"])
    assert [event["to_status"] for event in persisted["events"]] == [
        "prepared", "claimed", "applying", "verified",
    ]
    assert service.db.quick_check() == "ok"


def test_post_reload_mismatch_is_ambiguous_and_opens_p0(tmp_path: Path):
    service, plan, pre = _seed_authorized_service(tmp_path)
    prepared = service.prepare(
        plan_id=plan["plan_id"], adapter="fixture", actor="test", reason="E2E mismatch",
        idempotency_key="execute:mismatch", now=NOW,
    )
    claim = service.claim(execution_id=prepared["execution_id"], actor="fixture",
                          reason="claim", now=NOW)
    service.begin(execution_id=prepared["execution_id"], claim_token=claim["claim_token"],
                  pre_state=pre, actor="fixture", reason="pre-state matched",
                  now=NOW + timedelta(seconds=1))
    result = service.finalize(
        execution_id=prepared["execution_id"], claim_token=claim["claim_token"],
        post_state={**pre, "observed_at": (NOW + timedelta(seconds=10)).isoformat()},
        actor="fixture", reason="mismatch", now=NOW + timedelta(seconds=11),
    )
    assert result["status"] == "ambiguous"
    assert service.db.status()["open_incidents"]["P0"] == 1


def test_runtime_gate_change_blocks_before_claim_without_token(tmp_path: Path):
    service, plan, _ = _seed_authorized_service(tmp_path)
    prepared = service.prepare(
        plan_id=plan["plan_id"], adapter="fixture", actor="test", reason="gate change",
        idempotency_key="execute:gate-change", now=NOW,
    )
    service.db.set_control("kill_switch", True, actor="test", reason="emergency stop")
    result = service.claim(execution_id=prepared["execution_id"], actor="fixture",
                           reason="must block", now=NOW)
    assert result["status"] == "blocked"
    assert "claim_token" not in result
    assert "KILL_SWITCH_ON" in result["blocking_codes"]


def test_runtime_gate_change_after_claim_blocks_before_applying(tmp_path: Path):
    service, plan, pre = _seed_authorized_service(tmp_path)
    prepared = service.prepare(
        plan_id=plan["plan_id"], adapter="fixture", actor="test", reason="late gate change",
        idempotency_key="execute:late-gate-change", now=NOW,
    )
    claim = service.claim(execution_id=prepared["execution_id"], actor="fixture",
                          reason="claim", now=NOW)
    service.db.set_control("kill_switch", True, actor="test", reason="emergency stop")
    result = service.begin(
        execution_id=prepared["execution_id"], claim_token=claim["claim_token"],
        pre_state=pre, actor="fixture", reason="must stop before write",
        now=NOW + timedelta(seconds=1),
    )
    assert result["status"] == "blocked"
    assert "KILL_SWITCH_ON" in result["blocking_codes"]


def test_observed_pre_state_drift_blocks_before_applying(tmp_path: Path):
    service, plan, _ = _seed_authorized_service(tmp_path)
    prepared = service.prepare(
        plan_id=plan["plan_id"], adapter="fixture", actor="test",
        reason="observed state drift", idempotency_key="execute:observed-drift", now=NOW,
    )
    claim = service.claim(execution_id=prepared["execution_id"], actor="fixture",
                          reason="claim", now=NOW)
    changed = _private_state([2, 1] + list(range(3, 16)), captain=1, vice=2)

    result = service.begin(
        execution_id=prepared["execution_id"], claim_token=claim["claim_token"],
        pre_state=changed, actor="fixture", reason="must stop before write",
        now=NOW + timedelta(seconds=1),
    )

    assert result["status"] == "blocked"
    assert "OBSERVED_PRE_STATE_CHANGED" in result["blocking_codes"]


def test_command_bundle_tamper_prevents_claim(tmp_path: Path):
    service, plan, _ = _seed_authorized_service(tmp_path)
    prepared = service.prepare(
        plan_id=plan["plan_id"], adapter="fixture", actor="test", reason="tamper test",
        idempotency_key="execute:tamper", now=NOW,
    )
    command_path = Path(prepared["command_path"])
    command_path.write_text(command_path.read_text() + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="hash físico"):
        service.claim(execution_id=prepared["execution_id"], actor="fixture",
                      reason="must reject", now=NOW)
    assert service.db.execution_attempt(prepared["execution_id"])["status"] == "prepared"
