"""Tick idempotente del operador autónomo, seguro por defecto."""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import shutil
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from mova_fpl.data.snapshot import capture_bytes
from mova_fpl.data.live import historical_team_mismatches, settled_gws
from mova_fpl.data.sources import (fetch_bootstrap, fetch_element_summary,
                                   fetch_event_live, fetch_fixtures)
from mova_fpl.ops.decision_envelope import build_envelope
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB, canonical_json, new_id, sha256_json, utcnow
from mova_fpl.ops.harness import Harness
from mova_fpl.ops.schedule import (
    phase_for,
    private_state_cadence_seconds,
    public_state_cadence_seconds,
    select_event,
)
from mova_fpl.ops.strategy import StrategicContextService

LOG = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]

class LockBusy(RuntimeError):
    pass


@contextmanager
def exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LockBusy(f"otro tick conserva {path}") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(f"pid={os.getpid()} acquired_at={utcnow()}\n")
        handle.flush()
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def memory_available_bytes() -> int:
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    return 0


def resources(path: Path) -> dict:
    path.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(path)
    load = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0
    return {
        "memory_available_bytes": memory_available_bytes(),
        "disk_free_bytes": usage.free,
        "load_1m": round(float(load), 3),
    }


def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class TickRunner:
    def __init__(self, config: RuntimeConfig, db: OpsDB):
        self.config = config
        self.db = db

    def run(self, *, now: datetime | None = None, force: bool = False,
            actor: str = "mova-ops", reason: str | None = None,
            idempotency_key: str | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        if force and (not reason or not idempotency_key):
            raise ValueError("un tick forzado exige reason e idempotency_key")
        self.config.validate()
        self.db.migrate()
        self.db.ensure_defaults(
            mode=self.config.mode, action_level=self.config.action_level,
            compliance_gate=self.config.compliance_gate,
            browser_writes=self.config.enable_browser_writes,
        )
        bucket = int(now.timestamp()) // self.config.tick_bucket_seconds
        correlation_id = new_id("corr")
        job_key = idempotency_key if force else f"tick:{bucket}"

        with exclusive_lock(self.config.lock_path):
            job_id, reused = self.db.start_job("tick", job_key, correlation_id)
            if reused:
                existing = self.db.get_job_by_key(job_key)
                return {"status": "reused", "job_id": job_id,
                        "existing_status": existing.get("status") if existing else None}
            if force:
                self.db.append_audit(
                    "forced_tick_requested", actor=actor, correlation_id=correlation_id,
                    job_id=job_id, payload={"reason": reason, "idempotency_key": job_key},
                )
            harness = Harness(self.db, job_id, correlation_id=correlation_id)
            try:
                result = self._run(job_id, correlation_id, harness, now, force=force)
            except Exception as exc:
                self.db.finish_job(
                    job_id, "failed", error_code=type(exc).__name__,
                    error_detail=str(exc)[:2000],
                )
                self.db.open_incident(
                    "P1", "Tick MOVA falló", correlation_id=correlation_id, job_id=job_id,
                    detail={"error_code": type(exc).__name__, "error": str(exc)[:1000]},
                )
                raise
            self.db.finish_job(
                job_id, result["status"], output_sha256=sha256_json(result), metrics=result,
            )
            self.db.resolve_incidents(
                "Tick MOVA falló", resolution=f"tick recuperado en {job_id}", actor=actor,
            )
            return {"job_id": job_id, "correlation_id": correlation_id, **result}

    def _run(self, job_id: str, correlation_id: str, harness: Harness,
             now: datetime, *, force: bool = False) -> dict:
        resource_state = harness.call("resource_gate", lambda: resources(self.config.artifact_root))
        disk_ok = resource_state["disk_free_bytes"] >= self.config.disk_gate_bytes
        if not disk_ok:
            raise RuntimeError(
                f"disk gate: {resource_state['disk_free_bytes']} < {self.config.disk_gate_bytes}"
            )
        memory_ok = resource_state["memory_available_bytes"] >= self.config.memory_gate_bytes

        known = self.db.status().get("cycle")
        if known:
            deadline = datetime.fromisoformat(str(known["deadline_at"]).replace("Z", "+00:00"))
            if now < deadline:
                phase = phase_for(str(known["deadline_at"]), now)
                previous = self.db.latest_snapshot(str(known["cycle_id"]))
                if previous:
                    observed = datetime.fromisoformat(
                        str(previous["captured_at"]).replace("Z", "+00:00")
                    )
                    age = max(0, int((now - observed).total_seconds()))
                    cadence = public_state_cadence_seconds(str(known["deadline_at"]), now)
                    if age < cadence and not force:
                        self.db.record_health(
                            "mova-worker", "ok",
                            memory_available_bytes=resource_state["memory_available_bytes"],
                            disk_free_bytes=resource_state["disk_free_bytes"],
                            load_1m=resource_state["load_1m"],
                            detail={"gw": known["gw"], "phase": phase,
                                    "reason": "cadence_not_due", "source_age_seconds": age,
                                    "cadence_seconds": cadence},
                        )
                        return {
                            "status": "completed", "season": known["season"],
                            "gw": known["gw"], "deadline_at": known["deadline_at"],
                            "phase": phase, "work": "skipped_cadence",
                            "source_age_seconds": age, "cadence_seconds": cadence,
                            **resource_state,
                        }

        # Keep the two endpoints as separate audited steps. The bootstrap carries
        # events/player state while fixtures has a different latency and change
        # profile; combining them made a slow source impossible to identify.
        source = {
            "bootstrap": harness.call("fetch_fpl_bootstrap_events", fetch_bootstrap),
            "fixtures": harness.call("fetch_fpl_fixtures", fetch_fixtures),
        }
        boot = json.loads(source["bootstrap"])
        event = select_event(boot, now)
        gw, deadline = int(event["id"]), str(event["deadline_time"])
        event_history = {
            event_gw: harness.call(
                f"fetch_fpl_event_live_gw{event_gw:02d}",
                lambda event_gw=event_gw: fetch_event_live(event_gw),
            )
            for event_gw in settled_gws(boot, gw)
        }
        fixtures = json.loads(source["fixtures"])
        event_payloads = {
            event_gw: json.loads(payload) for event_gw, payload in event_history.items()
        }
        element_summaries = {
            element: harness.call(
                f"fetch_fpl_element_summary_{element}",
                lambda element=element: fetch_element_summary(element),
            )
            for element in historical_team_mismatches(
                boot, fixtures, event_payloads,
            )
        }
        phase = phase_for(deadline, now)
        cycle_id = self.db.upsert_cycle(self.config.season, gw, deadline, phase=phase)
        self.db.bind_job_cycle(job_id, cycle_id)
        harness.cycle_id = cycle_id

        def save_snapshot():
            out_root = self.config.artifact_root / "sources" / "fpl_live"
            dest, manifest = capture_bytes(
                self.config.season, gw, out_root, source["bootstrap"], source["fixtures"],
                event_raw=event_history,
                element_summary_raw=element_summaries,
                captured_at=now.isoformat(timespec="seconds"),
            )
            manifest_path = dest / "manifest.json"
            payload_sha = hashlib.sha256(
                source["bootstrap"] + b"\n" + source["fixtures"] + b"\n"
                + b"\n".join(event_history[key] for key in sorted(event_history))
                + b"\n" + b"\n".join(
                    element_summaries[key] for key in sorted(element_summaries)
                )
            ).hexdigest()
            self.db.add_snapshot(
                job_id=job_id, cycle_id=cycle_id, source_name="fpl_official",
                captured_at=manifest["captured_at"], artifact_path=str(dest),
                manifest_sha256=_sha_file(manifest_path), payload_sha256=payload_sha,
                freshness_seconds=0, quality_status="valid", quality=manifest,
            )
            return {"path": str(dest), "manifest": manifest,
                    "manifest_sha256": _sha_file(manifest_path)}

        snapshot = harness.call("seal_snapshot", save_snapshot)
        decision = None
        execution_preflight = None
        degraded = not memory_ok
        verified_cycle = self.db.seal_verified_decision_cycle(
            cycle_id, correlation_id=correlation_id, job_id=job_id,
        )
        if self.config.enable_shadow_decision and verified_cycle:
            decision = {
                "status": "skipped",
                "reason": "verified_execution_exists",
                **verified_cycle,
            }
        elif self.config.enable_shadow_decision and memory_ok:
            prepared = harness.call(
                "seal_cycle_manifest",
                lambda: StrategicContextService(self.config, self.db).prepare(now=now),
            )
            decision = self._shadow_decision(
                harness, job_id, cycle_id, gw, deadline, now, Path(snapshot["path"]),
                correlation_id, prepared,
            )
            degraded = degraded or decision.get("status") != "completed"
            if decision.get("status") == "completed" and decision.get("envelope_id"):
                from mova_fpl.ops.execution import ExecutionService

                execution_preflight = harness.call(
                    "execution_preflight",
                    lambda: ExecutionService(self.config, self.db).preflight(
                        actor="mova-worker",
                        reason="preflight automático posterior al DecisionEnvelope",
                        idempotency_key=f"execution-preflight:{decision['envelope_id']}",
                        now=now,
                    ),
                )
        elif self.config.enable_shadow_decision:
            self.db.open_incident(
                "P2", "Shadow decision omitida por memoria", correlation_id=correlation_id,
                cycle_id=cycle_id, job_id=job_id, detail=resource_state,
            )

        health_status = "degraded" if degraded else "ok"
        self.db.record_health(
            "mova-worker", health_status,
            memory_available_bytes=resource_state["memory_available_bytes"],
            disk_free_bytes=resource_state["disk_free_bytes"], load_1m=resource_state["load_1m"],
            detail={"gw": gw, "phase": phase, "decision": decision,
                    "execution_preflight": execution_preflight},
        )
        return {
            "status": "degraded" if degraded else "completed",
            "season": self.config.season, "gw": gw, "deadline_at": deadline,
            "phase": phase, "snapshot": snapshot["path"], "decision": decision,
            "execution_preflight": execution_preflight,
            **resource_state,
        }

    def _shadow_decision(self, harness: Harness, job_id: str, cycle_id: str, gw: int,
                         deadline: str, now: datetime, snapshot_dir: Path,
                         correlation_id: str, prepared_manifest: dict) -> dict:
        decisions = self.config.artifact_root / "decisions" / self.config.season
        decisions.mkdir(parents=True, exist_ok=True)
        stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = decisions / f"gw{gw:02d}_{stamp}_shadow.md"
        bundle_path = decisions / f"gw{gw:02d}_{stamp}_candidates.json"
        envelope_path = decisions / f"gw{gw:02d}_{stamp}_envelope.json"
        log_path = decisions / f"gw{gw:02d}_{stamp}_shadow.log"
        env = dict(os.environ)
        env.update({
            "MOVA_CANONICAL_DB": str(self.config.canonical_db),
            "MOVA_TRACE_DB": str(self.config.trace_db),
            "MOVA_MODEL_ROOT": str(self.config.artifact_root / "models"),
            "MOVA_GIT_SHA": self.config.git_sha,
        })
        from mova_fpl.ops.model_release import resolve_active_model_bundle

        active_bundle = resolve_active_model_bundle(self.config, self.db)
        points_version = active_bundle["models"]["points"]["version"]
        minutes_version = active_bundle["models"]["minutes"]["version"]
        argv = [
            sys.executable, "-m", "mova_fpl.cli.live", "--season", self.config.season,
            "--gw", str(gw), "--policy", "milp", "--horizon", "3", "--top-k", "0",
            "--version", points_version, "--minutes-version", minutes_version,
            "--snapshot-dir", str(snapshot_dir), "--team-id", str(self.config.team_id),
            "--chips", "--lookahead", "6", "--dry-run", "--out", str(out),
            "--json-out", str(bundle_path), "--as-of", prepared_manifest["manifest"]["as_of_at"],
        ]
        if self.config.enable_long_horizon_shadow or self.config.season_value_shadow_manifest:
            strategy_key = "season_value_v2" if self.config.season_value_shadow_manifest else "season_fixture_h3"
            argv.extend(["--strategy-shadow", strategy_key])
            if self.config.season_value_shadow_manifest:
                argv.extend(["--season-value-shadow-manifest", str(self.config.season_value_shadow_manifest)])
                if self.config.season_value_shadow_sha256:
                    argv.extend(["--season-value-shadow-sha256", self.config.season_value_shadow_sha256])
            if self.config.long_horizon_uncertainty_artifact:
                argv.extend([
                    "--strategy-shadow-uncertainty-artifact",
                    str(self.config.long_horizon_uncertainty_artifact),
                ])
                if self.config.long_horizon_uncertainty_sha256:
                    argv.extend([
                        "--strategy-shadow-uncertainty-sha256",
                        self.config.long_horizon_uncertainty_sha256,
                    ])
            if gw > 1:
                prior_envelope = self.db.latest_decision_envelope(
                    f"{self.config.season}-gw{gw - 1:02d}"
                )
                if prior_envelope:
                    argv.extend([
                        "--strategy-shadow-state", str(prior_envelope["artifact_path"]),
                        "--strategy-shadow-state-sha256",
                        str(prior_envelope["artifact_sha256"]),
                    ])
        private_state = self.db.latest_team_state(cycle_id)
        private_state_used = None
        if private_state and private_state.get("artifact_path"):
            observed = datetime.fromisoformat(
                str(private_state["observed_at"]).replace("Z", "+00:00")
            )
            age = max(0, int((now - observed).total_seconds()))
            phase_max_age = private_state_cadence_seconds(deadline, now)
            max_age = min(self.config.private_state_max_age_seconds, phase_max_age)
            if (age <= max_age
                    and private_state.get("quality_status") == "valid"):
                argv.extend(["--private-team-state", str(private_state["artifact_path"])])
                private_state_used = {
                    "team_state_id": private_state["team_state_id"],
                    "fingerprint": private_state["fingerprint"],
                    "age_seconds": age,
                    "max_age_seconds": max_age,
                }
        result = harness.command(
            "shadow_decision", argv, timeout=self.config.decision_timeout_seconds,
            env=env, cwd=ROOT,
        )
        log_path.write_text(
            result.stdout + "\n--- stderr ---\n" + result.stderr, encoding="utf-8",
        )
        if result.returncode != 0:
            self.db.open_incident(
                "P2", "Shadow decision falló", correlation_id=correlation_id,
                cycle_id=cycle_id, job_id=job_id,
                detail={"returncode": result.returncode, "log_path": str(log_path)},
            )
            return {"status": "failed", "log_path": str(log_path)}
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        controls = {
            key: value["value"] for key, value in self.db.controls().items()
        }
        manifest = {
            **prepared_manifest["manifest"],
            "revision": prepared_manifest["revision"],
        }
        envelope = build_envelope(
            bundle=bundle,
            manifest=manifest,
            manifest_id=prepared_manifest["manifest_id"],
            manifest_sha256=prepared_manifest["content_sha256"],
            controls=controls,
        )
        envelope_path.write_text(
            json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        artifact_sha = _sha_file(envelope_path)
        recorded = self.db.record_decision_envelope(
            job_id=job_id, envelope=envelope, artifact_path=str(envelope_path),
            artifact_sha256=artifact_sha,
        )
        selected = next(
            row["decision"] for row in envelope["candidates"]
            if row["candidate_key"] == envelope["selected_candidate_key"]
        )
        return {
            "status": "completed",
            "lifecycle_status": envelope["status"],
            "decision_id": recorded["decision_id"],
            "envelope_id": recorded["envelope_id"],
            "artifact": str(envelope_path),
            "artifact_sha256": artifact_sha,
            "report_artifact": str(out),
            "candidate_artifact": str(bundle_path),
            "manifest_id": prepared_manifest["manifest_id"],
            "manifest_sha256": prepared_manifest["content_sha256"],
            "blocking_codes": envelope["validation"]["blocking_codes"],
            "model_bundle": {"release_id": active_bundle.get("release_id"),
                             "source": active_bundle["source"],
                             "points": points_version, "minutes": minutes_version},
            "private_team_state": private_state_used,
            "expected_points": selected["expected_points"],
            "fingerprint": selected["fingerprint"],
            "chip": selected["chip"],
            "strategy_shadow": (
                {
                    "strategy_key": bundle["strategy_shadow"]["strategy_key"],
                    "status": bundle["strategy_shadow"]["status"],
                    "trajectory": bundle["strategy_shadow"].get("trajectory"),
                    "error": bundle["strategy_shadow"].get("error"),
                    **(bundle["strategy_shadow"].get("comparison") or {}),
                }
                if bundle.get("strategy_shadow") else None
            ),
        }
