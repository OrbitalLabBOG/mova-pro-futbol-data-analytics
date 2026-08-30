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
    assert metrics["same_squad_oracle_fixed_captain"] == 69
    assert metrics["same_squad_oracle_free_captain"] == 81
    artifact = Path(result["ledger"]["review"]["artifact_path"])
    assert artifact.is_file()
    assert json.loads(artifact.read_text())["metrics"]["entry"]["points"] == 50


def test_closeout_package_reproduces_documented_fingerprints():
    _, package = _package()
    selected = build_decision(package["selected"], package["season"], package["gw"])
    comparator = build_decision(package["comparator"], package["season"], package["gw"])
    assert selected.fingerprint() == package["intervention"]["selected_fingerprint"]
    assert comparator.fingerprint() == package["intervention"]["base_fingerprint"]


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
