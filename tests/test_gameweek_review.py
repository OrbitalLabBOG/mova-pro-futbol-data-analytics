from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from mova_fpl.analytics.gameweek_review import (
    build_decision, load_closeout_package, score_scenario,
)
from mova_fpl.cli.settle_trace import export as export_trace
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.causal_review import CausalReviewerService
from mova_fpl.ops.db import OpsDB
from mova_fpl.ops.collector.contracts import canonical_bytes
from mova_fpl.ops.decision_envelope import sha256_json
from mova_fpl.data.private_state import seal as seal_private_state
from mova_fpl.ops.improvement import (
    ContinuousImprovementService, validate_transition_evidence,
)
from mova_fpl.ops.model_release import ModelReleaseService, resolve_active_model_bundle
from mova_fpl.ops.review import GameweekReviewService
from mova_fpl.rules import get as get_rules


POINTS = {
    109: (6, 90), 8: (9, 80), 418: (1, 90), 11: (6, 90), 557: (6, 75),
    426: (2, 90), 427: (2, 90), 124: (2, 90), 346: (1, 90), 165: (11, 90),
    411: (2, 90), 496: (2, 90), 565: (14, 75), 329: (6, 90), 173: (3, 90),
    226: (7, 90), 229: (6, 90), 4: (5, 90), 84: (6, 90), 480: (2, 90),
    95: (3, 66), 236: (11, 90), 155: (1, 25), 399: (8, 27), 106: (0, 82),
    1: (6, 90), 469: (2, 90), 445: (3, 90),
}


def _package() -> tuple[Path, dict]:
    path = Path(__file__).parents[1] / "decisions/fpl/2026-27/gw01_closeout.json"
    return path, load_closeout_package(path)


def _official(package: dict) -> dict:
    all_players = {}
    position_ids = {"GKP": 1, "DEF": 2, "MID": 3, "FWD": 4}
    for scenario in (package["selected"], package["comparator"]):
        for row in scenario["players"]:
            all_players[int(row["element"])] = {
                "element": int(row["element"]), "web_name": row["name"],
                "team_id": 1, "element_type": position_ids[row["position"]],
                "now_cost": int(float(row["price"]) * 10),
            }
    selected = package["selected"]
    multipliers = {int(row["element"]): int(row["role"] == "starter")
                   for row in selected["players"]}
    multipliers[int(selected["captain"])] = 2
    picks = [{"element": element, "multiplier": multiplier, "position": index}
             for index, (element, multiplier) in enumerate(multipliers.items(), start=1)]
    live = [{"element": element, "total_points": points, "minutes": minutes,
             "stats": {"total_points": points, "minutes": minutes}}
            for element, (points, minutes) in POINTS.items()]
    return {
        "event": {"payload": {"average_entry_score": 50}, "finished": True,
                  "data_checked": True},
        "entry": {"event_points": 50, "event_rank": 4383525},
        "picks": picks, "live": live, "players": list(all_players.values()),
        "source": {"artifact_id": "artifact_gw1", "observed_at": "2026-08-27T21:30:09Z",
                   "artifact_path": "/artifacts/gw1", "manifest_sha256": "a" * 64,
                   "payload_sha256": "b" * 64},
        "projection_count": 0,
    }


def test_gw1_retrospective_scores_selected_and_pure_model(tmp_path: Path):
    path, package = _package()
    config = RuntimeConfig(artifact_root=tmp_path / "artifacts")
    service = GameweekReviewService(config, OpsDB(tmp_path / "ops.db", enforce_version=False))
    result = service._build(
        package, _official(package), path, "job_test", "2026-27-gw01", "corr_test",
        "julian", "cerrar GW1", "gw1:closeout:v1",
    )
    metrics = result["ledger"]["review"]["metrics"]
    assert result["selected_score"]["points"] == 50
    assert result["comparator_score"]["points"] == 62
    assert metrics["bench_points"] == 25
    assert metrics["intervention"] == {"expected_delta": -12.33, "realized_delta": -12}
    assert metrics["causal_scorecard_created"] is False
    assert metrics["causality_reason"] == "not_eligible_no_predeadline_batch"
    assert metrics["same_squad_oracle_fixed_captain"] == 69
    assert metrics["same_squad_oracle_free_captain"] == 81
    artifact = Path(result["ledger"]["review"]["artifact_path"])
    assert artifact.is_file()
    payload = json.loads(artifact.read_text())
    assert payload["metrics"]["entry"]["points"] == 50
    assert [item["code"] for item in payload["findings"]] == [
        "ENTRY_RESULT_AT_AVERAGE",
        "INTERVENTION_PAIRED_NEGATIVE_VALUE",
        "EARLY_SEASON_MINUTES_UNDERCALIBRATED",
        "BENCH_POINTS_NOT_CHIP_CAUSALITY",
        "CAPTAIN_CHOICE_TIED_COMPARATOR",
    ]


def test_retrospective_review_settles_strategy_shadow_against_manual(tmp_path: Path):
    path, package = _package()
    official = _official(package)
    control = build_decision(package["comparator"], package["season"], package["gw"])
    candidate = build_decision(package["selected"], package["season"], package["gw"])
    ids = [int(row["element"]) for row in official["live"]]
    shadow_source = {
        "status": "ready", "envelope_id": "envelope_shadow",
        "envelope_sha256": "e" * 64,
        "shadow": {
            "schema": "mova-strategy-shadow-v1",
            "experiment_id": "EXP-MOVA-2026-003",
            "strategy_key": "season_fixture_h3",
            "selected_for_execution": False,
            "virtual_trajectory": True,
            "trajectory": {"mode": "initialized_from_observed"},
            "chips": "disabled_in_both_arms",
            "control": {"decision": control.to_dict(), "violations": []},
            "candidate": {"decision": candidate.to_dict(), "violations": []},
            "projections": {
                "control_horizon_xp": {"1": {str(i): 2.0 for i in ids}},
                "candidate_horizon_xp": {"1": {str(i): 2.1 for i in ids}},
                "candidate_horizon_sd": {"1": {str(i): 1.5 for i in ids}},
            },
        },
    }
    config = RuntimeConfig(artifact_root=tmp_path / "artifacts")
    db = OpsDB(tmp_path / "ops.db", enforce_version=False)
    db.migrate()
    cycle_id = db.upsert_cycle(
        package["season"], package["gw"], package["deadline_at"], phase="settlement"
    )
    job_id, _ = db.start_job(
        "gameweek_review", "gw1:shadow:v1", "corr_test", cycle_id=cycle_id
    )

    result = GameweekReviewService(
        config, db
    )._build(
        package, official, path, job_id, cycle_id, "corr_test",
        "julian", "cerrar GW1", "gw1:shadow:v1", shadow_source,
    )
    db.record_gameweek_closeout(result["ledger"])

    shadow = result["strategy_shadow"]
    assert shadow["status"] == "settled"
    assert shadow["comparison"]["realized_points_delta"] == -12
    assert shadow["manual"]["candidate_realized_delta"] == 0
    assert result["ledger"]["review"]["metrics"]["strategy_shadow"] == shadow
    assert result["ledger"]["review"]["findings"][-1]["code"] == (
        "LONG_HORIZON_SHADOW_NEGATIVE"
    )
    stored = db.strategy_shadow_settlements("2026-27")
    assert len(stored) == 1
    assert stored[0]["comparison"]["realized_points_delta"] == -12


def test_review_with_predeadline_batch_defers_causal_scorecard_to_analytics(tmp_path: Path):
    path, package = _package()
    official = _official(package)
    official["projection_count"] = 2
    config = RuntimeConfig(artifact_root=tmp_path / "artifacts")
    result = GameweekReviewService(
        config, OpsDB(tmp_path / "ops.db", enforce_version=False)
    )._build(
        package, official, path, "job_test", "2026-27-gw01", "corr_test",
        "test", "batch causal", "gw1:causal-routing:v1",
    )
    metrics = result["ledger"]["review"]["metrics"]
    assert metrics["predeadline_projection_batches"] == 2
    assert metrics["causality_reason"] == (
        "analytics_reconcile_required_for_predeadline_batches"
    )


def test_closeout_package_reproduces_documented_fingerprints():
    _, package = _package()
    selected = build_decision(package["selected"], package["season"], package["gw"])
    comparator = build_decision(package["comparator"], package["season"], package["gw"])
    assert selected.fingerprint() == package["intervention"]["selected_fingerprint"]
    assert comparator.fingerprint() == package["intervention"]["base_fingerprint"]


def test_decision_builder_preserves_r3_effects_and_hit_cost(tmp_path: Path):
    path, package = _package()
    package = json.loads(json.dumps(package))
    package["selected"].update({
        "transfers_in": [109], "transfers_out": [226], "hits": 1,
        "chip": None,
    })
    decision = build_decision(package["selected"], package["season"], package["gw"])
    assert decision.transfers_in == (109,)
    assert decision.transfers_out == (226,)
    assert decision.hits == 1
    official = _official(package)
    official["entry"]["event_points"] = 46
    config = RuntimeConfig(artifact_root=tmp_path / "artifacts")
    result = GameweekReviewService(
        config, OpsDB(tmp_path / "ops.db", enforce_version=False)
    )._build(
        package, official, path, "job_test", "2026-27-gw01", "corr_test",
        "test", "r3 accounting", "gw1:r3-accounting:v1",
    )
    assert result["ledger"]["settlement"]["hit_cost"] == 4


def test_autonomous_closeout_package_uses_sealed_execution_and_causal_batch(
    tmp_path: Path, monkeypatch,
):
    _, documented = _package()
    config = RuntimeConfig(
        ops_db=tmp_path / "ops.db", artifact_root=tmp_path / "artifacts",
        lock_path=tmp_path / "worker.lock",
    )
    db = OpsDB(config.ops_db, enforce_version=False)
    db.migrate()
    cycle_id = db.upsert_cycle(
        documented["season"], documented["gw"], documented["deadline_at"],
        phase="executed_verified", status="executed_verified",
    )
    job_id, _ = db.start_job("fixture", "fixture:auto-closeout", "corr_fixture",
                             cycle_id=cycle_id)
    selected = build_decision(
        documented["selected"], documented["season"], documented["gw"]
    ).to_dict()
    comparator = build_decision(
        documented["comparator"], documented["season"], documented["gw"]
    ).to_dict()
    envelope_body = {
        "schema": "mova-decision-envelope-v1", "cycle_id": cycle_id,
        "selected_candidate_key": "milp_baseline",
        "candidates": [
            {"candidate_key": "do_nothing", "label": "Sin cambios",
             "decision": comparator},
            {"candidate_key": "milp_baseline", "label": "Seleccionada",
             "decision": selected},
        ],
    }
    envelope_sha = sha256_json(envelope_body)
    envelope = {**envelope_body, "envelope_id": "envelope_auto",
                "content_sha256": envelope_sha}
    envelope_path = config.artifact_root / "decisions" / "envelope.json"
    envelope_path.parent.mkdir(parents=True)
    envelope_path.write_bytes(canonical_bytes(envelope))
    physical_sha = hashlib.sha256(envelope_path.read_bytes()).hexdigest()
    evidence_path = config.artifact_root / "execution-evidence" / "verified.json"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text('{"status":"verified"}\n', encoding="utf-8")
    evidence_sha = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    now = "2026-08-21T17:00:00+00:00"
    selected_rows = {int(row["element"]): row for row in documented["selected"]["players"]}
    position_ids = {"GKP": 1, "DEF": 2, "MID": 3, "FWD": 4}
    ordered_elements = list(selected["starters"]) + list(selected["bench_order"])
    private_payload = {
        "schema": "mova-fpl-private-team-state-v1", "observed_at": now,
        "team_id": documented["entry_id"],
        "event": {"id": 1, "deadline_time": documented["deadline_at"]},
        "picks_last_updated": now,
        "picks": [{
            "element": element,
            "element_type": position_ids[selected_rows[element]["position"]],
            "position": position,
            "multiplier": (2 if element == selected["captain"] else
                           1 if position <= 11 else 0),
            "is_captain": element == selected["captain"],
            "is_vice_captain": element == selected["vice_captain"],
            "purchase_price": int(selected_rows[element]["price"] * 10),
            "selling_price": int(selected_rows[element]["price"] * 10),
        } for position, element in enumerate(ordered_elements, start=1)],
        "transfers": {"bank": 5, "value": 1000, "limit": 1, "made": 0,
                      "cost": 0, "status": "cost"},
        "chips": [],
    }
    team_state_path, team_manifest, _ = seal_private_state(
        private_payload, documented["season"], config.artifact_root / "team_state",
        expected_team_id=documented["entry_id"],
    )
    team_fingerprint = team_manifest["quality"]["fingerprint"]
    team_manifest_sha = hashlib.sha256(
        (team_state_path / "manifest.json").read_bytes()
    ).hexdigest()
    with db.transaction() as con:
        con.execute(
            """INSERT INTO cycle_manifests(manifest_id,cycle_id,revision,as_of_at,
            deadline_at,phase,source_manifest_json,analytics_manifest_json,
            research_summary_json,artifact_path,content_sha256,created_at)
            VALUES('manifest_auto',?,1,?,?,'preflight','[]','{}','{}',?,?,?)""",
            (cycle_id, now, documented["deadline_at"], str(envelope_path), "m" * 64, now),
        )
        con.execute(
            """INSERT INTO decision_runs(decision_id,job_id,cycle_id,revision,mode,
            policy_version,status,expected_points,fingerprint,artifact_path,created_at)
            VALUES('decision_auto',?,?,1,'supervised','policy','executed_verified',?,?,?,?)""",
            (job_id, cycle_id, selected["expected_points"], team_fingerprint,
             str(envelope_path), now),
        )
        con.execute(
            """INSERT INTO decision_envelopes(envelope_id,job_id,cycle_id,decision_id,
            manifest_id,schema_version,policy_version,status,selected_candidate_key,
            content_sha256,artifact_path,artifact_sha256,created_at)
            VALUES('envelope_auto',?,?,'decision_auto','manifest_auto',
            'mova-decision-envelope-v1','policy','staged','milp_baseline',?,?,?,?)""",
            (job_id, cycle_id, envelope_sha, str(envelope_path), physical_sha, now),
        )
        for key, label, decision, chosen in (
            ("do_nothing", "Sin cambios", comparator, 0),
            ("milp_baseline", "Seleccionada", selected, 1),
        ):
            con.execute(
                """INSERT INTO decision_candidates(envelope_id,candidate_key,label,selected,
                decision_json,fingerprint,expected_points) VALUES('envelope_auto',?,?,?,?,?,?)""",
                (key, label, chosen, json.dumps(decision), decision["fingerprint"],
                 decision["expected_points"]),
            )
        con.execute(
            """INSERT INTO web_executions(execution_id,decision_id,action_level,
            envelope_sha256,status,started_at,finished_at,evidence_path,evidence_sha256)
            VALUES('execution_auto','decision_auto','A2',?,'verified',?,?,?,?)""",
            (envelope_sha, now, now, str(evidence_path), evidence_sha),
        )
        for index, name in enumerate(("authorization", "pre_state", "post_reload_state", "exact_diff")):
            con.execute(
                """INSERT INTO verification_checks(check_id,execution_id,check_name,
                expected_json,observed_json,passed,checked_at)
                VALUES(?,'execution_auto',?,'{}','{}',1,?)""",
                (f"check_{index}", name, now),
            )
        for position, element in enumerate(
            list(selected["starters"]) + list(selected["bench_order"]), start=1
        ):
            con.execute(
                """INSERT INTO decision_players(decision_id,element,squad_position,role,
                is_captain,is_vice_captain,transfer_direction,expected_points)
                VALUES('decision_auto',?,?,?,?,?,?,NULL)""",
                (element, position, "starter" if position <= 11 else "bench",
                 int(element == selected["captain"]),
                 int(element == selected["vice_captain"]), None),
            )
        db.append_audit(
            "manual_verified_execution_recorded", actor="test", cycle_id=cycle_id,
            job_id=job_id, subject_type="web_execution", subject_id="execution_auto",
            payload={"transfers_in": [], "transfers_out": [], "hits": 0, "chip": None},
            con=con,
        )
    db.add_team_state(
        job_id=job_id, cycle_id=cycle_id, observed_at=now,
        source_name="fpl_authenticated_api", squad=[], free_transfers=1,
        bank_tenths=5, chips=[], fingerprint=team_fingerprint,
        artifact_path=str(team_state_path), manifest_sha256=team_manifest_sha,
    )

    players = {}
    for scenario in (documented["selected"], documented["comparator"]):
        for row in scenario["players"]:
            players[int(row["element"])] = {
                "element": int(row["element"]), "player_name": row["name"],
                "team": row["team"], "position": row["position"],
                "xp": float(row["expected_points"]), "p_60": row["p60"],
                "now_cost": int(float(row["price"]) * 10),
            }

    class FakeConnection:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def execute(self, query, params):
            if "model_projection_batches" in query:
                self.rows = [{"batch_id": "projection_auto",
                              "input_artifact_id": "artifact_pre"}]
            else:
                self.rows = list(players.values())
            return self
        def fetchall(self): return self.rows

    monkeypatch.setattr("mova_fpl.ops.review.connect", lambda *a, **k: FakeConnection())
    path = GameweekReviewService(config, db)._autonomous_package(gw=1)
    package = load_closeout_package(path)
    assert package["schema"] == "mova-fpl-autonomous-closeout-v1"
    assert package["intervention"]["payload"]["projection_batch_id"] == "projection_auto"
    assert package["selected"]["captain"] == documented["selected"]["captain"]
    assert package["comparator"]["captain"] == documented["comparator"]["captain"]
    assert package["verified_team_state"]["bank_tenths"] == 5
    assert db.pending_autonomous_closeout_gws(documented["season"]) == [1]


def test_closeout_package_rejects_missing_mount_verification(tmp_path: Path):
    _, package = _package()
    package.pop("mount_verification")
    path = tmp_path / "missing-verification.json"
    path.write_text(json.dumps(package), encoding="utf-8")

    with pytest.raises(ValueError, match="package de cierre sin mount_verification"):
        load_closeout_package(path)


def test_all_gw1_players_validate_and_score_without_autosubs():
    _, package = _package()
    official = _official(package)
    rules = get_rules(package["season"]).SQUAD
    for key in ("selected", "comparator"):
        decision = build_decision(package[key], package["season"], package["gw"])
        score, rows = score_scenario(package[key], decision, official, rules)
        assert score["auto_subs"] == []
        assert len(rows) == 15


def test_review_artifact_exports_paired_attribution_to_trace(tmp_path: Path):
    path, package = _package()
    config = RuntimeConfig(artifact_root=tmp_path / "artifacts")
    service = GameweekReviewService(config, OpsDB(tmp_path / "ops.db", enforce_version=False))
    result = service._build(
        package, _official(package), path, "job_test", "2026-27-gw01", "corr_test",
        "julian", "cerrar GW1", "gw1:trace-export:v1",
    )
    trace_db = tmp_path / "trace.db"
    exported = export_trace(
        path, Path(result["ledger"]["review"]["artifact_path"]), trace_db,
    )
    assert exported["points"] == 50
    assert exported["comparator_points"] == 62
    import sqlite3
    with sqlite3.connect(trace_db) as con:
        decision = con.execute(
            "select state,actual_points from gw_decisions where run_id=? and gw=1",
            (package["trace_run_id"],),
        ).fetchone()
        intervention = con.execute(
            "select expected_delta,realized_delta,points_with,points_without "
            "from interventions where run_id=? and gw=1",
            (package["trace_run_id"],),
        ).fetchone()
    assert decision == ("reconciled", 50)
    assert intervention == (-12.33, -12, 50, 62)


def test_closeout_is_queryable_through_supported_runtime(tmp_path: Path):
    path, package = _package()
    config = RuntimeConfig(artifact_root=tmp_path / "artifacts")
    db = OpsDB(tmp_path / "ops.db", enforce_version=False)
    db.migrate()
    cycle_id = db.upsert_cycle(
        package["season"], package["gw"], package["deadline_at"], phase="settlement"
    )
    job_id, _ = db.start_job("gameweek_review", "gw1:status-test", "corr_test", cycle_id=cycle_id)
    result = GameweekReviewService(config, db)._build(
        package, _official(package), path, job_id, cycle_id, "corr_test",
        "julian", "cerrar GW1", "gw1:status-test",
    )
    db.record_gameweek_closeout(result["ledger"])
    status = db.gameweek_review_status("2026-27", 1)
    assert status["status"] == "closed"
    assert status["review"]["entry_points"] == 50
    assert status["review"]["comparator_actual_points"] == 62
    assert len(status["player_outcomes"]) == 30
    assert len(status["change_proposals"]) == 3


def test_successful_closeout_replay_resolves_prior_failure_incident(tmp_path: Path):
    path, package = _package()
    config = RuntimeConfig(
        ops_db=tmp_path / "ops.db", artifact_root=tmp_path / "artifacts",
        lock_path=tmp_path / "ops.lock",
    )
    db = OpsDB(config.ops_db, enforce_version=False)
    db.migrate()
    cycle_id = db.upsert_cycle(
        package["season"], package["gw"], package["deadline_at"], phase="settlement"
    )
    key = "gw1:recovered-closeout"
    job_id, _ = db.start_job("gameweek_review", key, "corr_recovered", cycle_id=cycle_id)
    db.finish_job(job_id, "completed")
    db.open_incident_once("P2", "Settlement GW1 falló")

    result = GameweekReviewService(config, db).run(
        package_path=path, actor="test", reason="replay confirmado", idempotency_key=key,
    )

    assert result["status"] == "reused"
    with db.connect(readonly=True) as con:
        incident = con.execute(
            "SELECT status,resolution FROM incidents WHERE title='Settlement GW1 falló'"
        ).fetchone()
    assert incident["status"] == "resolved"
    assert job_id in incident["resolution"]


def test_closeout_reuses_matching_verified_execution(tmp_path: Path):
    path, package = _package()
    config = RuntimeConfig(artifact_root=tmp_path / "artifacts")
    db = OpsDB(tmp_path / "ops.db", enforce_version=False)
    db.migrate()
    cycle_id = db.upsert_cycle(
        package["season"], package["gw"], package["deadline_at"], phase="settlement"
    )
    job_id, _ = db.start_job(
        "gameweek_review", "gw1:reuse-execution", "corr_reuse", cycle_id=cycle_id
    )
    result = GameweekReviewService(config, db)._build(
        package, _official(package), path, job_id, cycle_id, "corr_reuse",
        "julian", "cerrar con ejecución previa", "gw1:reuse-execution",
    )
    with db.transaction() as con:
        con.execute(
            """INSERT INTO decision_runs(
            decision_id,job_id,cycle_id,revision,mode,policy_version,status,created_at)
            VALUES('decision_existing',?,?,1,'guarded','human-reviewed','executed_verified',?)""",
            (job_id, cycle_id, package["mounted_at"]),
        )
        con.execute(
            """INSERT INTO web_executions(
            execution_id,decision_id,action_level,envelope_sha256,status,started_at,
            finished_at,evidence_path,evidence_sha256)
            VALUES('execution_existing','decision_existing','A1','envelope','verified',?,?,?,?)""",
            (package["mounted_at"], package["mounted_at"], package["mount_evidence_path"],
             package["mount_evidence_sha256"]),
        )

    persisted = db.record_gameweek_closeout(result["ledger"])

    assert persisted["decision_id"] == "decision_existing"
    assert persisted["execution_id"] == "execution_existing"
    assert persisted["reused_verified_execution"] is True
    with db.connect(readonly=True) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM decision_runs WHERE cycle_id=?", (cycle_id,)
        ).fetchone()[0] == 1
        assert con.execute(
            "SELECT decision_id FROM gameweek_reviews WHERE review_id=?",
            (persisted["review_id"],),
        ).fetchone()[0] == "decision_existing"


def _persisted_review(tmp_path: Path) -> tuple[OpsDB, str]:
    path, package = _package()
    config = RuntimeConfig(artifact_root=tmp_path / "artifacts")
    db = OpsDB(tmp_path / "ops.db", enforce_version=False)
    db.migrate()
    cycle_id = db.upsert_cycle(
        package["season"], package["gw"], package["deadline_at"], phase="settlement"
    )
    job_id, _ = db.start_job(
        "gameweek_review", "gw1:improvement-test", "corr_improvement", cycle_id=cycle_id
    )
    result = GameweekReviewService(config, db)._build(
        package, _official(package), path, job_id, cycle_id, "corr_improvement",
        "test", "seed improvement", "gw1:improvement-test",
    )
    db.record_gameweek_closeout(result["ledger"])
    proposal_id = db.gameweek_review_status("2026-27", 1)["change_proposals"][0]["proposal_id"]
    return db, proposal_id


def test_improvement_gate_promotes_only_a_validated_lesson(tmp_path: Path):
    db, proposal_id = _persisted_review(tmp_path)
    with db.transaction() as con:
        con.execute(
            """INSERT INTO cost_ledger(cost_id,provider,subscription_usage,
            detail_json,occurred_at) VALUES('cost_unknown','codex_subscription',1,'{}',
            '2026-08-30T18:00:00Z')"""
        )
    service = ContinuousImprovementService(db)
    testing = tmp_path / "testing.json"
    testing.write_text(json.dumps({
        "experiment_id": "exp_minutes_v2", "test_plan": "backtest causal pareado",
    }), encoding="utf-8")
    accepted = tmp_path / "accepted.json"
    accepted.write_text(json.dumps({
        "experiment_id": "exp_minutes_v2", "evaluated_at": "2026-08-30T18:00:00Z",
        "acceptance_passed": True, "baseline": {"mae": 1.2},
        "candidate": {"mae": 1.1}, "test_evidence": ["artifact://exp_minutes_v2"],
        "rollback_plan": "restaurar model release anterior",
    }), encoding="utf-8")

    first = service.transition(
        proposal_id=proposal_id, to_status="testing", evidence_path=testing,
        actor="test", reason="abre experimento", idempotency_key="improve:test:testing",
    )
    promoted = service.transition(
        proposal_id=proposal_id, to_status="accepted", evidence_path=accepted,
        actor="test", reason="cumple criterio", idempotency_key="improve:test:accepted",
    )
    reused = service.transition(
        proposal_id=proposal_id, to_status="accepted", evidence_path=accepted,
        actor="test", reason="retry", idempotency_key="improve:test:accepted",
    )
    status = service.status(season="2026-27", gw=1)

    assert first["runtime_mutated"] is False
    assert promoted["lesson_id"].startswith("lesson_")
    assert reused["status"] == "reused"
    assert any(item["proposal_id"] == proposal_id and item["status"] == "accepted"
               for item in status["proposals"])
    assert len(status["lessons"]) == 1
    assert status["lessons"][0]["status"] == "validated"
    assert status["costs"]["totals"]["estimated_cost_usd"] is None
    assert status["costs"]["totals"]["unknown_cost_uses"] == 1
    assert status["runtime_mutated"] is False


def test_improvement_gate_blocks_weak_evidence_and_direct_accept(tmp_path: Path):
    db, proposal_id = _persisted_review(tmp_path)
    weak = {"experiment_id": "exp", "acceptance_passed": False}
    with pytest.raises(ValueError, match="evaluated_at"):
        validate_transition_evidence("accepted", weak)
    evidence = tmp_path / "accepted.json"
    evidence.write_text(json.dumps({
        "experiment_id": "exp", "evaluated_at": "2026-08-30T18:00:00Z",
        "acceptance_passed": True, "baseline": {"mae": 1.2},
        "candidate": {"mae": 1.1}, "test_evidence": ["artifact://exp"],
        "rollback_plan": "rollback",
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="transición inválida"):
        ContinuousImprovementService(db).transition(
            proposal_id=proposal_id, to_status="accepted", evidence_path=evidence,
            actor="test", reason="atajo inválido", idempotency_key="improve:test:invalid",
        )


class _ReleaseAnalytics:
    def __init__(self, status: str = "passed"):
        self.status = status

    def model_release_shadow_gate(self, *, season: str, release: dict) -> dict:
        passed = self.status == "passed"
        return {
            "schema": "mova-model-release-shadow-gate-v1", "status": self.status,
            "season": season, "release_id": release["release_id"],
            "final_gameweeks": 3 if passed else 1,
            "checks": {"final_gameweeks": passed, "drift_alerts": True,
                       "points_mae": True, "p60_ece": True},
            "candidate_evaluation_ids": ["evaluation_candidate"] if passed else [],
            "baseline_evaluation_ids": ["evaluation_baseline"] if passed else [],
        }


def _model_artifact(config: RuntimeConfig, name: str, version: str, body: bytes) -> str:
    directory = config.artifact_root / "models" / name
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}-{version}.joblib"
    path.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    path.with_suffix(".json").write_text(json.dumps({
        "name": name, "version": version, "artifact_sha256": digest,
        "metrics": {"fixture": True},
    }), encoding="utf-8")
    return digest


def test_model_release_requires_shadow_then_promotes_and_rolls_back(tmp_path: Path):
    db, proposal_id = _persisted_review(tmp_path)
    improvement = ContinuousImprovementService(db)
    testing = tmp_path / "release-testing.json"
    testing.write_text(json.dumps({
        "experiment_id": "exp_model_v2", "test_plan": "backtest causal pareado",
    }), encoding="utf-8")
    accepted = tmp_path / "release-accepted.json"
    accepted.write_text(json.dumps({
        "experiment_id": "exp_model_v2", "evaluated_at": "2026-08-30T18:00:00Z",
        "acceptance_passed": True, "baseline": {"mae": 1.2},
        "candidate": {"mae": 1.1}, "test_evidence": ["artifact://exp_model_v2"],
        "rollback_plan": "restaurar bundle anterior",
    }), encoding="utf-8")
    improvement.transition(
        proposal_id=proposal_id, to_status="testing", evidence_path=testing,
        actor="test", reason="abre experimento", idempotency_key="release:testing",
    )
    improvement.transition(
        proposal_id=proposal_id, to_status="accepted", evidence_path=accepted,
        actor="test", reason="acepta experimento", idempotency_key="release:accepted",
    )

    config = RuntimeConfig(artifact_root=tmp_path / "artifacts")
    baseline_hashes = {
        name: _model_artifact(config, name, "1.1.0", f"{name}-baseline".encode())
        for name in ("minutes", "points")
    }
    candidate_hashes = {
        name: _model_artifact(config, name, "1.2.0", f"{name}-candidate".encode())
        for name in ("minutes", "points")
    }
    manifest = tmp_path / "release.json"
    manifest.write_text(json.dumps({
        "schema": "mova-model-bundle-candidate-v1",
        "models": {name: {"version": "1.2.0", "artifact_sha256": digest}
                   for name, digest in candidate_hashes.items()},
        "promotion_policy": {"min_final_gameweeks": 3},
    }), encoding="utf-8")
    service = ModelReleaseService(config, db, _ReleaseAnalytics("insufficient"))
    prepared = service.prepare(
        proposal_id=proposal_id, manifest_path=manifest, actor="test",
        reason="sella candidato", idempotency_key="release:prepare",
    )
    release_id = prepared["release_id"]
    reused = service.prepare(
        proposal_id=proposal_id, manifest_path=manifest, actor="test",
        reason="retry", idempotency_key="release:prepare",
    )
    assert reused["status"] == "reused"
    shadow = service.shadow(
        release_id=release_id, actor="test", reason="inicia shadow",
        idempotency_key="release:shadow",
    )
    assert shadow["runtime_mutated"] is False
    with pytest.raises(ValueError, match="shadow gate no aprobado"):
        service.promote(
            release_id=release_id, actor="test", reason="prematuro",
            idempotency_key="release:promote:blocked",
        )
    assert db.model_bundle_release_status()["releases"][0]["status"] == "shadow"

    service.analytics = _ReleaseAnalytics("passed")
    promoted = service.promote(
        release_id=release_id, actor="test", reason="gate aprobado",
        idempotency_key="release:promote",
    )
    assert promoted["runtime_mutated"] is True
    assert service.promote(
        release_id=release_id, actor="test", reason="retry",
        idempotency_key="release:promote",
    )["status"] == "reused"
    active = resolve_active_model_bundle(config, db)
    assert active["release_id"] == release_id
    assert active["models"]["points"]["artifact_sha256"] == candidate_hashes["points"]

    second_proposal = next(
        row["proposal_id"] for row in improvement.status()["proposals"]
        if row["proposal_id"] != proposal_id
    )
    improvement.transition(
        proposal_id=second_proposal, to_status="testing", evidence_path=testing,
        actor="test", reason="segundo experimento", idempotency_key="release2:testing",
    )
    improvement.transition(
        proposal_id=second_proposal, to_status="accepted", evidence_path=accepted,
        actor="test", reason="acepta segundo", idempotency_key="release2:accepted",
    )
    second_hashes = {
        name: _model_artifact(config, name, "1.3.0", f"{name}-candidate-2".encode())
        for name in ("minutes", "points")
    }
    second_manifest = tmp_path / "release-2.json"
    second_manifest.write_text(json.dumps({
        "schema": "mova-model-bundle-candidate-v1",
        "models": {name: {"version": "1.3.0", "artifact_sha256": digest}
                   for name, digest in second_hashes.items()},
    }), encoding="utf-8")
    second = service.prepare(
        proposal_id=second_proposal, manifest_path=second_manifest, actor="test",
        reason="sella segundo", idempotency_key="release2:prepare",
    )
    second_id = second["release_id"]
    service.shadow(
        release_id=second_id, actor="test", reason="shadow segundo",
        idempotency_key="release2:shadow",
    )
    service.promote(
        release_id=second_id, actor="test", reason="promueve segundo",
        idempotency_key="release2:promote",
    )
    service.rollback(
        release_id=second_id, actor="test", reason="revierte al primero",
        idempotency_key="release2:rollback",
    )
    active = resolve_active_model_bundle(config, db)
    assert active["release_id"] == release_id
    states = {row["release_id"]: row["status"]
              for row in db.model_bundle_release_status()["releases"]}
    assert states[release_id] == "promoted"
    assert states[second_id] == "rolled_back"

    rolled_back = service.rollback(
        release_id=release_id, actor="test", reason="drill de rollback",
        idempotency_key="release:rollback",
    )
    assert rolled_back["runtime_mutated"] is True
    active = resolve_active_model_bundle(config, db)
    assert active["release_id"] is None
    assert active["models"]["minutes"]["artifact_sha256"] == baseline_hashes["minutes"]


def test_model_release_rejects_tampered_artifact(tmp_path: Path):
    db, _proposal_id = _persisted_review(tmp_path)
    config = RuntimeConfig(artifact_root=tmp_path / "artifacts")
    for name in ("minutes", "points"):
        _model_artifact(config, name, "1.1.0", name.encode())
    pointer = {"schema": "mova-active-model-bundle-v1", "release_id": "release_bad",
               "models": {name: {"version": "1.1.0", "artifact_sha256": "0" * 64}
                          for name in ("minutes", "points")}}
    db.set_control("active_model_bundle", pointer, actor="test", reason="tamper fixture")
    with pytest.raises(ValueError, match="hash de artefacto no coincide"):
        resolve_active_model_bundle(config, db)


def test_causal_reviewer_requires_settlement_and_final_scorecard(tmp_path: Path):
    config = RuntimeConfig(artifact_root=tmp_path / "artifacts")
    empty = OpsDB(tmp_path / "empty.db", enforce_version=False)
    result = CausalReviewerService(config, empty).run(
        gw=2, actor="test", reason="review", idempotency_key="causal:gw2:v1",
        analytics_state={"latest_scorecards": []},
    )
    assert result["status"] == "not_ready"
    assert result["reason"] == "settlement_not_closed"

    db, _proposal = _persisted_review(tmp_path)
    missing = CausalReviewerService(config, db).run(
        gw=1, actor="test", reason="review", idempotency_key="causal:gw1:missing",
        analytics_state={"latest_scorecards": []},
    )
    assert missing["reason"] == "baseline_scorecard_missing"
    assert db.pending_causal_review_gws("2026-27") == [1]


def test_causal_reviewer_is_idempotent_and_does_not_optimize_one_gw(tmp_path: Path):
    db, _proposal = _persisted_review(tmp_path)
    config = RuntimeConfig(artifact_root=tmp_path / "artifacts")
    state = {"latest_scorecards": [{
        "season": "2026-27", "gw": 1, "variant": "baseline",
        "drift_status": "ok", "metrics": {"points_mae": 2.1},
    }]}
    service = CausalReviewerService(config, db)
    result = service.run(
        gw=1, actor="test", reason="cierre causal",
        idempotency_key="causal:gw1:v1", analytics_state=state,
    )
    reused = service.run(
        gw=1, actor="test", reason="retry",
        idempotency_key="causal:gw1:v1", analytics_state=state,
    )
    assert result["status"] == "completed"
    assert result["proposals"] == 0
    assert reused["status"] == "reused"
    assert Path(result["artifact_path"]).is_file()
    with db.connect(readonly=True) as con:
        review = con.execute(
            "SELECT review_type,causality_status FROM gameweek_reviews "
            "WHERE review_id=?", (result["review_id"],)
        ).fetchone()
        causal_proposals = con.execute(
            "SELECT COUNT(*) FROM change_proposals WHERE review_id=?",
            (result["review_id"],),
        ).fetchone()[0]
    assert dict(review) == {"review_type": "causal", "causality_status": "eligible"}
    assert causal_proposals == 0
    assert db.pending_causal_review_gws("2026-27") == []
    status = db.gameweek_review_status("2026-27", 1)
    assert status["review"]["review_type"] == "causal"
    assert len(status["change_proposals"]) == 3  # conserva propuestas retrospectivas


def test_causal_reviewer_does_not_count_same_gameweek_corrections_as_recurrence(tmp_path: Path):
    db, _proposal = _persisted_review(tmp_path)
    config = RuntimeConfig(artifact_root=tmp_path / "artifacts")
    state = {"latest_scorecards": [{
        "season": "2026-27", "gw": 1, "variant": "baseline",
        "drift_status": "ok", "metrics": {"points_mae": 2.1},
    }]}
    service = CausalReviewerService(config, db)
    first = service.run(
        gw=1, actor="test", reason="primer cierre",
        idempotency_key="causal:gw1:first", analytics_state=state,
    )
    path, package = _package()
    cycle_id = "2026-27-gw01"
    job_id, _ = db.start_job(
        "gameweek_review", "gw1:corrected-closeout", "corr_corrected", cycle_id=cycle_id,
    )
    corrected_official = json.loads(json.dumps(_official(package)))
    corrected_official["source"]["artifact_id"] = "artifact_gw1_corrected"
    corrected_official["source"]["artifact_path"] = "/artifacts/gw1-corrected"
    corrected = GameweekReviewService(config, db)._build(
        package, corrected_official, path, job_id, cycle_id, "corr_corrected",
        "test", "corrección oficial", "gw1:corrected-closeout",
    )
    db.record_gameweek_closeout(corrected["ledger"])
    second = service.run(
        gw=1, actor="test", reason="cierre corregido",
        idempotency_key="causal:gw1:corrected", analytics_state=state,
    )

    assert first["proposals"] == 0
    assert second["proposals"] == 0
    assert all(item["prior_occurrences"] == 0 for item in second["findings"])


def test_active_model_pointer_uses_ledger_order_when_wall_clock_moves_backwards(tmp_path):
    db = OpsDB(tmp_path / 'ops.db', enforce_version=False)
    db.migrate()
    with db.transaction() as con:
        for at, release in [('2026-09-05T03:00:00Z', 'first'), ('2026-09-05T02:59:59Z', None)]:
            con.execute('INSERT INTO runtime_controls(control_key,value_json,effective_at,actor,reason) '
                        'VALUES(?,?,?,?,?)', ('active_model_bundle', json.dumps({'release_id': release}),
                                              at, 'test', 'rollback'))
    assert db.active_model_bundle()['release_id'] is None
    assert db.model_bundle_release_status()['active_model_bundle']['value']['release_id'] is None


def _causal_fixture(tmp_path):
    db, _ = _persisted_review(tmp_path)
    service = CausalReviewerService(RuntimeConfig(artifact_root=tmp_path / 'artifacts'), db)
    args = dict(gw=1, actor='test', reason='recovery test', idempotency_key='causal:recovery',
                analytics_state={'latest_scorecards': [dict(season='2026-27', gw=1,
                    variant='baseline', drift_status='alert')]})
    return db, service, args


def test_causal_repeated_findings_persist_with_storage_contract(tmp_path, monkeypatch):
    db, service, args = _causal_fixture(tmp_path)
    original = db.causal_review_context
    def recurrent(cycle):
        context = original(cycle)
        context['category_occurrences'] = {c: 2 for c in service.CATEGORIES}
        context['unresolved_research_conflicts'] = 1
        return context
    monkeypatch.setattr(db, 'causal_review_context', recurrent)
    result = service.run(**args)
    assert result['proposals'] >= 3
    with db.connect(readonly=True) as con:
        rows = con.execute('SELECT category,change_level,priority FROM change_proposals '
                           'WHERE review_id=?', (result['review_id'],)).fetchall()
    assert {'model', 'research', 'strategy'} <= {r['category'] for r in rows}
    assert all((r['change_level'], r['priority']) == ('C2', 'P2') for r in rows)
    assert service.run(**args)['status'] == 'reused'


@pytest.mark.parametrize('after_commit', [False, True])
def test_causal_recovers_failed_transaction_without_duplicate_review(tmp_path, monkeypatch, after_commit):
    db, service, args = _causal_fixture(tmp_path)
    record = db.record_causal_review
    def interrupted(payload):
        if after_commit:
            record(payload)
        raise OSError('injected lost response')
    monkeypatch.setattr(db, 'record_causal_review', interrupted)
    with pytest.raises(OSError):
        service.run(**args)
    assert service.run(**args)['status'] == 'failed'  # cooldown, never fake success
    with db.transaction() as con:
        con.execute("UPDATE job_runs SET finished_at='2026-01-01T00:00:00+00:00' "
                    "WHERE idempotency_key=?", (args['idempotency_key'],))
    monkeypatch.setattr(db, 'record_causal_review', record)
    result = service.run(**args)
    assert result['status'] == 'completed'
    assert service.run(**args)['status'] == 'reused'
    assert db.get_job_by_key(args['idempotency_key'])['attempt'] == 2
    with db.connect(readonly=True) as con:
        rows = con.execute("SELECT artifact_path,artifact_sha256 FROM gameweek_reviews "
                           "WHERE review_type='causal'").fetchall()
        assert len(rows) == 1
        assert rows[0]['artifact_path'] == result['artifact_path']
        assert rows[0]['artifact_sha256'] == hashlib.sha256(Path(result['artifact_path']).read_bytes()).hexdigest()


def test_causal_retry_is_bounded_and_rejects_changed_inputs(tmp_path, monkeypatch):
    db, service, args = _causal_fixture(tmp_path)
    def broken(payload):
        raise OSError('persistent failure')
    monkeypatch.setattr(db, 'record_causal_review', broken)
    for attempt in range(1, 4):
        with pytest.raises(OSError):
            service.run(**args)
        assert db.get_job_by_key(args['idempotency_key'])['attempt'] == attempt
        with db.transaction() as con:
            con.execute("UPDATE job_runs SET finished_at='2026-01-01T00:00:00+00:00' "
                        "WHERE idempotency_key=?", (args['idempotency_key'],))
    assert service.run(**args)['retry_exhausted'] is True
    args['analytics_state']['latest_scorecards'][0]['drift_status'] = 'ok'
    with pytest.raises(ValueError, match='input conflict'):
        service.run(**args)


def test_trace_uses_actual_comparator_and_unknown_author(tmp_path):
    _, package = _package()
    package['comparator']['label'] = 'observed_no_change'
    package['intervention'].pop('author')
    path = tmp_path / 'package.json'
    path.write_text(json.dumps(package))
    config = RuntimeConfig(artifact_root=tmp_path / 'artifacts')
    review = GameweekReviewService(config, OpsDB(tmp_path / 'ops.db', enforce_version=False))._build(
        package, _official(package), path, 'job_test', '2026-27-gw01', 'corr',
        'test', 'trace provenance', 'trace:provenance')
    trace = tmp_path / 'trace.db'
    export_trace(path, Path(review['ledger']['review']['artifact_path']), trace)
    import sqlite3
    with sqlite3.connect(trace) as con:
        assert con.execute('SELECT author FROM interventions').fetchone()[0] == 'unknown'
        labels = {r[0] for r in con.execute('SELECT baseline FROM benchmarks')}
    assert 'observed_no_change' in labels
    assert 'pure_model_v1.1.0' not in labels


def test_causal_crash_recovery_uses_lock_and_preserves_live_job(tmp_path):
    from mova_fpl.ops.tick import exclusive_lock, LockBusy
    db, service, args = _causal_fixture(tmp_path)
    source = db.causal_review_source('2026-27', 1)
    job_id, _ = db.start_job('causal_review', args['idempotency_key'], 'corr',
        cycle_id=source['cycle_id'], input_sha256=sha256_json({
            'source_review_id': source['review_id'],
            'scorecards': args['analytics_state']['latest_scorecards']}))
    assert service.run(**args)['status'] == 'running'
    with db.transaction() as con:
        con.execute("UPDATE job_runs SET started_at='2026-01-01T00:00:00+00:00' "
                    "WHERE job_id=?", (job_id,))
    with exclusive_lock(service.config.artifact_root / 'reviews/2026-27/gw01.lock'):
        with pytest.raises(LockBusy):
            service.run(**args)
    assert db.get_job_by_key(args['idempotency_key'])['attempt'] == 1
    assert service.run(**args)['status'] == 'completed'
    assert db.get_job_by_key(args['idempotency_key'])['attempt'] == 2
