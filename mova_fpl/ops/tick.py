"""Tick idempotente del operador autónomo, seguro por defecto."""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import re
import shutil
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from mova_fpl.data.snapshot import capture_bytes
from mova_fpl.data.sources import fetch_bootstrap, fetch_fixtures
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB, canonical_json, new_id, sha256_json, utcnow
from mova_fpl.ops.harness import Harness

LOG = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]

CADENCE_SECONDS = {
    "baseline": 6 * 3600,
    "research": 3 * 3600,
    "refresh": 3600,
    "preflight": 15 * 60,
    "freeze": 5 * 60,
    "execution_window": 5 * 60,
    "verification_window": 5 * 60,
    "hard_stop": 5 * 60,
    "settlement": 6 * 3600,
}


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


def select_event(boot: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    events = list(boot.get("events") or ())
    explicit = next((e for e in events if e.get("is_next")), None)
    if explicit:
        return explicit
    future = []
    for event in events:
        deadline = event.get("deadline_time")
        if not deadline:
            continue
        parsed = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
        if parsed > now:
            future.append((parsed, event))
    if future:
        return min(future, key=lambda item: item[0])[1]
    current = next((e for e in events if e.get("is_current")), None)
    if current:
        return current
    raise ValueError("bootstrap sin jornada current/next ni deadline futuro")


def phase_for(deadline: str, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    target = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
    hours = (target - now).total_seconds() / 3600
    if hours > 48:
        return "baseline"
    if hours > 24:
        return "research"
    if hours > 6:
        return "refresh"
    if hours > 1.5:
        return "preflight"
    if hours > 1:
        return "freeze"
    if hours > 0.5:
        return "execution_window"
    if hours > 0.25:
        return "verification_window"
    if hours > 0:
        return "hard_stop"
    return "settlement"


def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_decision(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    xp = re.search(r"xP del once \(con capitán\) \| ([0-9.]+)", text)
    fingerprint = re.search(r"Huella de la decisión: `([0-9a-f]+)`", text)
    chip = re.search(r"Se juega el ([A-Z ]+) en esta jornada", text)
    return {
        "expected_points": float(xp.group(1)) if xp else None,
        "fingerprint": fingerprint.group(1) if fingerprint else None,
        "chip": chip.group(1).strip().lower().replace(" ", "_") if chip else None,
    }


class TickRunner:
    def __init__(self, config: RuntimeConfig, db: OpsDB):
        self.config = config
        self.db = db

    def run(self, *, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        self.config.validate()
        self.db.migrate()
        self.db.ensure_defaults(
            mode=self.config.mode, action_level=self.config.action_level,
            compliance_gate=self.config.compliance_gate,
            browser_writes=self.config.enable_browser_writes,
        )
        bucket = int(now.timestamp()) // self.config.tick_bucket_seconds
        correlation_id = new_id("corr")
        idempotency_key = f"tick:{bucket}"

        with exclusive_lock(self.config.lock_path):
            job_id, reused = self.db.start_job("tick", idempotency_key, correlation_id)
            if reused:
                existing = self.db.get_job_by_key(idempotency_key)
                return {"status": "reused", "job_id": job_id,
                        "existing_status": existing.get("status") if existing else None}
            harness = Harness(self.db, job_id, correlation_id=correlation_id)
            try:
                result = self._run(job_id, correlation_id, harness, now)
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
            return {"job_id": job_id, "correlation_id": correlation_id, **result}

    def _run(self, job_id: str, correlation_id: str, harness: Harness,
             now: datetime) -> dict:
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
                    cadence = CADENCE_SECONDS[phase]
                    if age < cadence:
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

        source = harness.call(
            "fetch_official_sources",
            lambda: {"bootstrap": fetch_bootstrap(), "fixtures": fetch_fixtures()},
        )
        boot = json.loads(source["bootstrap"])
        event = select_event(boot, now)
        gw, deadline = int(event["id"]), str(event["deadline_time"])
        phase = phase_for(deadline, now)
        cycle_id = self.db.upsert_cycle(self.config.season, gw, deadline, phase=phase)
        self.db.bind_job_cycle(job_id, cycle_id)
        harness.cycle_id = cycle_id

        def save_snapshot():
            out_root = self.config.artifact_root / "sources" / "fpl_live"
            dest, manifest = capture_bytes(
                self.config.season, gw, out_root, source["bootstrap"], source["fixtures"],
                captured_at=now.isoformat(timespec="seconds"),
            )
            manifest_path = dest / "manifest.json"
            payload_sha = hashlib.sha256(
                source["bootstrap"] + b"\n" + source["fixtures"]
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
        degraded = not memory_ok
        if self.config.enable_shadow_decision and memory_ok:
            decision = self._shadow_decision(
                harness, job_id, cycle_id, gw, Path(snapshot["path"]), correlation_id,
            )
            degraded = degraded or decision.get("status") != "completed"
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
            detail={"gw": gw, "phase": phase, "decision": decision},
        )
        return {
            "status": "degraded" if degraded else "completed",
            "season": self.config.season, "gw": gw, "deadline_at": deadline,
            "phase": phase, "snapshot": snapshot["path"], "decision": decision,
            **resource_state,
        }

    def _shadow_decision(self, harness: Harness, job_id: str, cycle_id: str, gw: int,
                         snapshot_dir: Path, correlation_id: str) -> dict:
        decisions = self.config.artifact_root / "decisions" / self.config.season
        decisions.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = decisions / f"gw{gw:02d}_{stamp}_shadow.md"
        log_path = decisions / f"gw{gw:02d}_{stamp}_shadow.log"
        env = dict(os.environ)
        env.update({
            "MOVA_CANONICAL_DB": str(self.config.canonical_db),
            "MOVA_TRACE_DB": str(self.config.trace_db),
            "MOVA_MODEL_ROOT": str(self.config.artifact_root / "models"),
            "MOVA_GIT_SHA": self.config.git_sha,
        })
        argv = [
            sys.executable, "-m", "mova_fpl.cli.live", "--season", self.config.season,
            "--gw", str(gw), "--policy", "milp", "--horizon", "3", "--top-k", "0",
            "--version", "1.1.0", "--minutes-version", "1.1.0",
            "--snapshot-dir", str(snapshot_dir), "--team-id", str(self.config.team_id),
            "--chips", "--lookahead", "6", "--dry-run", "--out", str(out),
        ]
        private_state = self.db.latest_team_state(cycle_id)
        private_state_used = None
        if private_state and private_state.get("artifact_path"):
            observed = datetime.fromisoformat(
                str(private_state["observed_at"]).replace("Z", "+00:00")
            )
            age = max(0, int((datetime.now(timezone.utc) - observed).total_seconds()))
            if (age <= self.config.private_state_max_age_seconds
                    and private_state.get("quality_status") == "valid"):
                argv.extend(["--private-team-state", str(private_state["artifact_path"])])
                private_state_used = {
                    "team_state_id": private_state["team_state_id"],
                    "fingerprint": private_state["fingerprint"],
                    "age_seconds": age,
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
        parsed = _parse_decision(out)
        artifact_sha = _sha_file(out)
        decision_id = self.db.record_decision(
            job_id=job_id, cycle_id=cycle_id, mode="shadow", status="staged",
            policy_version="milp-points-1.1.0", expected_points=parsed["expected_points"],
            chip=parsed["chip"], fingerprint=parsed["fingerprint"],
            manifest_sha256=artifact_sha, artifact_path=str(out),
        )
        return {"status": "completed", "decision_id": decision_id, "artifact": str(out),
                "artifact_sha256": artifact_sha, "private_team_state": private_state_used,
                **parsed}
