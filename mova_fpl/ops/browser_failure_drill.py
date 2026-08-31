"""Hermetic rehearsal for DOM drift and ambiguous browser saves.

The drill uses disposable SQLite databases and fixture-only execution adapters.
It never connects to FPL, a browser, CDP, or the production control plane.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile

from mova_fpl.data.private_state import validate as validate_private_state
from mova_fpl.ops.browser_contract import (
    DOM_CONTRACT_VERSION,
    DOM_PROBE_SCHEMA,
    assess_pick_team_snapshot,
    compile_browser_commands,
    compile_r2_ui_action_plan,
)
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB, sha256_json
from mova_fpl.ops.execution import ExecutionService


SCHEMA = "mova-browser-failure-drill-v1"
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


def _seed(root: Path) -> tuple[ExecutionService, dict, dict]:
    config = RuntimeConfig(
        ops_db=root / "db" / "ops.db", artifact_root=root / "artifacts",
        analytics_root=root / "analytics", strategic_root=root / "strategy",
        research_root=root / "research", host_probe_path=root / "host.json",
        collector_root=root / "collector", collector_browser_path=Path("/usr/bin/false"),
        team_id=3609854,
    )
    db = OpsDB(config.ops_db, enforce_version=False)
    db.migrate()
    db.ensure_defaults(mode="autonomous", action_level="A2", compliance_gate="approved",
                       browser_writes=True)
    db.set_control("kill_switch", False, actor="drill", reason="disposable fixture")
    cycle = db.upsert_cycle("2026-27", 3, "2026-09-04T17:30:00+00:00",
                            phase="preflight")
    source_job, _ = db.start_job("tick", f"tick:{root.name}", f"corr_{root.name}",
                                 cycle_id=cycle)
    pre = _private_state(list(range(1, 16)), captain=1, vice=2)
    _, quality = validate_private_state(pre, expected_team_id=config.team_id)
    team_state_id = db.add_team_state(
        job_id=source_job, cycle_id=cycle, observed_at=pre["observed_at"],
        source_name="fixture", squad=pre["picks"], free_transfers=1,
        bank_tenths=10, chips=pre["chips"], fingerprint=quality["fingerprint"],
        artifact_path="fixture", manifest_sha256="c" * 64,
    )
    season_plan = db.activate_season_plan("2026-27", {
        "horizon_start_gw": 3, "horizon_end_gw": 8, "assumptions": [],
        "chip_windows": [], "guardrails": {}, "rationale": "fixture",
    }, actor="drill", reason="disposable fixture")
    manifest = db.add_cycle_manifest({
        "cycle_id": cycle, "as_of_at": NOW.isoformat(),
        "deadline_at": "2026-09-04T17:30:00+00:00", "phase": "preflight",
        "team_state_id": team_state_id, "plan_id": season_plan["plan_id"],
        "source_manifest": [], "analytics_manifest": {}, "research_summary": {},
        "artifact_path": "fixture-manifest.json",
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
        "schema": "mova-decision-envelope-v1", "policy_version": "drill-policy",
        "cycle_id": cycle, "season": "2026-27", "gw": 3, "mode": "autonomous",
        "status": "staged", "selected_candidate_key": "fixture_selected",
        "manifest": {"manifest_id": manifest["manifest_id"],
                     "content_sha256": manifest["content_sha256"]},
        "team_state": {"fingerprint": quality["fingerprint"]},
        "candidates": [
            {"candidate_key": "do_nothing", "label": "current", "decision": current,
             "violations": []},
            {"candidate_key": "fixture_selected", "label": "selected",
             "decision": selected, "violations": []},
        ],
        "validation": {"status": "staged", "blocking_codes": [], "checks": []},
    }
    content_sha = sha256_json(envelope)
    envelope = {**envelope, "envelope_id": f"envelope_{content_sha[:24]}",
                "content_sha256": content_sha}
    artifact = config.artifact_root / "decision-envelopes" / "fixture.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(json.dumps(envelope, sort_keys=True) + "\n", encoding="utf-8")
    db.record_decision_envelope(
        job_id=source_job, envelope=envelope, artifact_path=str(artifact),
        artifact_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
    )
    db.finish_job(source_job, "completed")
    service = ExecutionService(config, db, allow_fixture=True)
    plan = service.preflight(actor="drill", reason="disposable fixture",
                             idempotency_key=f"preflight:{root.name}", now=NOW)
    return service, plan, pre


def _dom_probe(order: list[int]) -> dict:
    return {
        "schema": DOM_PROBE_SCHEMA, "contract_version": DOM_CONTRACT_VERSION,
        "status": "pass",
        "slots": [{"position": position, "element": element,
                   "web_name": f"Player {element}"}
                  for position, element in enumerate(order, start=1)],
        "captain_controls": {
            "status": "pass",
            "starters": [
                {"position": position, "element": element,
                 "player_button_index": position - 1,
                 "captain_checkbox": True, "vice_captain_checkbox": True,
                 "captain_checked": element == 1, "vice_captain_checked": element == 2}
                for position, element in enumerate(order[:11], start=1)
            ],
        },
    }


def _raises(callable_, expected: str) -> bool:
    try:
        callable_()
    except Exception as exc:  # the drill records only class, never private payloads
        return expected in str(exc)
    return False


def run() -> dict:
    """Prove fail-closed DOM handling and no retry after uncertain commit."""
    checks: dict[str, bool] = {}
    workspace_path: Path | None = None
    with tempfile.TemporaryDirectory(prefix="mova-browser-failure-drill-") as temporary:
        workspace = Path(temporary)
        workspace_path = workspace
        service, plan_row, pre = _seed(workspace / "ambiguous")
        plan = service._load_plan(service.db.execution_claim_source(plan_row["plan_id"])["plan"])
        bundle = {**compile_browser_commands(plan), "execution_id": "fixture_execution"}
        probe = _dom_probe(list(range(1, 16)))
        compiled = compile_r2_ui_action_plan(
            bundle=bundle, pre_state=pre, dom_probe=probe, expected_team_id=3609854,
        )
        checks["valid_dom_contract_accepted"] = compiled["status"] == "ready"

        drifted_version = {**probe, "contract_version": "unknown-dom-contract"}
        checks["dom_contract_version_drift_rejected"] = _raises(
            lambda: compile_r2_ui_action_plan(
                bundle=bundle, pre_state=pre, dom_probe=drifted_version,
                expected_team_id=3609854,
            ), "versión del DOM probe incompatible",
        )
        checks["dom_order_drift_rejected"] = _raises(
            lambda: compile_r2_ui_action_plan(
                bundle=bundle, pre_state=pre,
                dom_probe=_dom_probe([2, 1] + list(range(3, 16))),
                expected_team_id=3609854,
            ), "orden del DOM no coincide",
        )
        snapshot = Path("tests/fixtures/fpl_pick_team_accessibility.txt")
        if snapshot.is_file():
            accessibility = snapshot.read_text(encoding="utf-8")
        else:
            accessibility = "\n".join([
                'heading "Pick Team"', 'heading "Deadline: fixture"', 'link "Sign Out"',
                'link "Transfers"', 'button "Bench Boost Play"',
                'button "Triple Captain Play"', 'button "Wildcard Play"',
                'button "Free Hit Play"', *(['button "Switch player"'] * 15),
            ])
        checks["missing_accessible_control_rejected"] = (
            assess_pick_team_snapshot(accessibility.replace('link "Sign Out"', ""))["status"]
            == "fail"
        )
        checks["wrong_switch_control_count_rejected"] = (
            assess_pick_team_snapshot(accessibility.replace(
                'button "Switch player"', "", 1,
            ))["status"] == "fail"
        )

        prepared = service.prepare(
            plan_id=plan_row["plan_id"], adapter="fixture", actor="drill",
            reason="ambiguous save fixture", idempotency_key="execute:ambiguous", now=NOW,
        )
        claim = service.claim(execution_id=prepared["execution_id"], actor="drill",
                              reason="fixture claim", now=NOW)
        service.begin(execution_id=prepared["execution_id"],
                      claim_token=claim["claim_token"], pre_state=pre, actor="drill",
                      reason="pre-state matched", now=NOW + timedelta(seconds=1))
        result = service.finalize(
            execution_id=prepared["execution_id"], claim_token=claim["claim_token"],
            post_state={**pre, "observed_at": (
                NOW + timedelta(seconds=10)).isoformat()},
            actor="drill", reason="post-reload mismatch", now=NOW + timedelta(seconds=11),
        )
        checks["post_reload_mismatch_is_ambiguous"] = result["status"] == "ambiguous"
        checks["ambiguous_save_opens_p0"] = (
            service.db.status()["open_incidents"].get("P0") == 1
        )
        checks["ambiguous_attempt_cannot_be_reclaimed"] = _raises(
            lambda: service.claim(execution_id=prepared["execution_id"], actor="drill",
                                  reason="retry forbidden", now=NOW + timedelta(seconds=12)),
            "ambiguous",
        )

        blocked_service, blocked_plan, blocked_pre = _seed(workspace / "blocked")
        blocked_prepared = blocked_service.prepare(
            plan_id=blocked_plan["plan_id"], adapter="fixture", actor="drill",
            reason="pre-state drift fixture", idempotency_key="execute:pre-drift", now=NOW,
        )
        blocked_claim = blocked_service.claim(
            execution_id=blocked_prepared["execution_id"], actor="drill",
            reason="fixture claim", now=NOW,
        )
        changed_pre = _private_state([2, 1] + list(range(3, 16)), captain=1, vice=2)
        blocked_result = blocked_service.begin(
            execution_id=blocked_prepared["execution_id"],
            claim_token=blocked_claim["claim_token"], pre_state=changed_pre,
            actor="drill", reason="observed drift", now=NOW + timedelta(seconds=1),
        )
        checks["pre_state_drift_blocks_before_applying"] = (
            blocked_result["status"] == "blocked"
            and "OBSERVED_PRE_STATE_CHANGED" in blocked_result["blocking_codes"]
        )
        checks["blocked_attempt_never_applied"] = (
            blocked_service.db.execution_attempt(blocked_prepared["execution_id"])["status"]
            == "blocked"
        )

    checks["temporary_workspace_removed"] = (
        workspace_path is not None and not workspace_path.exists()
    )
    return {
        "schema": SCHEMA, "scenario": "dom_drift_ambiguous_save",
        "status": "pass" if all(checks.values()) else "fail", "checks": checks,
        "runtime_mutated": False, "fixture_only": True,
    }
