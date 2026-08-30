"""Servicio idempotente de proyección, reconciliación y drift por gameweek."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from mova_fpl.analytics import (
    assess_drift, evaluate_gameweek_for_season, project_snapshot, projection_signature,
)
from mova_fpl.ops.analytics_store import AnalyticsStore, publish_status
from mova_fpl.ops.collector.contracts import canonical_bytes, sha256_bytes, write_atomic
from mova_fpl.ops.db import new_id, sha256_json
from mova_fpl.ops.harness import Harness
from mova_fpl.ops.tick import exclusive_lock
from mova_fpl.postgres.store import migrate as postgres_migrate


def _sha(value: dict) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _next_event(boot: dict, now: datetime) -> dict | None:
    explicit = next((item for item in boot.get("events", []) if item.get("is_next")), None)
    candidates = [item for item in boot.get("events", [])
                  if datetime.fromisoformat(item["deadline_time"].replace("Z", "+00:00")) > now]
    return explicit or min(candidates, key=lambda item: item["deadline_time"], default=None)


class AnalyticsService:
    def __init__(self, config, db):
        self.config = config
        self.db = db
        self.store = AnalyticsStore(config)

    def run(self, action: str = "run", *, now: datetime | None = None,
            actor: str | None = None, reason: str | None = None,
            idempotency_key: str | None = None) -> dict:
        if action not in {"run", "project", "reconcile"}:
            raise ValueError(f"acción analytics inválida: {action}")
        audit_values = (actor, reason, idempotency_key)
        if any(value is not None for value in audit_values) and not all(
            isinstance(value, str) and value.strip() for value in audit_values
        ):
            raise ValueError("actor, reason e idempotency_key deben venir juntos")
        current = now or datetime.now(timezone.utc)
        self.config.validate()
        self.config.validate_postgres()
        self.db.migrate()
        bucket = int(current.timestamp()) // 1800
        key = idempotency_key or f"analytics:{action}:{bucket}"
        correlation_id = new_id("corr")
        with exclusive_lock(self.config.analytics_lock_path):
            job_id, reused = self.db.start_job("model_analytics", key, correlation_id)
            if reused:
                return {"status": "reused", "job_id": job_id}
            if actor is not None:
                self.db.append_audit(
                    "model_operation_requested", actor=actor,
                    correlation_id=correlation_id, job_id=job_id,
                    subject_type="model_operation", subject_id=action,
                    payload={"reason": reason, "idempotency_key": idempotency_key},
                )
            harness = Harness(self.db, job_id, correlation_id=correlation_id)
            try:
                harness.call("postgres_analytics_migrate", lambda: postgres_migrate(self.config))
                result = {"status": "completed", "action": action}
                if action in {"run", "project"}:
                    result["projection"] = harness.call(
                        "analytics_project", lambda: self.project(current)
                    )
                if action in {"run", "reconcile"}:
                    result["reconciliation"] = harness.call(
                        "analytics_reconcile", self.reconcile
                    )
                state = self.store.status()
                state["last_run"] = result
                publish_status(self.config, state)
                if action in {"run", "reconcile"}:
                    from mova_fpl.ops.causal_review import CausalReviewerService

                    reviewer = CausalReviewerService(self.config, self.db)
                    result["causal_reviews"] = []
                    for gw in self.db.pending_causal_review_gws(self.config.season):
                        try:
                            causal = reviewer.run(
                                gw=gw, actor="mova-analytics",
                                reason="review causal posterior a scorecard final",
                                idempotency_key=f"causal:{self.config.season}:gw{gw}:v1",
                                analytics_state=state,
                            )
                        except Exception as exc:  # reviewer no invalida scorecards ya sellados
                            self.db.open_incident_once(
                                "P2", f"Causal review GW{gw} falló",
                                correlation_id=correlation_id,
                                detail={"error_code": type(exc).__name__,
                                        "error": str(exc)[:1000]},
                            )
                            causal = {"status": "failed", "gw": gw,
                                      "error_code": type(exc).__name__}
                        result["causal_reviews"].append(causal)
                result["analytics_status"] = state["status"]
                self.db.finish_job(job_id, "completed", output_sha256=sha256_json(result),
                                   metrics=result)
                return {"job_id": job_id, "correlation_id": correlation_id, **result}
            except Exception as exc:
                self.db.finish_job(job_id, "failed", error_code=type(exc).__name__,
                                   error_detail=str(exc)[:2000])
                self.db.open_incident_once(
                    "P2", "Analytics service MOVA falló", correlation_id=correlation_id,
                    job_id=job_id, detail={"error_code": type(exc).__name__,
                                           "error": str(exc)[:1000]},
                )
                raise

    def project(self, now: datetime) -> dict:
        artifact = self.store.latest_fpl_artifact()
        if not artifact:
            return {"status": "skipped", "reason": "no_fpl_artifact"}
        directory = Path(artifact["artifact_path"])
        boot_path, fixtures_path = directory / "bootstrap-static.json", directory / "fixtures.json"
        if not boot_path.is_file() or not fixtures_path.is_file():
            raise FileNotFoundError("artifact FPL sin bootstrap-static.json o fixtures.json")
        boot = json.loads(boot_path.read_text(encoding="utf-8"))
        fixtures = json.loads(fixtures_path.read_text(encoding="utf-8"))
        event = _next_event(boot, now)
        if not event:
            return {"status": "skipped", "reason": "season_complete"}
        gw, cutoff = int(event["id"]), event["deadline_time"]
        deadline = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
        observed = artifact["observed_at"]
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        if now >= deadline or observed >= deadline:
            return {"status": "skipped", "reason": "deadline_closed", "gw": gw}

        from mova_fpl.ops.model_release import (
            resolve_active_model_bundle, verify_model_bundle,
        )

        active_bundle = resolve_active_model_bundle(self.config, self.db)
        active_minutes = active_bundle["models"]["minutes"]["version"]
        active_points = active_bundle["models"]["points"]["version"]

        output = self.config.analytics_root / "projections" / self.config.season / f"gw{gw:02d}"

        def identity(signature: dict, variant: str, extra: dict | None = None) -> dict:
            return {"input_artifact_id": artifact["artifact_id"],
                    "season": self.config.season, "gw": gw, "variant": variant,
                    **signature, **(extra or {})}

        def persist(projection: dict, variant: str, status: str,
                    identity_: dict) -> dict:
            idempotency_key = _sha(identity_)
            payload = {"schema": "mova-player-projections-v1", "identity": identity_,
                       "cutoff_at": cutoff, "generated_at": now.isoformat(),
                       "players": projection["rows"]}
            body = canonical_bytes(payload)
            path = output / f"{variant}-{idempotency_key[:12]}.json"
            write_atomic(path, body)
            batch_id, reused = self.store.save_projection(
                idempotency_key=idempotency_key, season=self.config.season, gw=gw,
                variant=variant, versions=projection["versions"], cutoff_at=cutoff,
                input_artifact_id=artifact["artifact_id"], manifest=identity_,
                rows=projection["rows"], status=status, artifact_path=str(path),
                artifact_sha256=sha256_bytes(body),
            )
            return {"status": "reused" if reused else "completed", "batch_id": batch_id,
                    "variant": variant, "players": len(projection["rows"])}

        def cached_or_project(variant: str, status: str, signature: dict,
                              extra: dict | None = None,
                              market_context: list[dict] | None = None) -> dict:
            identity_ = identity(signature, variant, extra)
            existing = self.store.projection_by_key(_sha(identity_))
            if existing:
                return {"status": "reused", "batch_id": existing["batch_id"],
                        "variant": variant, "players": existing["player_count"]}
            projection = project_snapshot(
                boot=boot, fixtures=fixtures, season=self.config.season, gw=gw,
                minutes_version=active_minutes,
                points_version=active_points,
                market_context=market_context,
            )
            return persist(projection, variant, status, identity_)

        baseline_signature = projection_signature(
            active_minutes, active_points,
            market=False,
        )
        batches = [cached_or_project("baseline", "approved", baseline_signature)]
        market = self.store.market_context(
            fpl_artifact_id=artifact["artifact_id"], season=self.config.season,
            gw=gw, as_of=min(now, deadline),
        )
        quality = market["quality"]
        if (market["artifact_id"] and quality["coverage_ratio"] == 1.0
                and quality["minimum_bookmakers"] >= 5):
            shadow_signature = projection_signature(
                active_minutes, active_points,
                market=True,
            )
            batches.append(cached_or_project(
                "odds_cs_shadow", "shadow", shadow_signature,
                {"market_artifact_id": market["artifact_id"],
                 "market_weight": 0.95, "market_quality": quality},
                market_context=market["context"],
            ))
            odds_status = "projected_shadow"
        else:
            odds_status = "unavailable_or_incomplete"
        release_shadow = self.db.shadow_model_bundle_release()
        model_release_status = "inactive"
        if release_shadow:
            release_id = release_shadow["release_id"]
            variant = f"model_release_shadow:{release_id}"
            try:
                candidate = verify_model_bundle(
                    self.config, release_shadow["candidate_manifest"]
                )
                candidate_minutes = candidate["models"]["minutes"]["version"]
                candidate_points = candidate["models"]["points"]["version"]
                signature = projection_signature(
                    candidate_minutes, candidate_points, market=False
                )
                identity_ = identity(signature, variant, {"release_id": release_id})
                existing = self.store.projection_by_key(_sha(identity_))
                if existing:
                    batch = {"status": "reused", "batch_id": existing["batch_id"],
                             "variant": variant, "players": existing["player_count"]}
                else:
                    projection = project_snapshot(
                        boot=boot, fixtures=fixtures, season=self.config.season, gw=gw,
                        minutes_version=candidate_minutes,
                        points_version=candidate_points,
                    )
                    batch = persist(projection, variant, "shadow", identity_)
                batches.append(batch)
                model_release_status = "projected_shadow"
            except Exception as exc:  # el candidato nunca invalida el baseline productivo
                self.db.open_incident_once(
                    "P2", f"Shadow model release {release_id} falló",
                    detail={"error_code": type(exc).__name__,
                            "error": str(exc)[:1000], "gw": gw},
                )
                model_release_status = "failed_shadow"
        return {"status": "completed", "gw": gw, "batches": batches,
                "active_model_bundle": {"release_id": active_bundle.get("release_id"),
                                        "source": active_bundle["source"],
                                        "minutes": active_minutes,
                                        "points": active_points},
                "market": {"status": odds_status, "quality": quality,
                           "artifact_id": market["artifact_id"]},
                "model_release_shadow": {"status": model_release_status,
                                         "release_id": (release_shadow or {}).get("release_id")},
                "events_signal": "rejected_by_experiment"}

    def reconcile(self) -> dict:
        evaluations = []
        for batch in self.store.pending_batches(self.config.season):
            actual, artifact_id, checked = self.store.actual_frame(
                batch["season"], batch["target_gw"]
            )
            if actual.empty or not checked or not artifact_id:
                evaluations.append({"batch_id": batch["batch_id"], "gw": batch["target_gw"],
                                    "status": "waiting_for_data_checked"})
                continue
            predictions = self.store.projection_frame(batch["batch_id"])
            evaluated = evaluate_gameweek_for_season(predictions, actual, batch["season"])
            references = self.store.reference_metrics(
                batch, limit=self.config.analytics_reference_gameweeks
            )
            drift = assess_drift(
                evaluated["metrics"], references,
                min_reference=self.config.analytics_reference_gameweeks,
            )
            evaluation_key = _sha({"batch_id": batch["batch_id"],
                                   "actual_artifact_id": artifact_id, "settlement": "final"})
            evaluation_id, reused = self.store.save_evaluation(
                idempotency_key=evaluation_key, batch=batch, settlement="final",
                metrics=evaluated["metrics"], drift=drift,
                components=evaluated["components"], actual_artifact_id=artifact_id,
            )
            incident_title = (f"Drift modelo FPL {batch['season']} GW{batch['target_gw']} "
                              f"{batch['variant']}")
            if drift["status"] == "alert":
                self.db.open_incident_once(
                    "P2", incident_title,
                    detail={"evaluation_id": evaluation_id, "variant": batch["variant"],
                            "reasons": drift["reasons"]},
                )
            elif drift["status"] in {"healthy", "watch"}:
                self.db.resolve_incidents(
                    incident_title, resolution=f"scorecard corregido {evaluation_id}: "
                    f"{drift['status']}"
                )
            evaluations.append({"evaluation_id": evaluation_id, "batch_id": batch["batch_id"],
                                "gw": batch["target_gw"], "status": "reused" if reused else "final",
                                "drift_status": drift["status"]})
        return {"status": "completed", "evaluations": evaluations,
                "evaluated": sum(item.get("status") == "final" for item in evaluations),
                "waiting": sum(item.get("status") == "waiting_for_data_checked"
                               for item in evaluations)}
