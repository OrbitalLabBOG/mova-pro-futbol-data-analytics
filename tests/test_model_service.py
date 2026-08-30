from __future__ import annotations

import json
from pathlib import Path

import pytest

from mova_fpl.models.registry import save
from mova_fpl.ops.cli import parser
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB, sha256_json
from mova_fpl.ops.model_service import ModelOpsService


class TinyModel:
    metadata = {"filas_ajuste": 3}


class FakeAnalytics:
    def __init__(self):
        self.calls = []

    def run(self, action, **kwargs):
        self.calls.append((action, kwargs))
        return {"status": "completed", "action": action, "job_id": f"job_{action}"}


class FakeStore:
    def __init__(self, explanation=None):
        self.explanation = explanation

    def projection_explanation(self, batch_id, element):
        return self.explanation

    def status(self, limit=20):
        return {"status": "healthy", "latest_projection_batches": []}


def _config(tmp_path: Path) -> RuntimeConfig:
    canonical = tmp_path / "canonical.db"
    canonical.write_bytes(b"sealed canonical fixture")
    return RuntimeConfig(
        ops_db=tmp_path / "ops.db", canonical_db=canonical,
        artifact_root=tmp_path / "artifacts",
        analytics_root=tmp_path / "analytics",
        analytics_lock_path=tmp_path / "analytics.lock",
    )


def test_model_cli_exposes_four_typed_operations():
    parsed = parser().parse_args([
        "model", "train", "--version", "1.2.0", "--actor", "test",
        "--reason", "candidate", "--idempotency-key", "train-1",
    ])
    assert parsed.model_command == "train" and parsed.holdout == "2025-26"
    assert parser().parse_args([
        "model", "explain", "--batch-id", "projection_1", "--element", "7",
    ]).element == 7
    for operation in ("predict", "evaluate"):
        assert parser().parse_args([
            "model", operation, "--actor", "test", "--reason", "fixture",
            "--idempotency-key", operation,
        ]).model_command == operation


def test_predict_and_evaluate_are_separate_audited_jobs(tmp_path: Path):
    analytics = FakeAnalytics()
    service = ModelOpsService(
        _config(tmp_path), OpsDB(tmp_path / "ops.db", enforce_version=False),
        analytics_store=FakeStore(), analytics_service=analytics,
    )
    predicted = service.predict(actor="agent", reason="predeadline", idempotency_key="gw3")
    evaluated = service.evaluate(actor="agent", reason="settlement", idempotency_key="gw2")
    assert predicted["schema"] == "mova-model-predict-result-v1"
    assert evaluated["schema"] == "mova-model-evaluate-result-v1"
    assert analytics.calls == [
        ("project", {"actor": "agent", "reason": "predeadline",
                     "idempotency_key": "model:predict:gw3"}),
        ("reconcile", {"actor": "agent", "reason": "settlement",
                       "idempotency_key": "model:evaluate:gw2"}),
    ]


def test_explain_is_read_only_sealed_and_preserves_provenance(tmp_path: Path):
    row = {
        "batch_id": "projection_fixture", "season": "2026-27", "target_gw": 3,
        "variant": "baseline", "model_versions": {"minutes": "1.1.0"},
        "cutoff_at": "2026-09-04T17:30:00Z",
        "generated_at": "2026-08-30T20:00:00Z",
        "input_artifact_id": "artifact_1", "input_manifest": {"sha": "a"},
        "artifact_path": "/artifact.json", "artifact_sha256": "b" * 64,
        "element": 7, "fixture_id": 21, "player_name": "Player 7",
        "position": "MID", "team": "ARS", "opponent_team": 2,
        "xp": 6.25, "xp_sd": 1.1, "p_play": .95, "p_60": .82,
        "components": {"goals": 1.2, "assists": .8},
        "context": {"fixture_count": 1},
    }
    service = ModelOpsService(
        _config(tmp_path), OpsDB(tmp_path / "ops.db", enforce_version=False),
        analytics_store=FakeStore(row), analytics_service=FakeAnalytics(),
    )
    result = service.explain(batch_id="projection_fixture", element=7)
    content_sha = result.pop("content_sha256")
    assert content_sha == sha256_json(result)
    assert result["prediction"]["components"]["goals"] == 1.2
    assert result["batch"]["input_artifact_id"] == "artifact_1"
    assert result["batch"]["cutoff_at"] == "2026-09-04T17:30:00Z"


def test_train_publishes_candidate_only_and_reuses_idempotency(tmp_path: Path, monkeypatch):
    config = _config(tmp_path)
    db = OpsDB(config.ops_db, enforce_version=False)
    service = ModelOpsService(
        config, db, analytics_store=FakeStore(), analytics_service=FakeAnalytics(),
    )

    def fake_fit(**kwargs):
        candidate = config.analytics_root / "candidate.json"
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text("{}\n", encoding="utf-8")
        kwargs["created"].append(candidate)
        return {
            "schema": "mova-model-train-result-v1", "version": kwargs["version"],
            "manifest_path": str(candidate), "manifest_sha256": "a" * 64,
            "candidate_manifest_path": str(candidate),
            "candidate_manifest_sha256": "b" * 64,
            "runtime_mutated": False,
        }

    monkeypatch.setattr(service, "_fit_and_publish", fake_fit)
    first = service.train(
        version="1.2.0", holdout="2025-26", actor="trainer", reason="weekly candidate",
        idempotency_key="train:week-35",
    )
    second = service.train(
        version="1.2.0", holdout="2025-26", actor="trainer", reason="weekly candidate",
        idempotency_key="train:week-35",
    )
    assert first["status"] == "completed" and first["runtime_mutated"] is False
    assert second["status"] == "reused" and second["job_id"] == first["job_id"]
    assert db.get_job_by_key("model:train:train:week-35")["status"] == "completed"
    with db.connect(readonly=True) as con:
        audits = con.execute(
            "select event_type,actor,payload_json from audit_events where job_id=?",
            (first["job_id"],),
        ).fetchall()
    model_audits = [row for row in audits if row["event_type"].startswith("model_")]
    assert [row["event_type"] for row in model_audits] == [
        "model_training_requested", "model_candidate_trained",
    ]
    assert model_audits[0]["actor"] == "trainer"

    with pytest.raises(ValueError, match="otro input"):
        service.train(
            version="1.2.1", holdout="2025-26", actor="trainer",
            reason="must not alias another candidate",
            idempotency_key="train:week-35",
        )


def test_failed_training_cleans_created_candidate_files(tmp_path: Path, monkeypatch):
    config = _config(tmp_path)
    service = ModelOpsService(
        config, OpsDB(config.ops_db, enforce_version=False),
        analytics_store=FakeStore(), analytics_service=FakeAnalytics(),
    )
    orphan = config.analytics_root / "orphan.json"

    def fail(**kwargs):
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.write_text("partial", encoding="utf-8")
        kwargs["created"].append(orphan)
        raise RuntimeError("fit failed")

    monkeypatch.setattr(service, "_fit_and_publish", fail)
    with pytest.raises(RuntimeError, match="fit failed"):
        service.train(
            version="1.2.1", holdout="2025-26", actor="trainer", reason="fixture",
            idempotency_key="train:failure",
        )
    assert not orphan.exists()


def test_registry_refuses_to_overwrite_a_candidate(tmp_path: Path):
    first = save(TinyModel(), "minutes", "9.9.9", {"mode": "test"},
                 artifact_root=tmp_path, overwrite=False)
    assert Path(first["artifact"]).is_absolute()
    with pytest.raises(FileExistsError):
        save(TinyModel(), "minutes", "9.9.9", {"mode": "test"},
             artifact_root=tmp_path, overwrite=False)
