"""Stable model operations facade for the autonomous harness.

Training only publishes a new, immutable candidate bundle.  Prediction,
explanation and evaluation remain separate operations, and none of them can
promote a model release or mutate the FPL account.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from mova_fpl.analytics.model_training import fit_candidate_models
from mova_fpl.data.schema import SEASONS
from mova_fpl.data.store import Store
from mova_fpl.ops.analytics_service import AnalyticsService
from mova_fpl.ops.analytics_store import AnalyticsStore
from mova_fpl.ops.collector.contracts import canonical_bytes, sha256_bytes, write_atomic
from mova_fpl.ops.db import OpsDB, new_id, sha256_json
from mova_fpl.ops.model_release import resolve_active_model_bundle
from mova_fpl.ops.tick import exclusive_lock


MODEL_CONTRACT_VERSION = "model-ops-v1"
SEMVER = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


def _assert_audit(actor: str, reason: str, idempotency_key: str) -> None:
    if not all(isinstance(value, str) and value.strip()
               for value in (actor, reason, idempotency_key)):
        raise ValueError("actor, reason e idempotency_key son obligatorios")


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ModelOpsService:
    def __init__(self, config, db: OpsDB, *, analytics_store=None,
                 analytics_service=None):
        self.config = config
        self.db = db
        self.store = analytics_store or AnalyticsStore(config)
        self.analytics = analytics_service or AnalyticsService(config, db)

    def status(self) -> dict:
        active = resolve_active_model_bundle(self.config, self.db)
        analytics = self.store.status(limit=20)
        return {
            "schema": "mova-model-ops-status-v1",
            "contract_version": MODEL_CONTRACT_VERSION,
            "interfaces": {
                "train": {"mode": "candidate_only", "promotes_runtime": False},
                "predict": {"mode": "immutable_projection", "promotes_runtime": False},
                "explain": {"mode": "read_only", "promotes_runtime": False},
                "evaluate": {"mode": "final_scorecard", "promotes_runtime": False},
            },
            "active_bundle": active,
            "analytics": analytics,
        }

    def predict(self, *, actor: str, reason: str, idempotency_key: str) -> dict:
        _assert_audit(actor, reason, idempotency_key)
        result = self.analytics.run(
            "project", actor=actor, reason=reason,
            idempotency_key=f"model:predict:{idempotency_key}",
        )
        return {"schema": "mova-model-predict-result-v1",
                "contract_version": MODEL_CONTRACT_VERSION, **result}

    def evaluate(self, *, actor: str, reason: str, idempotency_key: str) -> dict:
        _assert_audit(actor, reason, idempotency_key)
        result = self.analytics.run(
            "reconcile", actor=actor, reason=reason,
            idempotency_key=f"model:evaluate:{idempotency_key}",
        )
        return {"schema": "mova-model-evaluate-result-v1",
                "contract_version": MODEL_CONTRACT_VERSION, **result}

    def explain(self, *, batch_id: str, element: int) -> dict:
        if not isinstance(batch_id, str) or not batch_id.startswith("projection_"):
            raise ValueError("batch_id inválido")
        if isinstance(element, bool) or int(element) <= 0:
            raise ValueError("element debe ser entero positivo")
        row = self.store.projection_explanation(batch_id, int(element))
        if not row:
            raise KeyError(f"proyección ausente: {batch_id}/{element}")
        explanation = {
            "schema": "mova-model-explanation-v1",
            "contract_version": MODEL_CONTRACT_VERSION,
            "batch": {
                "batch_id": row["batch_id"], "season": row["season"],
                "target_gw": int(row["target_gw"]), "variant": row["variant"],
                "model_versions": row["model_versions"],
                "cutoff_at": row["cutoff_at"], "generated_at": row["generated_at"],
                "input_artifact_id": row["input_artifact_id"],
                "input_manifest": row["input_manifest"],
                "artifact_path": row["artifact_path"],
                "artifact_sha256": row["artifact_sha256"],
            },
            "subject": {
                "element": int(row["element"]), "fixture_id": row["fixture_id"],
                "player_name": row["player_name"], "position": row["position"],
                "team": row["team"], "opponent_team": row["opponent_team"],
            },
            "prediction": {
                "xp": float(row["xp"]),
                "xp_sd": float(row["xp_sd"]) if row["xp_sd"] is not None else None,
                "p_play": float(row["p_play"]), "p_60": float(row["p_60"]),
                "components": row["components"], "context": row["context"],
            },
        }
        explanation["content_sha256"] = sha256_json(explanation)
        return explanation

    def train(self, *, version: str, holdout: str, actor: str, reason: str,
              idempotency_key: str) -> dict:
        """Fit both model families and publish a non-active candidate manifest."""
        _assert_audit(actor, reason, idempotency_key)
        if not isinstance(version, str) or not SEMVER.fullmatch(version):
            raise ValueError("version debe usar semver X.Y.Z")
        if holdout not in SEASONS or holdout == self.config.season:
            raise ValueError("holdout debe ser una temporada cerrada conocida")
        self.db.migrate()
        canonical = self.config.canonical_db.resolve()
        if not canonical.is_file():
            raise FileNotFoundError(canonical)
        canonical_sha = _file_sha(canonical)
        identity = {
            "contract_version": MODEL_CONTRACT_VERSION,
            "version": version, "holdout": holdout,
            "canonical_sha256": canonical_sha,
            "mode": "production_candidate",
        }
        input_sha = sha256_json(identity)
        job_id, reused = self.db.start_job(
            "model_train", f"model:train:{idempotency_key}", new_id("corr"),
            input_sha256=input_sha,
        )
        if reused:
            prior = self.db.get_job_by_key(f"model:train:{idempotency_key}") or {}
            if prior.get("input_sha256") != input_sha:
                raise ValueError(
                    "idempotency_key ya fue usada con otro input de entrenamiento"
                )
            metrics = json.loads(prior.get("metrics_json") or "{}")
            if prior.get("status") != "completed":
                raise RuntimeError(
                    f"training idempotente previo terminó {prior.get('status')}"
                )
            return {**metrics, "status": "reused", "job_id": job_id}

        self.db.append_audit(
            "model_training_requested", actor=actor, job_id=job_id,
            subject_type="model_bundle_candidate", subject_id=version,
            payload={"reason": reason, "holdout": holdout,
                     "idempotency_key": idempotency_key,
                     "input_sha256": input_sha, "runtime_mutated": False},
        )
        created: list[Path] = []
        try:
            with exclusive_lock(self.config.analytics_lock_path):
                result = self._fit_and_publish(
                    job_id=job_id, version=version, holdout=holdout,
                    canonical_sha=canonical_sha, created=created,
                )
            self.db.append_audit(
                "model_candidate_trained", actor=actor, job_id=job_id,
                subject_type="model_bundle_candidate", subject_id=version,
                payload={"reason": reason, "manifest_sha256": result["manifest_sha256"],
                         "runtime_mutated": False},
            )
            self.db.finish_job(
                job_id, "completed", output_sha256=result["manifest_sha256"], metrics=result,
            )
            return {**result, "status": "completed", "job_id": job_id}
        except Exception as exc:
            for path in reversed(created):
                path.unlink(missing_ok=True)
            self.db.finish_job(job_id, "failed", error_code=type(exc).__name__,
                               error_detail=str(exc)[:2000])
            raise

    def _fit_and_publish(self, *, job_id: str, version: str, holdout: str,
                         canonical_sha: str, created: list[Path]) -> dict:
        model_root = self.config.artifact_root / "models"
        targets = [
            model_root / family / f"{family}-{version}.{suffix}"
            for family in ("minutes", "points") for suffix in ("joblib", "json")
        ]
        if any(path.exists() for path in targets):
            raise FileExistsError(f"versión candidata ya existe: {version}")
        frame = Store(self.config.canonical_db).multi_season_as_of(holdout, 39)
        if frame.empty:
            raise ValueError("dataset de entrenamiento vacío")

        created.extend([
            model_root / "minutes" / f"minutes-{version}.joblib",
            model_root / "minutes" / f"minutes-{version}.json",
            model_root / "points" / f"points-{version}.joblib",
            model_root / "points" / f"points-{version}.json",
        ])
        records = fit_candidate_models(
            frame, version=version, holdout=holdout, artifact_root=model_root,
        )
        candidate = {
            "schema": "mova-model-bundle-candidate-v1",
            "contract_version": MODEL_CONTRACT_VERSION,
            "models": {
                "minutes": {"version": version,
                            "artifact_sha256": records["minutes"]["artifact_sha256"]},
                "points": {"version": version,
                           "artifact_sha256": records["points"]["artifact_sha256"]},
            },
        }
        dataset = {
            "dataset_id": f"dataset_{canonical_sha[:24]}",
            "source": str(self.config.canonical_db), "source_sha256": canonical_sha,
            "cutoff": {"season": holdout, "gw_exclusive": 39},
            "rows": int(len(frame)),
        }
        candidate_body = canonical_bytes(candidate)
        candidate_target = (
            self.config.analytics_root / "model-training" / f"{job_id}.candidate.json"
        )
        write_atomic(candidate_target, candidate_body)
        created.append(candidate_target)
        manifest = {
            "schema": "mova-model-training-run-v1", "job_id": job_id,
            "contract_version": MODEL_CONTRACT_VERSION,
            "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "dataset_release": dataset, "candidate_bundle": candidate,
            "candidate_manifest_path": str(candidate_target),
            "candidate_manifest_sha256": sha256_bytes(candidate_body),
            "training": records,
            "runtime_mutated": False,
            "next_gate": "accepted proposal + improve release prepare/shadow/promote",
        }
        body = canonical_bytes(manifest)
        target = self.config.analytics_root / "model-training" / f"{job_id}.json"
        write_atomic(target, body)
        created.append(target)
        return {
            "schema": "mova-model-train-result-v1",
            "contract_version": MODEL_CONTRACT_VERSION,
            "version": version, "dataset_release": dataset,
            "candidate_bundle": candidate, "manifest_path": str(target),
            "manifest_sha256": sha256_bytes(body), "runtime_mutated": False,
            "candidate_manifest_path": str(candidate_target),
            "candidate_manifest_sha256": sha256_bytes(candidate_body),
        }
