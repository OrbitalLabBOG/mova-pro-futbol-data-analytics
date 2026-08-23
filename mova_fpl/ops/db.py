"""Repositorio SQLite del control plane.

Solo este módulo conoce el DDL operativo. Las transacciones son cortas y nunca
envuelven red, modelos o browser.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from mova_fpl.ops.schema import MIGRATIONS


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_json(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(p) for p in value.split(".") if p.isdigit())


class SQLiteVersionError(RuntimeError):
    pass


class OpsDB:
    def __init__(self, path: str | Path, *, minimum_version: str = "3.51.3",
                 enforce_version: bool = True):
        self.path = Path(path)
        self.minimum_version = minimum_version
        self.enforce_version = enforce_version

    @property
    def sqlite_version(self) -> str:
        return sqlite3.sqlite_version

    def assert_runtime(self) -> None:
        if self.enforce_version and _version_tuple(self.sqlite_version) < _version_tuple(
            self.minimum_version
        ):
            raise SQLiteVersionError(
                f"SQLite {self.sqlite_version} no cumple mínimo {self.minimum_version}; "
                "ops.db no se abre con el binario del host"
            )

    def connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        self.assert_runtime()
        if readonly:
            con = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=5,
                                  isolation_level=None)
            con.execute("PRAGMA query_only=ON")
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            con = sqlite3.connect(self.path, timeout=5, isolation_level=None)
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=FULL")
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=5000")
        return con

    @contextmanager
    def transaction(self):
        con = self.connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.execute("COMMIT")
        except Exception:
            if con.in_transaction:
                con.execute("ROLLBACK")
            raise
        finally:
            con.close()

    def migrate(self) -> list[int]:
        applied: list[int] = []
        with self.transaction() as con:
            con.execute(MIGRATIONS[0][2][0])
            current = {int(r[0]) for r in con.execute("SELECT version FROM schema_migrations")}
            for version, name, statements in MIGRATIONS:
                checksum = hashlib.sha256("\n".join(statements).encode("utf-8")).hexdigest()
                if version in current:
                    row = con.execute(
                        "SELECT checksum FROM schema_migrations WHERE version=?", (version,)
                    ).fetchone()
                    if not row or row[0] != checksum:
                        raise RuntimeError(f"drift de migration {version}: checksum distinto")
                    continue
                for statement in statements:
                    con.execute(statement)
                con.execute(
                    "INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES(?,?,?,?)",
                    (version, name, checksum, utcnow()),
                )
                applied.append(version)
        return applied

    def quick_check(self) -> str:
        with self.connect(readonly=True) as con:
            result = con.execute("PRAGMA quick_check").fetchone()[0]
            fk = con.execute("PRAGMA foreign_key_check").fetchall()
        if result != "ok" or fk:
            raise RuntimeError(f"ops.db integrity failure: quick_check={result}, fk={len(fk)}")
        return "ok"

    def checkpoint(self) -> tuple[int, int, int]:
        """Checkpoint explícito; debe llamarse bajo el flock único del worker."""
        with self.connect() as con:
            row = con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        result = tuple(int(value) for value in row)
        if result[0] != 0:
            raise RuntimeError(f"WAL checkpoint ocupado: {result}")
        return result

    def append_audit(self, event_type: str, *, actor: str = "mova-ops",
                     severity: str = "info", correlation_id: str | None = None,
                     cycle_id: str | None = None, job_id: str | None = None,
                     subject_type: str | None = None, subject_id: str | None = None,
                     payload: dict | None = None, con: sqlite3.Connection | None = None) -> str:
        event_id = new_id("audit")
        body = payload or {}
        params = (event_id, utcnow(), severity, event_type, actor, correlation_id, cycle_id,
                  job_id, subject_type, subject_id, canonical_json(body), sha256_json(body))
        sql = """
            INSERT INTO audit_events(event_id,occurred_at,severity,event_type,actor,
              correlation_id,cycle_id,job_id,subject_type,subject_id,payload_json,payload_sha256)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """
        if con is not None:
            con.execute(sql, params)
        else:
            with self.transaction() as tx:
                tx.execute(sql, params)
        return event_id

    def set_control(self, key: str, value, *, actor: str, reason: str) -> int:
        now = utcnow()
        with self.transaction() as con:
            cur = con.execute(
                "INSERT INTO runtime_controls(control_key,value_json,effective_at,actor,reason) "
                "VALUES(?,?,?,?,?)",
                (key, canonical_json(value), now, actor, reason),
            )
            control_id = int(cur.lastrowid)
            self.append_audit(
                "runtime_control_changed", actor=actor, severity="warning",
                subject_type="runtime_control", subject_id=key,
                payload={"control_id": control_id, "value": value, "reason": reason}, con=con,
            )
        return control_id

    def controls(self) -> dict:
        sql = """
            SELECT control_key,value_json,effective_at,actor,reason
            FROM runtime_controls r
            WHERE control_id=(SELECT control_id FROM runtime_controls x
                WHERE x.control_key=r.control_key
                ORDER BY effective_at DESC,control_id DESC LIMIT 1)
            ORDER BY control_key
        """
        with self.connect(readonly=True) as con:
            rows = con.execute(sql).fetchall()
        return {
            r["control_key"]: {
                "value": json.loads(r["value_json"]), "effective_at": r["effective_at"],
                "actor": r["actor"], "reason": r["reason"],
            }
            for r in rows
        }

    def ensure_defaults(self, *, mode: str, action_level: str, compliance_gate: str,
                        browser_writes: bool, actor: str = "deploy") -> None:
        existing = self.controls()
        defaults = {
            "mode": mode,
            "action_level": action_level,
            "compliance_gate": compliance_gate,
            "kill_switch": True,
            "browser_writes": bool(browser_writes),
        }
        for key, value in defaults.items():
            if key not in existing:
                self.set_control(key, value, actor=actor, reason="bootstrap seguro del runtime")

    def upsert_cycle(self, season: str, gw: int, deadline_at: str, *, phase: str,
                     status: str = "active") -> str:
        cycle_id = f"{season}-gw{gw:02d}"
        now = utcnow()
        with self.transaction() as con:
            con.execute(
                """
                INSERT INTO gameweek_cycles(cycle_id,season,gw,deadline_at,phase,status,
                  first_observed_at,last_observed_at)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(season,gw) DO UPDATE SET
                  deadline_at=excluded.deadline_at,phase=excluded.phase,status=excluded.status,
                  last_observed_at=excluded.last_observed_at
                """,
                (cycle_id, season, gw, deadline_at, phase, status, now, now),
            )
        return cycle_id

    def get_job_by_key(self, idempotency_key: str):
        with self.connect(readonly=True) as con:
            row = con.execute(
                "SELECT * FROM job_runs WHERE idempotency_key=?", (idempotency_key,)
            ).fetchone()
        return dict(row) if row else None

    def start_job(self, job_type: str, idempotency_key: str, correlation_id: str,
                  *, cycle_id: str | None = None, input_sha256: str | None = None) -> tuple[str, bool]:
        existing = self.get_job_by_key(idempotency_key)
        if existing:
            return str(existing["job_id"]), True
        job_id = new_id("job")
        with self.transaction() as con:
            con.execute(
                """
                INSERT INTO job_runs(job_id,idempotency_key,correlation_id,cycle_id,job_type,
                  status,started_at,input_sha256)
                VALUES(?,?,?,?,?,'running',?,?)
                """,
                (job_id, idempotency_key, correlation_id, cycle_id, job_type, utcnow(), input_sha256),
            )
            self.append_audit(
                "job_started", correlation_id=correlation_id, cycle_id=cycle_id, job_id=job_id,
                subject_type="job", subject_id=job_id,
                payload={"job_type": job_type, "idempotency_key": idempotency_key}, con=con,
            )
        return job_id, False

    def finish_job(self, job_id: str, status: str, *, output_sha256: str | None = None,
                   metrics: dict | None = None, error_code: str | None = None,
                   error_detail: str | None = None) -> None:
        with self.transaction() as con:
            row = con.execute(
                "SELECT correlation_id,cycle_id,job_type FROM job_runs WHERE job_id=?", (job_id,)
            ).fetchone()
            if not row:
                raise KeyError(job_id)
            con.execute(
                """
                UPDATE job_runs SET status=?,finished_at=?,output_sha256=?,metrics_json=?,
                  error_code=?,error_detail=? WHERE job_id=?
                """,
                (status, utcnow(), output_sha256, canonical_json(metrics or {}), error_code,
                 error_detail, job_id),
            )
            self.append_audit(
                f"job_{status}", severity="error" if status == "failed" else "info",
                correlation_id=row["correlation_id"], cycle_id=row["cycle_id"], job_id=job_id,
                subject_type="job", subject_id=job_id,
                payload={"job_type": row["job_type"], "status": status,
                         "error_code": error_code}, con=con,
            )

    def bind_job_cycle(self, job_id: str, cycle_id: str) -> None:
        with self.transaction() as con:
            changed = con.execute(
                "UPDATE job_runs SET cycle_id=? WHERE job_id=?", (cycle_id, job_id)
            ).rowcount
            if changed != 1:
                raise KeyError(job_id)

    def start_step(self, job_id: str, name: str) -> tuple[str, float]:
        import time
        step_id = new_id("step")
        with self.transaction() as con:
            con.execute(
                "INSERT INTO job_steps(step_id,job_id,step_name,status,started_at) "
                "VALUES(?,?,?,'running',?)", (step_id, job_id, name, utcnow()),
            )
        return step_id, time.monotonic()

    def finish_step(self, step_id: str, started_monotonic: float, status: str, *,
                    detail: dict | None = None, output_sha256: str | None = None,
                    error_code: str | None = None, error_detail: str | None = None) -> None:
        import time
        duration = int((time.monotonic() - started_monotonic) * 1000)
        with self.transaction() as con:
            con.execute(
                """
                UPDATE job_steps SET status=?,finished_at=?,duration_ms=?,output_sha256=?,
                  detail_json=?,error_code=?,error_detail=? WHERE step_id=?
                """,
                (status, utcnow(), duration, output_sha256, canonical_json(detail or {}),
                 error_code, error_detail, step_id),
            )

    def add_snapshot(self, *, job_id: str, cycle_id: str, source_name: str,
                     captured_at: str, artifact_path: str, manifest_sha256: str,
                     payload_sha256: str, freshness_seconds: int, quality_status: str,
                     quality: dict) -> str:
        snapshot_id = new_id("snapshot")
        with self.transaction() as con:
            con.execute(
                """
                INSERT OR IGNORE INTO source_snapshots(snapshot_id,job_id,cycle_id,source_name,
                  captured_at,artifact_path,manifest_sha256,payload_sha256,freshness_seconds,
                  quality_status,quality_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (snapshot_id, job_id, cycle_id, source_name, captured_at, artifact_path,
                 manifest_sha256, payload_sha256, freshness_seconds, quality_status,
                 canonical_json(quality)),
            )
        return snapshot_id

    def add_team_state(self, *, job_id: str, cycle_id: str, observed_at: str,
                       source_name: str, squad: list, free_transfers: int,
                       bank_tenths: int, chips: list, fingerprint: str,
                       artifact_path: str, manifest_sha256: str,
                       quality_status: str = "valid") -> str:
        team_state_id = new_id("teamstate")
        with self.transaction() as con:
            con.execute(
                """
                INSERT OR IGNORE INTO team_state_snapshots(team_state_id,job_id,cycle_id,
                  observed_at,source_name,squad_json,free_transfers,bank_tenths,chips_json,
                  fingerprint,artifact_path,manifest_sha256,quality_status)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (team_state_id, job_id, cycle_id, observed_at, source_name,
                 canonical_json(squad), int(free_transfers), int(bank_tenths),
                 canonical_json(chips), fingerprint, artifact_path, manifest_sha256,
                 quality_status),
            )
            self.append_audit(
                "team_state_captured", correlation_id=None, cycle_id=cycle_id, job_id=job_id,
                subject_type="team_state", subject_id=team_state_id,
                payload={"source_name": source_name, "fingerprint": fingerprint,
                         "free_transfers": free_transfers,
                         "quality_status": quality_status}, con=con,
            )
        return team_state_id

    def record_decision(self, *, job_id: str, cycle_id: str, mode: str, status: str,
                        policy_version: str, expected_points: float | None,
                        chip: str | None, fingerprint: str | None,
                        manifest_sha256: str | None, artifact_path: str | None) -> str:
        decision_id = new_id("decision")
        with self.transaction() as con:
            revision = int(con.execute(
                "SELECT COALESCE(MAX(revision),0)+1 FROM decision_runs WHERE cycle_id=?",
                (cycle_id,),
            ).fetchone()[0])
            con.execute(
                """
                INSERT INTO decision_runs(decision_id,job_id,cycle_id,revision,mode,
                  policy_version,status,expected_points,chip,fingerprint,manifest_sha256,
                  artifact_path,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (decision_id, job_id, cycle_id, revision, mode, policy_version, status,
                 expected_points, chip, fingerprint, manifest_sha256, artifact_path, utcnow()),
            )
        return decision_id

    def record_health(self, service: str, status: str, *, memory_available_bytes: int | None,
                      disk_free_bytes: int | None, load_1m: float | None,
                      detail: dict | None = None) -> str:
        sample_id = new_id("health")
        with self.transaction() as con:
            con.execute(
                """
                INSERT INTO health_samples(sample_id,observed_at,service,status,
                  memory_available_bytes,disk_free_bytes,load_1m,sqlite_version,detail_json)
                VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (sample_id, utcnow(), service, status, memory_available_bytes, disk_free_bytes,
                 load_1m, self.sqlite_version, canonical_json(detail or {})),
            )
        return sample_id

    def open_incident(self, severity: str, title: str, *, correlation_id: str | None = None,
                      cycle_id: str | None = None, job_id: str | None = None,
                      detail: dict | None = None) -> str:
        incident_id = new_id("incident")
        payload = detail or {}
        with self.transaction() as con:
            con.execute(
                """
                INSERT INTO incidents(incident_id,opened_at,severity,status,title,correlation_id,
                  cycle_id,job_id,detail_json) VALUES(?,? ,?,'open',?,?,?,?,?)
                """,
                (incident_id, utcnow(), severity, title, correlation_id, cycle_id, job_id,
                 canonical_json(payload)),
            )
            event_key = f"incident:{incident_id}"
            con.execute(
                """
                INSERT INTO outbox_events(outbox_id,event_key,created_at,available_at,event_type,
                  severity,status,payload_json) VALUES(?,?,?,?,?,?,'pending',?)
                """,
                (new_id("outbox"), event_key, utcnow(), utcnow(), "incident_opened", severity,
                 canonical_json({"incident_id": incident_id, "title": title, **payload})),
            )
        return incident_id

    def status(self) -> dict:
        with self.connect(readonly=True) as con:
            cycle = con.execute(
                "SELECT * FROM gameweek_cycles ORDER BY deadline_at DESC LIMIT 1"
            ).fetchone()
            tick = con.execute(
                "SELECT * FROM job_runs WHERE job_type='tick' ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            team_state = con.execute(
                "SELECT team_state_id,cycle_id,observed_at,source_name,free_transfers,"
                "bank_tenths,fingerprint,quality_status FROM team_state_snapshots "
                "ORDER BY observed_at DESC LIMIT 1"
            ).fetchone()
            incidents = con.execute(
                "SELECT severity,COUNT(*) AS n FROM incidents WHERE status!='resolved' GROUP BY severity"
            ).fetchall()
            pending = con.execute(
                "SELECT COUNT(*) FROM outbox_events WHERE status IN ('pending','sending')"
            ).fetchone()[0]
        return {
            "sqlite_version": self.sqlite_version,
            "cycle": dict(cycle) if cycle else None,
            "latest_tick": dict(tick) if tick else None,
            "latest_team_state": dict(team_state) if team_state else None,
            "open_incidents": {r["severity"]: r["n"] for r in incidents},
            "outbox_pending": int(pending),
            "controls": self.controls(),
        }

    def latest_snapshot(self, cycle_id: str) -> dict | None:
        with self.connect(readonly=True) as con:
            row = con.execute(
                "SELECT * FROM source_snapshots WHERE cycle_id=? "
                "ORDER BY captured_at DESC LIMIT 1", (cycle_id,),
            ).fetchone()
        return dict(row) if row else None

    def latest_team_state(self, cycle_id: str) -> dict | None:
        with self.connect(readonly=True) as con:
            row = con.execute(
                "SELECT * FROM team_state_snapshots WHERE cycle_id=? "
                "ORDER BY observed_at DESC LIMIT 1", (cycle_id,),
            ).fetchone()
        return dict(row) if row else None

    def latest_team_state_for_event(self, season: str, gw: int) -> dict | None:
        with self.connect(readonly=True) as con:
            row = con.execute(
                "SELECT t.* FROM team_state_snapshots t "
                "JOIN gameweek_cycles c ON c.cycle_id=t.cycle_id "
                "WHERE c.season=? AND c.gw=? "
                "ORDER BY t.observed_at DESC LIMIT 1",
                (season, int(gw)),
            ).fetchone()
        return dict(row) if row else None

    def recent(self, table: str, limit: int = 50) -> list[dict]:
        allowed = {"job_runs", "job_steps", "audit_events", "incidents", "health_samples",
                   "source_snapshots", "team_state_snapshots", "decision_runs",
                   "outbox_events", "chip_strategy_runs"}
        if table not in allowed:
            raise ValueError(f"tabla no permitida: {table}")
        order = {
            "job_runs": "started_at", "job_steps": "started_at", "audit_events": "occurred_at",
            "incidents": "opened_at", "health_samples": "observed_at",
            "source_snapshots": "captured_at", "decision_runs": "created_at",
            "team_state_snapshots": "observed_at",
            "outbox_events": "created_at", "chip_strategy_runs": "created_at",
        }[table]
        with self.connect(readonly=True) as con:
            rows = con.execute(
                f"SELECT * FROM {table} ORDER BY {order} DESC LIMIT ?", (max(1, min(limit, 500)),)
            ).fetchall()
        return [dict(r) for r in rows]

    def prometheus(self) -> str:
        status = self.status()
        tick = status["latest_tick"] or {}
        success = 1 if tick.get("status") in {"completed", "degraded"} else 0
        cycle = status["cycle"] or {}
        incidents = status["open_incidents"]
        last_tick_epoch = 0.0
        team_state = status["latest_team_state"] or {}
        team_state_epoch = 0.0
        if tick.get("finished_at"):
            try:
                last_tick_epoch = datetime.fromisoformat(tick["finished_at"]).timestamp()
            except ValueError:
                pass
        if team_state.get("observed_at"):
            try:
                team_state_epoch = datetime.fromisoformat(
                    str(team_state["observed_at"]).replace("Z", "+00:00")
                ).timestamp()
            except ValueError:
                pass
        tick_duration_seconds = 0.0
        if tick.get("started_at") and tick.get("finished_at"):
            try:
                tick_duration_seconds = max(0.0, (
                    datetime.fromisoformat(tick["finished_at"])
                    - datetime.fromisoformat(tick["started_at"])
                ).total_seconds())
            except ValueError:
                pass
        step_rows = []
        with self.connect(readonly=True) as con:
            collector_job = con.execute(
                "SELECT job_id FROM job_steps "
                "WHERE step_name IN ('fetch_fpl_bootstrap_events','fetch_official_sources') "
                "AND status='completed' ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            if collector_job:
                step_rows = con.execute(
                    "SELECT step_name,status,duration_ms FROM job_steps "
                    "WHERE job_id=? ORDER BY started_at", (collector_job["job_id"],)
                ).fetchall()
        lines = [
            "# HELP mova_up Whether ops.db is readable.",
            "# TYPE mova_up gauge",
            "mova_up 1",
            "# HELP mova_tick_last_success Whether the latest tick completed or degraded.",
            "# TYPE mova_tick_last_success gauge",
            f"mova_tick_last_success {success}",
            "# HELP mova_tick_last_finished_timestamp_seconds Unix time of latest finished tick.",
            "# TYPE mova_tick_last_finished_timestamp_seconds gauge",
            f"mova_tick_last_finished_timestamp_seconds {last_tick_epoch:.3f}",
            "# HELP mova_tick_last_duration_seconds Wall time of the latest tick.",
            "# TYPE mova_tick_last_duration_seconds gauge",
            f"mova_tick_last_duration_seconds {tick_duration_seconds:.3f}",
            "# HELP mova_collector_step_duration_ms Duration of each audited step in the latest collector run.",
            "# TYPE mova_collector_step_duration_ms gauge",
            "# HELP mova_current_gameweek Current tracked gameweek.",
            "# TYPE mova_current_gameweek gauge",
            f"mova_current_gameweek {int(cycle.get('gw') or 0)}",
            "# HELP mova_team_state_last_observed_timestamp_seconds Unix time of latest private team state.",
            "# TYPE mova_team_state_last_observed_timestamp_seconds gauge",
            f"mova_team_state_last_observed_timestamp_seconds {team_state_epoch:.3f}",
            "# HELP mova_team_state_free_transfers Latest exact free-transfer balance.",
            "# TYPE mova_team_state_free_transfers gauge",
            f"mova_team_state_free_transfers {int(team_state.get('free_transfers') or 0)}",
            "# HELP mova_open_incidents Open incidents by severity.",
            "# TYPE mova_open_incidents gauge",
        ]
        for row in step_rows:
            step = str(row["step_name"]).replace("\\", "\\\\").replace('"', '\\"')
            step_status = str(row["status"]).replace("\\", "\\\\").replace('"', '\\"')
            duration_ms = int(row["duration_ms"] or 0)
            lines.append(
                f'mova_collector_step_duration_ms{{step="{step}",status="{step_status}"}} '
                f'{duration_ms}'
            )
        for severity in ("P0", "P1", "P2", "P3"):
            lines.append(f'mova_open_incidents{{severity="{severity}"}} {int(incidents.get(severity, 0))}')
        lines += [
            "# HELP mova_outbox_pending Pending alert events.",
            "# TYPE mova_outbox_pending gauge",
            f"mova_outbox_pending {status['outbox_pending']}",
            "",
        ]
        return "\n".join(lines)
