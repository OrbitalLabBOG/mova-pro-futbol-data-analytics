"""Coordinador determinista e idempotente del servicio de datos."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from mova_fpl.ops.collector import fpl, odds, whoscored
from mova_fpl.ops.collector.odds_policy import plan_collection
from mova_fpl.ops.collector.store import CollectorStore, publish_coverage, publish_status
from mova_fpl.ops.db import new_id, sha256_json
from mova_fpl.ops.harness import Harness
from mova_fpl.ops.tick import exclusive_lock
from mova_fpl.postgres.store import migrate as postgres_migrate


SOURCES = ("fpl", "odds", "schedule", "events")


class CollectorService:
    def __init__(self, config, db):
        self.config = config
        self.db = db
        self.store = CollectorStore(config)

    def run(self, selection: str = "all", *, force: bool = False,
            actor: str = "mova-collector", reason: str | None = None,
            idempotency_key: str | None = None,
            now: datetime | None = None) -> dict:
        if selection not in {"all", *SOURCES}:
            raise ValueError(f"fuente inválida: {selection}")
        if force and (not reason or not idempotency_key):
            raise ValueError("collect --force exige reason e idempotency_key")
        current = now or datetime.now(timezone.utc)
        self.config.validate()
        self.config.validate_postgres()
        self.db.migrate()
        bucket = int(current.timestamp()) // 900
        key = idempotency_key if force else f"collect:{selection}:{bucket}"
        correlation_id = new_id("corr")
        with exclusive_lock(self.config.collector_lock_path):
            job_id, reused = self.db.start_job("data_collection", key, correlation_id)
            if reused:
                existing = self.db.get_job_by_key(key)
                return {"status": "reused", "job_id": job_id,
                        "existing_status": existing.get("status") if existing else None}
            if force:
                self.db.append_audit(
                    "forced_collection_requested", actor=actor,
                    correlation_id=correlation_id, job_id=job_id,
                    payload={"selection": selection, "reason": reason,
                             "idempotency_key": key},
                )
            harness = Harness(self.db, job_id, correlation_id=correlation_id)
            try:
                result = self._run(selection, current, force, job_id, correlation_id, harness)
            except Exception as exc:
                self.db.finish_job(job_id, "failed", error_code=type(exc).__name__,
                                   error_detail=str(exc)[:2000])
                self.db.open_incident_once(
                    "P1", "Servicio de datos MOVA falló",
                    correlation_id=correlation_id, job_id=job_id,
                    detail={"error_code": type(exc).__name__, "error": str(exc)[:1000]},
                )
                raise
            self.db.finish_job(job_id, result["status"],
                               output_sha256=sha256_json(result), metrics=result)
            return {"job_id": job_id, "correlation_id": correlation_id, **result}

    def _run(self, selection: str, now: datetime, force: bool, job_id: str,
             correlation_id: str, harness: Harness) -> dict:
        harness.call("postgres_data_migrate", lambda: postgres_migrate(self.config))
        wanted = list(SOURCES) if selection == "all" else [selection]
        results = []
        # Events depend on a schedule. If the cache is absent, schedule becomes
        # due even for an explicit `collect events`.
        if "events" in wanted and not whoscored.schedule_file(self.config).is_file() \
                and "schedule" not in wanted:
            wanted.insert(0, "schedule")
        for name in wanted:
            cadence = {
                "fpl": self.config.collector_fpl_cadence_seconds,
                "odds": self.config.collector_odds_cadence_seconds,
                "schedule": self.config.collector_schedule_cadence_seconds,
                "events": self.config.collector_events_cadence_seconds,
            }[name]
            source_name = {
                "fpl": "fpl_official", "odds": "market_odds",
                "schedule": "whoscored_schedule", "events": "whoscored_events",
            }[name]
            odds_plan = None
            if name == "odds":
                cursor, deadline = self.store.odds_context(now=now)
                odds_plan = plan_collection(
                    self.config, now=now, deadline=deadline, cursor=cursor, force=force
                )
                due = odds_plan.due
                cadence = odds_plan.cadence_seconds
            else:
                due, cursor = self.store.is_due(
                    source_name, cadence, now=now, force=force
                )
            if not due:
                results.append({"source": source_name, "status": "skipped",
                                "reason": (odds_plan.reason if odds_plan
                                           else "cadence_not_due"),
                                "last_success_at": str(cursor.get("last_success_at"))
                                if cursor else None, "cadence_seconds": cadence,
                                **({"policy": odds_plan.as_dict()} if odds_plan else {})})
                continue
            run_id = self.store.start(source_name, job_id)
            try:
                if name == "fpl":
                    output = harness.call("collect_fpl_official", lambda: fpl.collect(
                        self.config, self.store, run_id, now=now
                    ))
                elif name == "odds":
                    output = harness.call("collect_market_odds", lambda: odds.collect(
                        self.config, self.store, run_id, plan=odds_plan, now=now
                    ))
                elif name == "schedule":
                    output = harness.call("collect_whoscored_schedule", lambda: (
                        whoscored.collect_schedule(
                            self.config, self.store, run_id, now=now, refresh=True
                        )
                    ))
                else:
                    output = harness.call("collect_whoscored_events", lambda: (
                        whoscored.collect_events(self.config, self.store, run_id, now=now)
                    ))
                rendered = output.as_dict()
                self.store.finish(run_id, source=source_name, cadence_seconds=cadence,
                                  status=output.status, output=rendered)
                incident_title = f"Collector {source_name} degradado"
                if output.status == "completed":
                    self.db.resolve_incidents(
                        incident_title, resolution=f"fuente recuperada en {run_id}"
                    )
                    if source_name == "market_odds":
                        self.db.resolve_incidents(
                            "Collector football_data_odds degradado",
                            resolution=f"adapter sustituido por market_odds en {run_id}",
                        )
                elif output.status == "degraded":
                    self.db.open_incident_once(
                        "P2", incident_title, correlation_id=correlation_id, job_id=job_id,
                        detail={"run_id": run_id, "quality": output.quality},
                    )
                results.append(rendered)
            except Exception as exc:  # una fuente no silencia ni aborta las otras
                self.store.finish(run_id, source=source_name, cadence_seconds=cadence,
                                  status="failed", error=exc)
                self.db.open_incident_once(
                    "P2", f"Collector {source_name} degradado",
                    correlation_id=correlation_id, job_id=job_id,
                    detail={"run_id": run_id, "error_code": type(exc).__name__,
                            "error": str(exc)[:1000]},
                )
                results.append({"source": source_name, "status": "failed",
                                "run_id": run_id, "error_code": type(exc).__name__,
                                "error": str(exc)[:1000]})
        bad = [item for item in results if item["status"] in {"failed", "degraded"}]
        completed = [item for item in results if item["status"] == "completed"]
        digest = hashlib.sha256(
            "|".join(str(item.get("payload_sha256", "")) for item in results).encode()
        ).hexdigest()
        result = {
            "status": "degraded" if bad else "completed", "selection": selection,
            "sources": results, "completed_sources": len(completed),
            "degraded_sources": len(bad), "output_fingerprint": digest,
        }
        snapshot = self.store.status()
        snapshot["generated_at"] = now.isoformat(timespec="milliseconds")
        snapshot["last_collection"] = result
        publish_status(self.config, snapshot)
        publish_coverage(self.config, self.store.coverage())
        return result
