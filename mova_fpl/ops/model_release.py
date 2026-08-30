"""Release controlado de bundles de modelos con shadow, promoción y rollback."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from mova_fpl.ops.analytics_store import AnalyticsStore
from mova_fpl.ops.db import OpsDB

FAMILIES = ("minutes", "points")
DEFAULT_POLICY = {
    "min_final_gameweeks": 3,
    "max_drift_alerts": 0,
    "max_points_mae_ratio": 1.05,
    "max_p60_ece_delta": 0.02,
}


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _model_root(config) -> Path:
    return (config.artifact_root / "models").resolve()


def _validate_version(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value):
        raise ValueError("cada versión de modelo debe usar semver X.Y.Z")
    return value


def _seal_bundle(config, models: dict) -> dict:
    if not isinstance(models, dict) or set(models) != set(FAMILIES):
        raise ValueError("models debe contener exactamente minutes y points")
    root = _model_root(config)
    sealed = {}
    for name in FAMILIES:
        source = models[name]
        if not isinstance(source, dict):
            raise ValueError(f"models.{name} debe ser objeto")
        version = _validate_version(source.get("version"))
        expected = source.get("artifact_sha256")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError(f"models.{name}.artifact_sha256 inválido")
        path = (root / name / f"{name}-{version}.joblib").resolve()
        if root not in path.parents or not path.is_file():
            raise ValueError(f"artefacto de {name} no existe dentro de model root")
        observed = _hash_file(path)
        if observed != expected:
            raise ValueError(f"hash de artefacto no coincide: {name}")
        sidecar_path = path.with_suffix(".json")
        metrics = {}
        if sidecar_path.is_file():
            try:
                sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"sidecar inválido: {name}") from exc
            if (sidecar.get("name") != name or sidecar.get("version") != version
                    or sidecar.get("artifact_sha256") != observed):
                raise ValueError(f"sidecar no corresponde al artefacto: {name}")
            metrics = sidecar.get("metrics") if isinstance(sidecar.get("metrics"), dict) else {}
        sealed[name] = {
            "version": version,
            "artifact_path": str(path),
            "artifact_sha256": observed,
            "metrics": metrics,
        }
    return {"schema": "mova-model-bundle-v1", "models": sealed}


def _validate_policy(raw: object) -> dict:
    if raw is None:
        return dict(DEFAULT_POLICY)
    if not isinstance(raw, dict) or not set(raw) <= set(DEFAULT_POLICY):
        raise ValueError("promotion_policy contiene campos no permitidos")
    policy = {**DEFAULT_POLICY, **raw}
    integers = ("min_final_gameweeks", "max_drift_alerts")
    if any(not isinstance(policy[key], int) for key in integers):
        raise ValueError("min_final_gameweeks y max_drift_alerts deben ser enteros")
    if not 3 <= policy["min_final_gameweeks"] <= 10:
        raise ValueError("min_final_gameweeks debe estar entre 3 y 10")
    if not 0 <= policy["max_drift_alerts"] <= 1:
        raise ValueError("max_drift_alerts debe estar entre 0 y 1")
    if not 1.0 <= float(policy["max_points_mae_ratio"]) <= 1.20:
        raise ValueError("max_points_mae_ratio debe estar entre 1.0 y 1.20")
    if not 0 <= float(policy["max_p60_ece_delta"]) <= 0.10:
        raise ValueError("max_p60_ece_delta debe estar entre 0 y 0.10")
    policy["max_points_mae_ratio"] = float(policy["max_points_mae_ratio"])
    policy["max_p60_ece_delta"] = float(policy["max_p60_ece_delta"])
    return policy


def _assert_audit_fields(*values: str) -> None:
    if not all(isinstance(value, str) and value.strip() for value in values):
        raise ValueError("actor, reason e idempotency_key son obligatorios")


def resolve_active_model_bundle(config, db: OpsDB) -> dict:
    """Resuelve el puntero activo y comprueba hashes antes de inferencia."""
    pointer = db.active_model_bundle()
    if pointer is None:
        models = {
            "minutes": {"version": config.analytics_minutes_version},
            "points": {"version": config.analytics_points_version},
        }
        for name in FAMILIES:
            path = _model_root(config) / name / f"{name}-{models[name]['version']}.joblib"
            if not path.is_file():
                raise ValueError(f"artefacto baseline no existe: {name}")
            models[name]["artifact_sha256"] = _hash_file(path)
        bundle = _seal_bundle(config, models)
        bundle["release_id"] = None
        bundle["source"] = "runtime_config"
        return bundle
    if pointer.get("schema") != "mova-active-model-bundle-v1":
        raise ValueError("active_model_bundle tiene schema inválido")
    bundle = _seal_bundle(config, pointer.get("models"))
    bundle["release_id"] = pointer.get("release_id")
    bundle["source"] = "runtime_control"
    return bundle


def verify_model_bundle(config, manifest: dict) -> dict:
    if not isinstance(manifest, dict) or manifest.get("schema") != "mova-model-bundle-v1":
        raise ValueError("model bundle tiene schema inválido")
    return _seal_bundle(config, manifest.get("models"))


class ModelReleaseService:
    def __init__(self, config, db: OpsDB, analytics_store=None):
        self.config = config
        self.db = db
        self.analytics = analytics_store or AnalyticsStore(config)

    def status(self) -> dict:
        state = self.db.model_bundle_release_status()
        shadow = next((row for row in state["releases"] if row["status"] == "shadow"), None)
        if shadow:
            try:
                state["shadow_gate"] = self.analytics.model_release_shadow_gate(
                    season=self.config.season, release=shadow
                )
            except Exception as exc:  # estado SQLite sigue siendo consultable sin PostgreSQL
                state["shadow_gate"] = {"status": "unavailable",
                                        "error_code": type(exc).__name__}
        else:
            state["shadow_gate"] = None
        return state

    def prepare(self, *, proposal_id: str, manifest_path: Path, actor: str,
                reason: str, idempotency_key: str) -> dict:
        _assert_audit_fields(actor, reason, idempotency_key)
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("no se pudo leer el manifest de release") from exc
        if not isinstance(raw, dict) or raw.get("schema") != "mova-model-bundle-candidate-v1":
            raise ValueError("schema del manifest de release inválido")
        candidate = _seal_bundle(self.config, raw.get("models"))
        active = resolve_active_model_bundle(self.config, self.db)
        baseline = {"schema": active["schema"], "models": active["models"],
                    "source_release_id": active.get("release_id")}
        if {name: candidate["models"][name]["artifact_sha256"] for name in FAMILIES} == {
            name: baseline["models"][name]["artifact_sha256"] for name in FAMILIES
        }:
            raise ValueError("el candidato es idéntico al bundle activo")
        policy = _validate_policy(raw.get("promotion_policy"))
        return self.db.prepare_model_bundle_release(
            proposal_id=proposal_id, candidate=candidate, baseline=baseline,
            promotion_policy=policy, actor=actor, reason=reason,
            idempotency_key=idempotency_key,
        )

    def shadow(self, *, release_id: str, actor: str, reason: str,
               idempotency_key: str) -> dict:
        _assert_audit_fields(actor, reason, idempotency_key)
        release = self._release(release_id)
        candidate = _seal_bundle(self.config, release["candidate_manifest"]["models"])
        baseline = _seal_bundle(self.config, release["baseline_manifest"]["models"])
        evidence = {"candidate_sha256": _bundle_hashes(candidate),
                    "baseline_sha256": _bundle_hashes(baseline),
                    "shadow_variant": f"model_release_shadow:{release_id}"}
        return self.db.transition_model_bundle_release(
            release_id, to_status="shadow", evidence=evidence, actor=actor,
            reason=reason, idempotency_key=idempotency_key,
        )

    def promote(self, *, release_id: str, actor: str, reason: str,
                idempotency_key: str) -> dict:
        _assert_audit_fields(actor, reason, idempotency_key)
        reused = self._reused_event(release_id, idempotency_key, "promoted")
        if reused:
            return reused
        release = self._release(release_id)
        if release["status"] != "shadow":
            raise ValueError("solo un release en shadow puede promoverse")
        candidate = _seal_bundle(self.config, release["candidate_manifest"]["models"])
        gate = self.analytics.model_release_shadow_gate(
            season=self.config.season, release=release
        )
        if gate["status"] != "passed":
            raise ValueError(f"shadow gate no aprobado: {gate['status']}")
        evidence = {"gate": gate, "candidate_sha256": _bundle_hashes(candidate)}
        return self.db.transition_model_bundle_release(
            release_id, to_status="promoted", evidence=evidence, actor=actor,
            reason=reason, idempotency_key=idempotency_key,
        )

    def rollback(self, *, release_id: str, actor: str, reason: str,
                 idempotency_key: str) -> dict:
        _assert_audit_fields(actor, reason, idempotency_key)
        release = self._release(release_id)
        candidate = _seal_bundle(self.config, release["candidate_manifest"]["models"])
        baseline = _seal_bundle(self.config, release["baseline_manifest"]["models"])
        evidence = {"candidate_sha256": _bundle_hashes(candidate),
                    "baseline_sha256": _bundle_hashes(baseline),
                    "rollback_verified": True}
        return self.db.transition_model_bundle_release(
            release_id, to_status="rolled_back", evidence=evidence, actor=actor,
            reason=reason, idempotency_key=idempotency_key,
        )

    def _release(self, release_id: str) -> dict:
        if not isinstance(release_id, str) or not release_id.strip():
            raise ValueError("release_id es obligatorio")
        release = next((row for row in self.db.model_bundle_release_status()["releases"]
                        if row["release_id"] == release_id), None)
        if not release:
            raise ValueError("release_id no existe")
        return release

    def _reused_event(self, release_id: str, idempotency_key: str,
                      to_status: str) -> dict | None:
        state = self.db.model_bundle_release_status()
        event = next((row for row in state["events"]
                      if row["idempotency_key"] == idempotency_key), None)
        if not event:
            return None
        if event["release_id"] != release_id or event["to_status"] != to_status:
            raise ValueError("idempotency_key ya usada con otra transición")
        return {"status": "reused", "release_id": release_id,
                "release_status": to_status, "event_id": event["release_event_id"],
                "runtime_mutated": to_status in {"promoted", "rolled_back"}}


def _bundle_hashes(bundle: dict) -> dict:
    return {name: bundle["models"][name]["artifact_sha256"] for name in FAMILIES}
