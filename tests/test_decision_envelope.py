import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from mova_fpl.ops.decision_envelope import build_envelope, validate_decision_shape
from mova_fpl.engine.evaluate import score_decision
from mova_fpl.engine.state import Decision
from mova_fpl.ops.db import OpsDB


def _decision(*, squad=tuple(range(1, 16)), captain=1, chip=None,
              transfers_in=(), transfers_out=(), xp=50.0, policy="fixture"):
    return Decision(
        season="2026-27", gw=3, squad_15=squad, starters=tuple(squad[:11]),
        captain=captain, vice_captain=squad[1] if captain != squad[1] else squad[2],
        bench_order=tuple(squad[11:]), transfers_in=transfers_in,
        transfers_out=transfers_out, chip=chip, expected_points=xp,
        total_cost=99.0, bank_after=1.0, policy=policy,
    )


def _bundle(*, preliminary=False, selected=None):
    unchanged = _decision(policy="do_nothing")
    baseline = selected or _decision(
        squad=tuple(range(2, 17)), captain=2, chip="wildcard",
        transfers_in=(16,), transfers_out=(1,), xp=58.5, policy="milp",
    )
    alternative = _decision(captain=2, xp=53.0, policy="milp")
    return {
        "schema": "mova-live-decision-candidates-v1",
        "season": "2026-27", "gw": 3,
        "selected_candidate_key": "milp_baseline",
        "candidates": [
            {"candidate_key": "do_nothing", "label": "Sin cambios",
             "decision": unchanged.to_dict(), "violations": []},
            {"candidate_key": "milp_baseline", "label": "Baseline",
             "decision": baseline.to_dict(), "violations": []},
            {"candidate_key": "primary_alternative", "label": "Alternativa",
             "decision": alternative.to_dict(), "violations": []},
        ],
        "team_state": {"fingerprint": "f" * 64, "free_transfers": 2},
        "event_context": {
            "prior_gw": 2, "preliminary": preliminary,
            "readiness_reasons": ["prior_gameweek_unsettled"] if preliminary else [],
        },
        "engine": {"policy": "milp", "points_model_version": "1.1.0",
                   "minutes_model_version": "1.1.0", "git_sha": "abc123"},
        "report_artifact": {"path": "decision.md", "sha256": "a" * 64},
    }


def _manifest(*, phase="preflight", analytics=True, plan_id="plan_1"):
    return {
        "schema": "mova-cycle-manifest-v1", "cycle_id": "2026-27-gw03",
        "season": "2026-27", "gw": 3, "revision": 1,
        "as_of_at": "2026-09-04T15:30:00+00:00",
        "deadline_at": "2026-09-04T17:30:00+00:00", "phase": phase,
        "team_state_id": "teamstate_1", "plan_id": plan_id,
        "team_state": {
            "observed_at": "2026-09-04T15:25:00+00:00", "quality_status": "valid",
            "fingerprint": "f" * 64, "free_transfers": 2, "bank_tenths": 0,
        },
        "source_manifest": [],
        "analytics_manifest": ({
            "status": "approved", "target_gw": 3, "player_count": 620,
            "batch_id": "projection_3", "cutoff_at": "2026-09-04T15:00:00Z",
        } if analytics else {"status": "missing", "reason": "no_batch_for_cycle"}),
        "research_summary": {"unresolved_conflicts": 0},
    }


CONTROLS = {"mode": "shadow", "action_level": "A0", "browser_writes": False,
            "kill_switch": True, "compliance_gate": "pending"}


def test_envelope_ready_is_staged_and_deterministic():
    kwargs = {
        "bundle": _bundle(), "manifest": _manifest(), "manifest_id": "manifest_1",
        "manifest_sha256": "b" * 64, "controls": CONTROLS,
    }
    first = build_envelope(**kwargs)
    second = build_envelope(**kwargs)

    assert first == second
    assert first["status"] == "staged"
    assert first["validation"]["blocking_codes"] == []
    assert [row["candidate_key"] for row in first["comparisons"]] == [
        "milp_baseline", "primary_alternative"
    ]


def test_envelope_normalizes_typed_database_timestamps_to_json():
    manifest = _manifest()
    manifest["analytics_manifest"]["cutoff_at"] = datetime(
        2026, 9, 4, 15, 0, tzinfo=timezone.utc,
    )

    envelope = build_envelope(
        bundle=_bundle(), manifest=manifest, manifest_id="manifest_1",
        manifest_sha256="b" * 64, controls=CONTROLS,
    )

    assert isinstance(
        next(
            check for check in envelope["validation"]["checks"]
            if check["code"] == "ANALYTICS_APPROVED_CAUSAL"
        )["detail"]["cutoff_at"],
        str,
    )
    json.dumps(envelope)


def test_envelope_preserves_non_executable_strategy_shadow_without_selecting_it():
    bundle = _bundle()
    control = _decision(xp=52.0).to_dict()
    candidate = _decision(captain=2, xp=51.5).to_dict()
    bundle["strategy_shadow"] = {
        "schema": "mova-strategy-shadow-v1",
        "experiment_id": "EXP-MOVA-2026-003",
        "strategy_key": "season_fixture_h3",
        "status": "shadow_only",
        "selected_for_execution": False,
        "control": {"candidate_key": "shadow_control_h3", "label": "control",
                    "decision": control, "violations": []},
        "candidate": {"candidate_key": "shadow_season_fixture_h3", "label": "candidate",
                      "decision": candidate, "violations": []},
        "comparison": {"fingerprint_changed": True},
        "projections": {"control_horizon_xp": {}, "candidate_horizon_xp": {}},
    }

    envelope = build_envelope(
        bundle=bundle, manifest=_manifest(), manifest_id="manifest_1",
        manifest_sha256="b" * 64, controls=CONTROLS,
    )

    assert envelope["selected_candidate_key"] == "milp_baseline"
    assert envelope["strategy_shadow"] == bundle["strategy_shadow"]
    check = next(
        item for item in envelope["validation"]["checks"]
        if item["code"] == "STRATEGY_SHADOW_VALID_NON_EXECUTABLE"
    )
    assert check["passed"] is True
    assert envelope["status"] == "staged"


def test_preliminary_without_projection_blocks_wildcard():
    envelope = build_envelope(
        bundle=_bundle(preliminary=True), manifest=_manifest(phase="baseline", analytics=False),
        manifest_id="manifest_1", manifest_sha256="b" * 64, controls=CONTROLS,
    )

    assert envelope["status"] == "blocked"
    assert {"PRIOR_GAMEWEEK_SETTLED", "ANALYTICS_APPROVED_CAUSAL",
            "IRREVERSIBLE_ACTION_WINDOW"} <= set(envelope["validation"]["blocking_codes"])


def test_hit_is_paid_transfer_count_not_point_penalty():
    paid_transfer = _decision(
        squad=tuple(range(3, 18)), captain=3,
        transfers_in=(16, 17), transfers_out=(1, 2),
    ).to_dict()
    paid_transfer["hits"] = 1
    paid_transfer.pop("fingerprint")

    assert validate_decision_shape(paid_transfer) == []


def test_settlement_charges_four_points_per_paid_transfer():
    decision = _decision()
    decision = Decision.from_dict({**decision.to_dict(), "hits": 1, "fingerprint": None})
    results = pd.DataFrame([
        {"element": element, "minutes": 90, "total_points": 1}
        for element in range(1, 16)
    ])
    rules = {
        "hit_cost": 4, "starters": 11,
        "formation_min": {}, "formation_max": {},
    }

    outcome = score_decision(decision, results, rules)

    assert outcome.points_before_hits == 12
    assert outcome.hits == 1
    assert outcome.points == 8


def test_envelope_persists_candidates_checks_and_real_manifest_hash(tmp_path: Path):
    db = OpsDB(tmp_path / "ops.db", enforce_version=False)
    db.migrate()
    cycle_id = db.upsert_cycle(
        "2026-27", 3, "2026-09-04T17:30:00+00:00", phase="preflight"
    )
    job_id, _ = db.start_job("tick", "tick:envelope", "corr_envelope", cycle_id=cycle_id)
    db.add_team_state(
        job_id=job_id, cycle_id=cycle_id, observed_at="2026-09-04T15:25:00+00:00",
        source_name="fpl_authenticated_api", squad=[{"element": i} for i in range(1, 16)],
        free_transfers=2, bank_tenths=0, chips=[], fingerprint="f" * 64,
        artifact_path="team-state", manifest_sha256="c" * 64,
    )
    plan = db.activate_season_plan("2026-27", {
        "horizon_start_gw": 3, "horizon_end_gw": 8, "assumptions": [],
        "chip_windows": [], "guardrails": {}, "rationale": "fixture",
    }, actor="test", reason="fixture")
    manifest = _manifest(plan_id=plan["plan_id"])
    manifest["team_state_id"] = db.latest_team_state(cycle_id)["team_state_id"]
    recorded_manifest = db.add_cycle_manifest({**manifest, "artifact_path": "manifest.json"})
    manifest["revision"] = recorded_manifest["revision"]
    envelope = build_envelope(
        bundle=_bundle(), manifest=manifest,
        manifest_id=recorded_manifest["manifest_id"],
        manifest_sha256=recorded_manifest["content_sha256"], controls=CONTROLS,
    )
    first = db.record_decision_envelope(
        job_id=job_id, envelope=envelope, artifact_path="envelope.json",
        artifact_sha256="d" * 64,
    )
    second = db.record_decision_envelope(
        job_id=job_id, envelope=envelope, artifact_path="envelope.json",
        artifact_sha256="d" * 64,
    )

    assert first["status"] == "staged" and second["reused"] is True
    with db.connect(readonly=True) as con:
        decision = con.execute(
            "select manifest_sha256,status from decision_runs where decision_id=?",
            (first["decision_id"],),
        ).fetchone()
        assert decision["manifest_sha256"] == recorded_manifest["content_sha256"]
        assert decision["status"] == "staged"
        assert con.execute("select count(*) from decision_candidates").fetchone()[0] == 3
        assert con.execute("select count(*) from decision_players").fetchone()[0] == 15
        assert con.execute("select count(*) from decision_validation_checks").fetchone()[0] == 11
