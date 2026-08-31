"""Repositorio SQLite del control plane.

Solo este módulo conoce el DDL operativo. Las transacciones son cortas y nunca
envuelven red, modelos o browser.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
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

    def record_decision_envelope(self, *, job_id: str, envelope: dict,
                                 artifact_path: str, artifact_sha256: str) -> dict:
        """Persiste el paquete máquina completo en una sola transacción idempotente."""
        from mova_fpl.ops.decision_envelope import decision_fingerprint

        content_sha = str(envelope["content_sha256"])
        cycle_id = str(envelope["cycle_id"])
        envelope_id = str(envelope["envelope_id"])
        selected_key = str(envelope["selected_candidate_key"])
        candidates = {str(row["candidate_key"]): row for row in envelope["candidates"]}
        selected = candidates[selected_key]["decision"]
        decision_id = f"decision_{content_sha[:24]}"
        created_at = utcnow()
        with self.transaction() as con:
            existing = con.execute(
                "SELECT envelope_id,decision_id,status,artifact_path FROM decision_envelopes "
                "WHERE content_sha256=?", (content_sha,),
            ).fetchone()
            if existing:
                return {**dict(existing), "reused": True, "content_sha256": content_sha}

            revision = int(con.execute(
                "SELECT COALESCE(MAX(revision),0)+1 FROM decision_runs WHERE cycle_id=?",
                (cycle_id,),
            ).fetchone()[0])
            superseded = con.execute(
                "UPDATE decision_runs SET status='superseded' "
                "WHERE cycle_id=? AND status IN ('staged','blocked')", (cycle_id,),
            ).rowcount
            con.execute(
                "UPDATE decision_envelopes SET status='superseded' "
                "WHERE cycle_id=? AND status IN ('staged','blocked')", (cycle_id,),
            )
            con.execute(
                """INSERT INTO decision_runs(
                decision_id,job_id,cycle_id,revision,mode,policy_version,status,
                expected_points,chip,fingerprint,manifest_sha256,artifact_path,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    decision_id, job_id, cycle_id, revision, envelope["mode"],
                    envelope["policy_version"], envelope["status"],
                    float(selected["expected_points"]), selected.get("chip"),
                    decision_fingerprint(selected),
                    envelope["manifest"]["content_sha256"], artifact_path, created_at,
                ),
            )
            ordered = list(selected["starters"]) + list(selected["bench_order"])
            for position, element in enumerate(ordered, start=1):
                con.execute(
                    """INSERT INTO decision_players(
                    decision_id,element,squad_position,role,is_captain,is_vice_captain,
                    transfer_direction,expected_points) VALUES(?,?,?,?,?,?,?,NULL)""",
                    (
                        decision_id, element, position,
                        "starter" if position <= 11 else "bench",
                        int(element == selected.get("captain")),
                        int(element == selected.get("vice_captain")),
                        "in" if element in (selected.get("transfers_in") or ()) else None,
                    ),
                )
            con.execute(
                """INSERT INTO decision_envelopes(
                envelope_id,job_id,cycle_id,decision_id,manifest_id,schema_version,
                policy_version,status,selected_candidate_key,content_sha256,artifact_path,
                artifact_sha256,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    envelope_id, job_id, cycle_id, decision_id,
                    envelope["manifest"]["manifest_id"], envelope["schema"],
                    envelope["policy_version"], envelope["status"], selected_key,
                    content_sha, artifact_path, artifact_sha256, created_at,
                ),
            )
            for row in envelope["candidates"]:
                candidate = row["decision"]
                con.execute(
                    """INSERT INTO decision_candidates(
                    envelope_id,candidate_key,label,selected,decision_json,fingerprint,
                    expected_points) VALUES(?,?,?,?,?,?,?)""",
                    (
                        envelope_id, row["candidate_key"], row["label"],
                        int(row["candidate_key"] == selected_key),
                        canonical_json(candidate), decision_fingerprint(candidate),
                        float(candidate["expected_points"]),
                    ),
                )
            for row in envelope["validation"]["checks"]:
                check_id = "decisioncheck_" + hashlib.sha256(
                    f"{envelope_id}:{row['code']}".encode("utf-8")
                ).hexdigest()[:24]
                con.execute(
                    """INSERT INTO decision_validation_checks(
                    check_id,envelope_id,code,severity,passed,summary,detail_json,created_at)
                    VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        check_id, envelope_id, row["code"], row["severity"],
                        int(row["passed"]), row["summary"],
                        canonical_json(row.get("detail") or {}), created_at,
                    ),
                )
            self.append_audit(
                "decision_envelope_recorded",
                correlation_id=con.execute(
                    "SELECT correlation_id FROM job_runs WHERE job_id=?", (job_id,)
                ).fetchone()[0],
                cycle_id=cycle_id, job_id=job_id, subject_type="decision_envelope",
                subject_id=envelope_id,
                severity="warning" if envelope["status"] == "blocked" else "info",
                payload={
                    "decision_id": decision_id, "status": envelope["status"],
                    "content_sha256": content_sha,
                    "manifest_sha256": envelope["manifest"]["content_sha256"],
                    "blocking_codes": envelope["validation"]["blocking_codes"],
                    "superseded_decisions": superseded,
                }, con=con,
            )
        return {
            "envelope_id": envelope_id, "decision_id": decision_id,
            "status": envelope["status"], "revision": revision,
            "content_sha256": content_sha, "artifact_path": artifact_path,
            "reused": False, "superseded_decisions": superseded,
        }

    def execution_preflight_source(self) -> dict:
        """Carga únicamente el estado durable necesario para un preflight."""
        with self.connect(readonly=True) as con:
            envelope = con.execute(
                "SELECT * FROM decision_envelopes "
                "WHERE status IN ('staged','blocked') ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if not envelope:
                return {"envelope": None}
            manifest = con.execute(
                "SELECT m.*,c.deadline_at FROM cycle_manifests m "
                "JOIN gameweek_cycles c ON c.cycle_id=m.cycle_id "
                "WHERE m.manifest_id=?", (envelope["manifest_id"],),
            ).fetchone()
            team_state = con.execute(
                "SELECT * FROM team_state_snapshots WHERE cycle_id=? "
                "ORDER BY observed_at DESC LIMIT 1", (envelope["cycle_id"],),
            ).fetchone()
            incidents = con.execute(
                "SELECT incident_id,severity,status,title,opened_at FROM incidents "
                "WHERE status!='resolved' AND severity IN ('P0','P1') "
                "ORDER BY opened_at"
            ).fetchall()
            prior = con.execute(
                """SELECT execution_id,status,finished_at FROM (
                  SELECT a.execution_id,a.status,a.finished_at,a.created_at AS observed_at
                  FROM execution_attempts a
                  JOIN execution_plans p ON p.plan_id=a.plan_id
                  WHERE p.decision_id=?
                  UNION ALL
                  SELECT w.execution_id,w.status,w.finished_at,
                    COALESCE(w.finished_at,w.started_at) AS observed_at
                  FROM web_executions w WHERE w.decision_id=?
                ) ORDER BY observed_at DESC LIMIT 1""",
                (envelope["decision_id"], envelope["decision_id"]),
            ).fetchone()
        if not manifest:
            raise RuntimeError("DecisionEnvelope referencia un manifest inexistente")
        return {
            "envelope": dict(envelope), "manifest": dict(manifest),
            "team_state": dict(team_state) if team_state else None,
            "open_high_incidents": [dict(row) for row in incidents],
            "prior_execution": dict(prior) if prior else None,
        }

    def execution_plan_for_job(self, job_id: str) -> dict | None:
        with self.connect(readonly=True) as con:
            row = con.execute(
                "SELECT * FROM execution_plans WHERE job_id=?", (job_id,)
            ).fetchone()
        return dict(row) if row else None

    def record_execution_plan(self, *, job_id: str, plan: dict,
                              artifact_path: str, artifact_sha256: str) -> dict:
        """Persiste plan y gates atómicamente; nunca habilita el browser."""
        authorization = plan["authorization"]
        action = plan["action"]
        created_at = plan["created_at"]
        with self.transaction() as con:
            existing = con.execute(
                "SELECT * FROM execution_plans WHERE content_sha256=? OR idempotency_key=?",
                (plan["content_sha256"], plan["idempotency_key"]),
            ).fetchone()
            if existing:
                return dict(existing)
            con.execute(
                "UPDATE execution_plans SET status='superseded' "
                "WHERE cycle_id=? AND status IN ('blocked','authorized','noop')",
                (plan["cycle_id"],),
            )
            con.execute(
                """INSERT INTO execution_plans(
                plan_id,job_id,cycle_id,envelope_id,decision_id,policy_version,risk_class,
                required_action_level,status,idempotency_key,content_sha256,artifact_path,
                artifact_sha256,expected_pre_fingerprint,expected_post_fingerprint,
                deadline_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    plan["plan_id"], job_id, plan["cycle_id"],
                    plan["envelope"]["envelope_id"], plan["envelope"]["decision_id"],
                    plan["policy_version"], action["risk_class"],
                    action["required_action_level"], authorization["status"],
                    plan["idempotency_key"], plan["content_sha256"], artifact_path,
                    artifact_sha256, action["expected_pre_team_fingerprint"],
                    action["expected_post_decision_fingerprint"], plan["deadline_at"],
                    created_at,
                ),
            )
            for check in authorization["checks"]:
                check_id = "preflightcheck_" + hashlib.sha256(
                    f"{plan['plan_id']}:{check['code']}".encode("utf-8")
                ).hexdigest()[:24]
                con.execute(
                    """INSERT INTO execution_preflight_checks(
                    check_id,plan_id,code,severity,passed,summary,detail_json,created_at)
                    VALUES(?,?,?,?,?,?,?,?)""",
                    (check_id, plan["plan_id"], check["code"], check["severity"],
                     int(check["passed"]), check["summary"],
                     canonical_json(check.get("detail") or {}), created_at),
                )
            self.append_audit(
                "execution_preflight_recorded", actor=plan["actor"],
                correlation_id=con.execute(
                    "SELECT correlation_id FROM job_runs WHERE job_id=?", (job_id,)
                ).fetchone()[0], cycle_id=plan["cycle_id"], job_id=job_id,
                subject_type="execution_plan", subject_id=plan["plan_id"],
                severity="warning" if authorization["status"] == "blocked" else "info",
                payload={
                    "reason": plan["reason"], "status": authorization["status"],
                    "risk_class": action["risk_class"],
                    "required_action_level": action["required_action_level"],
                    "blocking_codes": authorization["blocking_codes"],
                    "content_sha256": plan["content_sha256"],
                }, con=con,
            )
        return {
            "plan_id": plan["plan_id"], "cycle_id": plan["cycle_id"],
            "envelope_id": plan["envelope"]["envelope_id"],
            "decision_id": plan["envelope"]["decision_id"],
            "status": authorization["status"], "risk_class": action["risk_class"],
            "required_action_level": action["required_action_level"],
            "blocking_codes": authorization["blocking_codes"],
            "content_sha256": plan["content_sha256"], "artifact_path": artifact_path,
        }

    @staticmethod
    def _append_attempt_event(con: sqlite3.Connection, *, execution_id: str,
                              from_status: str | None, to_status: str, actor: str,
                              reason: str, detail: dict, occurred_at: str) -> None:
        sequence = int(con.execute(
            "SELECT COALESCE(MAX(sequence),0)+1 FROM execution_attempt_events "
            "WHERE execution_id=?", (execution_id,),
        ).fetchone()[0])
        detail_sha = sha256_json(detail)
        event_id = "execevent_" + hashlib.sha256(
            f"{execution_id}:{sequence}:{to_status}:{detail_sha}".encode("utf-8")
        ).hexdigest()[:24]
        con.execute(
            """INSERT INTO execution_attempt_events(
            attempt_event_id,execution_id,sequence,from_status,to_status,actor,reason,
            detail_json,detail_sha256,occurred_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (event_id, execution_id, sequence, from_status, to_status, actor, reason,
             canonical_json(detail), detail_sha, occurred_at),
        )

    def execution_claim_source(self, plan_id: str) -> dict:
        """Carga el estado mutable que debe revalidarse justo antes de preparar."""
        with self.connect(readonly=True) as con:
            plan = con.execute(
                "SELECT * FROM execution_plans WHERE plan_id=?", (plan_id,)
            ).fetchone()
            if not plan:
                raise ValueError(f"execution plan inexistente: {plan_id}")
            controls = {
                str(row["control_key"]): json.loads(row["value_json"])
                for row in con.execute(
                    """SELECT control_key,value_json FROM runtime_controls r
                    WHERE control_id=(SELECT control_id FROM runtime_controls x
                      WHERE x.control_key=r.control_key
                      ORDER BY effective_at DESC,control_id DESC LIMIT 1)"""
                )
            }
            incidents = con.execute(
                "SELECT incident_id,severity,title FROM incidents "
                "WHERE status!='resolved' AND severity IN ('P0','P1') ORDER BY opened_at"
            ).fetchall()
            team_state = con.execute(
                "SELECT team_state_id,observed_at,fingerprint,quality_status "
                "FROM team_state_snapshots WHERE cycle_id=? "
                "ORDER BY observed_at DESC LIMIT 1", (plan["cycle_id"],),
            ).fetchone()
            attempt = con.execute(
                "SELECT * FROM execution_attempts WHERE plan_id=?", (plan_id,)
            ).fetchone()
        return {
            "plan": dict(plan), "controls": controls,
            "open_high_incidents": [dict(row) for row in incidents],
            "team_state": dict(team_state) if team_state else None,
            "attempt": dict(attempt) if attempt else None,
        }

    def prepare_execution_attempt(self, *, plan: dict, job_id: str,
                                  execution_id: str, idempotency_key: str,
                                  adapter: str, command_path: str,
                                  command_sha256: str, actor: str, reason: str,
                                  created_at: str) -> dict:
        """Reserva exactamente un intento por plan; no concede aún el lease."""
        with self.transaction() as con:
            existing = con.execute(
                "SELECT * FROM execution_attempts WHERE plan_id=? OR idempotency_key=?",
                (plan["plan_id"], idempotency_key),
            ).fetchone()
            if existing:
                if existing["idempotency_key"] != idempotency_key:
                    raise RuntimeError(
                        f"plan ya reservado por execution attempt {existing['execution_id']}"
                    )
                return {**dict(existing), "reused": True}
            con.execute(
                """INSERT INTO execution_attempts(
                execution_id,plan_id,job_id,idempotency_key,adapter,command_path,
                command_sha256,status,
                expected_pre_fingerprint,expected_post_fingerprint,created_at)
                VALUES(?,?,?,?,?,?,?,'prepared',?,?,?)""",
                (execution_id, plan["plan_id"], job_id, idempotency_key, adapter,
                 command_path, command_sha256,
                 plan["expected_pre_fingerprint"], plan["expected_post_fingerprint"],
                 created_at),
            )
            self._append_attempt_event(
                con, execution_id=execution_id, from_status=None, to_status="prepared",
                actor=actor, reason=reason,
                detail={"adapter": adapter, "plan_id": plan["plan_id"],
                        "command_sha256": command_sha256},
                occurred_at=created_at,
            )
            self.append_audit(
                "execution_attempt_prepared", actor=actor,
                correlation_id=con.execute(
                    "SELECT correlation_id FROM job_runs WHERE job_id=?", (job_id,)
                ).fetchone()[0], cycle_id=plan["cycle_id"], job_id=job_id,
                subject_type="execution_attempt", subject_id=execution_id,
                payload={"plan_id": plan["plan_id"], "adapter": adapter,
                         "command_sha256": command_sha256, "reason": reason},
                con=con,
            )
        return {
            "execution_id": execution_id, "plan_id": plan["plan_id"],
            "job_id": job_id, "idempotency_key": idempotency_key,
            "adapter": adapter, "command_path": command_path,
            "command_sha256": command_sha256, "status": "prepared", "reused": False,
        }

    def claim_execution_attempt(self, *, execution_id: str, token_sha256: str,
                                claimant: str, reason: str, claimed_at: str,
                                lease_expires_at: str) -> dict:
        """Concede un token una sola vez mediante compare-and-swap transaccional."""
        with self.transaction() as con:
            row = con.execute(
                "SELECT * FROM execution_attempts WHERE execution_id=?", (execution_id,)
            ).fetchone()
            if not row:
                raise ValueError(f"execution attempt inexistente: {execution_id}")
            if row["status"] != "prepared":
                raise RuntimeError(f"execution attempt no reclamable: {row['status']}")
            changed = con.execute(
                """UPDATE execution_attempts SET status='claimed',claim_token_sha256=?,
                claimed_by=?,claimed_at=?,lease_expires_at=?
                WHERE execution_id=? AND status='prepared' AND claim_token_sha256 IS NULL""",
                (token_sha256, claimant, claimed_at, lease_expires_at, execution_id),
            ).rowcount
            if changed != 1:
                raise RuntimeError("claim perdido por concurrencia")
            self._append_attempt_event(
                con, execution_id=execution_id, from_status="prepared", to_status="claimed",
                actor=claimant, reason=reason,
                detail={"lease_expires_at": lease_expires_at}, occurred_at=claimed_at,
            )
        return {"execution_id": execution_id, "status": "claimed",
                "lease_expires_at": lease_expires_at}

    def begin_execution_attempt(self, *, execution_id: str, token_sha256: str,
                                observed_pre_fingerprint: str, actor: str,
                                reason: str, started_at: str) -> dict:
        """Marca el instante a partir del cual cualquier fallo se considera ambiguo."""
        with self.transaction() as con:
            row = con.execute(
                "SELECT * FROM execution_attempts WHERE execution_id=?", (execution_id,)
            ).fetchone()
            if not row or row["claim_token_sha256"] != token_sha256:
                raise PermissionError("claim token inválido")
            if row["status"] != "claimed":
                raise RuntimeError(f"execution attempt no iniciable: {row['status']}")
            if str(row["lease_expires_at"]) <= started_at:
                raise RuntimeError("execution lease expirado")
            if row["expected_pre_fingerprint"] != observed_pre_fingerprint:
                raise RuntimeError("pre-state cambió después del preflight")
            con.execute(
                """UPDATE execution_attempts SET status='applying',started_at=?,
                observed_pre_fingerprint=? WHERE execution_id=? AND status='claimed'""",
                (started_at, observed_pre_fingerprint, execution_id),
            )
            self._append_attempt_event(
                con, execution_id=execution_id, from_status="claimed", to_status="applying",
                actor=actor, reason=reason,
                detail={"observed_pre_fingerprint": observed_pre_fingerprint},
                occurred_at=started_at,
            )
        return {"execution_id": execution_id, "status": "applying"}

    def finish_execution_attempt(self, *, execution_id: str, token_sha256: str,
                                 status: str, actor: str, reason: str,
                                 finished_at: str, detail: dict,
                                 observed_post_fingerprint: str | None = None,
                                 evidence_path: str | None = None,
                                 evidence_sha256: str | None = None,
                                 result_sha256: str | None = None,
                                 error_code: str | None = None,
                                 error_detail: str | None = None) -> dict:
        if status not in {"verified", "failed", "ambiguous", "blocked", "expired"}:
            raise ValueError(f"estado terminal inválido: {status}")
        with self.transaction() as con:
            row = con.execute(
                "SELECT * FROM execution_attempts WHERE execution_id=?", (execution_id,)
            ).fetchone()
            if not row or row["claim_token_sha256"] != token_sha256:
                raise PermissionError("claim token inválido")
            if row["status"] in {"verified", "failed", "ambiguous", "blocked", "expired"}:
                same = row["status"] == status and row["result_sha256"] == result_sha256
                if same:
                    return {**dict(row), "reused": True}
                raise RuntimeError(f"execution attempt ya terminal: {row['status']}")
            allowed_from = {"verified": {"applying"}, "ambiguous": {"applying"},
                            "failed": {"claimed"}, "blocked": {"claimed"},
                            "expired": {"claimed"}}
            if row["status"] not in allowed_from[status]:
                raise RuntimeError(f"transición inválida: {row['status']} -> {status}")
            con.execute(
                """UPDATE execution_attempts SET status=?,finished_at=?,
                observed_post_fingerprint=?,evidence_path=?,evidence_sha256=?,result_sha256=?,
                error_code=?,error_detail=? WHERE execution_id=?""",
                (status, finished_at, observed_post_fingerprint, evidence_path,
                 evidence_sha256, result_sha256, error_code, error_detail, execution_id),
            )
            self._append_attempt_event(
                con, execution_id=execution_id, from_status=str(row["status"]),
                to_status=status, actor=actor, reason=reason, detail=detail,
                occurred_at=finished_at,
            )
            plan = con.execute(
                "SELECT cycle_id FROM execution_plans WHERE plan_id=?", (row["plan_id"],)
            ).fetchone()
            self.append_audit(
                f"execution_attempt_{status}", actor=actor,
                correlation_id=con.execute(
                    "SELECT correlation_id FROM job_runs WHERE job_id=?", (row["job_id"],)
                ).fetchone()[0], cycle_id=plan["cycle_id"], job_id=row["job_id"],
                subject_type="execution_attempt", subject_id=execution_id,
                severity="info" if status == "verified" else "critical" if status == "ambiguous" else "warning",
                payload={"reason": reason, **detail}, con=con,
            )
        return {"execution_id": execution_id, "status": status, "reused": False}

    def execution_attempt(self, execution_id: str) -> dict:
        with self.connect(readonly=True) as con:
            row = con.execute(
                "SELECT * FROM execution_attempts WHERE execution_id=?", (execution_id,)
            ).fetchone()
            events = con.execute(
                "SELECT * FROM execution_attempt_events WHERE execution_id=? ORDER BY sequence",
                (execution_id,),
            ).fetchall()
        if not row:
            raise ValueError(f"execution attempt inexistente: {execution_id}")
        return {**dict(row), "events": [dict(event) for event in events]}

    def execution_attempt_for_job(self, job_id: str) -> dict | None:
        with self.connect(readonly=True) as con:
            row = con.execute(
                "SELECT * FROM execution_attempts WHERE job_id=?", (job_id,)
            ).fetchone()
        return dict(row) if row else None

    def block_prepared_execution(self, *, execution_id: str, actor: str,
                                 reason: str, blocking_codes: list[str],
                                 finished_at: str) -> dict:
        """Cierra sin token un intento que perdió un gate antes del claim."""
        with self.transaction() as con:
            row = con.execute(
                "SELECT * FROM execution_attempts WHERE execution_id=?", (execution_id,)
            ).fetchone()
            if not row:
                raise ValueError(f"execution attempt inexistente: {execution_id}")
            if row["status"] != "prepared":
                raise RuntimeError(f"execution attempt no bloqueable: {row['status']}")
            con.execute(
                """UPDATE execution_attempts SET status='blocked',finished_at=?,
                error_code='RUNTIME_GATES_CHANGED',error_detail=? WHERE execution_id=?""",
                (finished_at, ",".join(blocking_codes), execution_id),
            )
            self._append_attempt_event(
                con, execution_id=execution_id, from_status="prepared", to_status="blocked",
                actor=actor, reason=reason, detail={"blocking_codes": blocking_codes},
                occurred_at=finished_at,
            )
            plan = con.execute(
                "SELECT cycle_id FROM execution_plans WHERE plan_id=?", (row["plan_id"],)
            ).fetchone()
            self.append_audit(
                "execution_attempt_blocked", actor=actor, severity="warning",
                correlation_id=con.execute(
                    "SELECT correlation_id FROM job_runs WHERE job_id=?", (row["job_id"],)
                ).fetchone()[0], cycle_id=plan["cycle_id"], job_id=row["job_id"],
                subject_type="execution_attempt", subject_id=execution_id,
                payload={"reason": reason, "blocking_codes": blocking_codes}, con=con,
            )
        return {"execution_id": execution_id, "status": "blocked",
                "blocking_codes": blocking_codes}

    def seal_verified_decision_cycle(self, cycle_id: str, *, correlation_id: str,
                                     job_id: str) -> dict | None:
        """Cierra propuestas tardías cuando el ciclo ya fue ejecutado y verificado."""
        with self.transaction() as con:
            verified = con.execute(
                """SELECT e.execution_id,d.decision_id,e.finished_at
                FROM web_executions e
                JOIN decision_runs d ON d.decision_id=e.decision_id
                WHERE d.cycle_id=? AND d.status='executed_verified' AND e.status='verified'
                ORDER BY e.finished_at DESC,e.rowid DESC LIMIT 1""",
                (cycle_id,),
            ).fetchone()
            if not verified:
                return None
            superseded = con.execute(
                "UPDATE decision_runs SET status='superseded' "
                "WHERE cycle_id=? AND status='staged'",
                (cycle_id,),
            ).rowcount
            if superseded:
                self.append_audit(
                    "verified_cycle_shadow_decisions_superseded",
                    correlation_id=correlation_id,
                    cycle_id=cycle_id,
                    job_id=job_id,
                    subject_type="web_execution",
                    subject_id=verified["execution_id"],
                    payload={
                        "decision_id": verified["decision_id"],
                        "superseded_shadow_decisions": superseded,
                        "reason": "verified_execution_exists",
                    },
                    con=con,
                )
            return {
                "execution_id": verified["execution_id"],
                "decision_id": verified["decision_id"],
                "finished_at": verified["finished_at"],
                "superseded_shadow_decisions": superseded,
            }

    def record_gameweek_closeout(self, payload: dict) -> dict:
        """Persiste un cierre ya validado en una sola transacción corta.

        El caller resuelve red, resultados, artefactos y métricas antes de entrar
        aquí. Los IDs son deterministas para que una recuperación no duplique la
        memoria de la jornada.
        """
        cycle = payload["cycle"]
        decision = payload["decision"]
        settlement = payload["settlement"]
        review = payload["review"]
        now = utcnow()
        with self.transaction() as con:
            con.execute(
                "INSERT OR IGNORE INTO seasons(season_code,status,created_at) "
                "VALUES(?,'active',?)", (cycle["season"], now),
            )
            con.execute(
                "UPDATE gameweek_cycles SET phase='reconciled',status='reconciled',"
                "last_observed_at=?,revision=revision+1 WHERE cycle_id=?",
                (now, cycle["cycle_id"]),
            )
            source = payload["source_snapshot"]
            con.execute(
                """INSERT OR IGNORE INTO source_snapshots(
                snapshot_id,job_id,cycle_id,source_name,captured_at,artifact_path,
                manifest_sha256,payload_sha256,freshness_seconds,quality_status,quality_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (source["snapshot_id"], payload["job_id"], cycle["cycle_id"],
                 source["source_name"], source["captured_at"], source["artifact_path"],
                 source["manifest_sha256"], source["payload_sha256"], 0, "valid",
                 canonical_json(source["quality"])),
            )
            team = payload["team_state"]
            con.execute(
                """INSERT OR IGNORE INTO team_state_snapshots(
                team_state_id,job_id,cycle_id,observed_at,source_name,squad_json,
                free_transfers,bank_tenths,chips_json,fingerprint,artifact_path,
                manifest_sha256,quality_status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (team["team_state_id"], payload["job_id"], cycle["cycle_id"],
                 team["observed_at"], team["source_name"], canonical_json(team["squad"]),
                 team["free_transfers"], team["bank_tenths"], canonical_json(team["chips"]),
                 team["fingerprint"], team["artifact_path"], team["manifest_sha256"], "valid"),
            )
            for signal in payload.get("research_signals", []):
                con.execute(
                    """INSERT OR IGNORE INTO research_signals(
                    signal_id,job_id,cycle_id,player_element,claim_type,claim_text,
                    source_url,source_tier,observed_at,published_at,expires_at,confidence,
                    conflict_status,content_sha256) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (signal["signal_id"], payload["job_id"], cycle["cycle_id"],
                     signal.get("player_element"), signal["claim_type"], signal["claim_text"],
                     signal["source_url"], signal["source_tier"], signal["observed_at"],
                     signal.get("published_at"), signal["expires_at"], signal["confidence"],
                     signal.get("conflict_status", "none"), signal["content_sha256"]),
                )
            intervention = payload["intervention"]
            con.execute(
                """INSERT OR IGNORE INTO intervention_runs(
                intervention_id,job_id,cycle_id,policy_version,payload_json,payload_sha256,
                rationale,rationale_sha256,created_at) VALUES(?,?,?,?,?,?,?,?,?)""",
                (intervention["intervention_id"], payload["job_id"], cycle["cycle_id"],
                 intervention["policy_version"], canonical_json(intervention["payload"]),
                 sha256_json(intervention["payload"]), intervention["rationale"],
                 hashlib.sha256(intervention["rationale"].encode("utf-8")).hexdigest(),
                 intervention["created_at"]),
            )
            con.execute(
                """INSERT OR IGNORE INTO decision_runs(
                decision_id,job_id,cycle_id,revision,mode,policy_version,status,
                expected_points,chip,fingerprint,manifest_sha256,artifact_path,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (decision["decision_id"], payload["job_id"], cycle["cycle_id"],
                 decision["revision"], decision["mode"], decision["policy_version"],
                 "reconciled", decision["expected_points"], decision.get("chip"),
                 decision["fingerprint"], decision["manifest_sha256"],
                 decision["artifact_path"], decision["created_at"]),
            )
            for player in decision["players"]:
                con.execute(
                    """INSERT OR IGNORE INTO decision_players(
                    decision_id,element,squad_position,role,is_captain,is_vice_captain,
                    transfer_direction,expected_points) VALUES(?,?,?,?,?,?,?,?)""",
                    (decision["decision_id"], player["element"], player["squad_position"],
                     player["role"], int(player["is_captain"]),
                     int(player["is_vice_captain"]), None, player["expected_points"]),
                )
            strategy = payload["chip_strategy"]
            con.execute(
                """INSERT OR IGNORE INTO chip_strategy_runs(
                strategy_id,job_id,cycle_id,window_name,policy_version,inventory_json,
                recommended_chip,status,manifest_sha256,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (strategy["strategy_id"], payload["job_id"], cycle["cycle_id"],
                 strategy["window_name"], strategy["policy_version"],
                 canonical_json(strategy["inventory"]), None, "hold_verified",
                 strategy["manifest_sha256"], strategy["created_at"]),
            )
            execution = payload["execution"]
            con.execute(
                """INSERT OR IGNORE INTO web_executions(
                execution_id,decision_id,action_level,envelope_sha256,status,started_at,
                finished_at,evidence_path,evidence_sha256) VALUES(?,?,?,?,?,?,?,?,?)""",
                (execution["execution_id"], decision["decision_id"], "manual_attestation",
                 execution["envelope_sha256"], "verified", execution["started_at"],
                 execution["finished_at"], execution["evidence_path"],
                 execution["evidence_sha256"]),
            )
            for check in execution["checks"]:
                con.execute(
                    """INSERT OR IGNORE INTO verification_checks(
                    check_id,execution_id,check_name,expected_json,observed_json,passed,checked_at)
                    VALUES(?,?,?,?,?,?,?)""",
                    (check["check_id"], execution["execution_id"], check["check_name"],
                     canonical_json(check["expected"]), canonical_json(check["observed"]),
                     int(check["passed"]), execution["finished_at"]),
                )
            con.execute(
                """INSERT OR IGNORE INTO gameweek_settlements(
                settlement_id,idempotency_key,job_id,cycle_id,source_artifact_id,settled_at,
                entry_points,entry_rank,average_points,bench_points,hit_cost,captain_points,
                auto_subs_json,official_json,artifact_path,artifact_sha256)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (settlement["settlement_id"], settlement["idempotency_key"], payload["job_id"],
                 cycle["cycle_id"], settlement["source_artifact_id"], settlement["settled_at"],
                 settlement["entry_points"], settlement.get("entry_rank"),
                 settlement.get("average_points"), settlement["bench_points"],
                 settlement["hit_cost"], settlement["captain_points"],
                 canonical_json(settlement["auto_subs"]), canonical_json(settlement["official"]),
                 review["artifact_path"], review["artifact_sha256"]),
            )
            con.execute(
                """INSERT OR IGNORE INTO gameweek_reviews(
                review_id,job_id,settlement_id,decision_id,review_type,causality_status,
                expected_points,actual_points,comparator_label,comparator_expected_points,
                comparator_actual_points,realized_delta,metrics_json,findings_json,
                artifact_path,artifact_sha256,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (review["review_id"], payload["job_id"], settlement["settlement_id"],
                 decision["decision_id"], "retrospective",
                 "not_eligible_no_predeadline_batch", review["expected_points"],
                 review["actual_points"], review["comparator_label"],
                 review["comparator_expected_points"], review["comparator_actual_points"],
                 review["realized_delta"], canonical_json(review["metrics"]),
                 canonical_json(review["findings"]), review["artifact_path"],
                 review["artifact_sha256"], review["created_at"]),
            )
            for row in review["player_outcomes"]:
                con.execute(
                    """INSERT OR IGNORE INTO review_player_outcomes(
                    review_id,scenario,element,player_name,role,is_captain,expected_points,
                    p60,actual_points,minutes,effective_points) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (review["review_id"], row["scenario"], row["element"], row["player_name"],
                     row["role"], int(row["is_captain"]), row["expected_points"], row.get("p60"),
                     row["actual_points"], row["minutes"], row["effective_points"]),
                )
            for proposal in review["proposals"]:
                con.execute(
                    """INSERT OR IGNORE INTO change_proposals(
                    proposal_id,review_id,category,change_level,priority,title,hypothesis,
                    evidence_json,acceptance_json,status,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (proposal["proposal_id"], review["review_id"], proposal["category"],
                     proposal["change_level"], proposal["priority"], proposal["title"],
                     proposal["hypothesis"], canonical_json(proposal["evidence"]),
                     canonical_json(proposal["acceptance"]), proposal.get("status", "proposed"),
                     review["created_at"]),
                )
            self.append_audit(
                "gameweek_reconciled", actor=payload["actor"],
                correlation_id=payload["correlation_id"], cycle_id=cycle["cycle_id"],
                job_id=payload["job_id"], subject_type="gameweek_settlement",
                subject_id=settlement["settlement_id"],
                payload={"reason": payload["reason"], "entry_points": settlement["entry_points"],
                         "review_type": "retrospective",
                         "causal_scorecard_created": False}, con=con,
            )
        return {
            "cycle_id": cycle["cycle_id"], "decision_id": decision["decision_id"],
            "settlement_id": settlement["settlement_id"], "review_id": review["review_id"],
            "player_outcomes": len(review["player_outcomes"]),
            "proposals": len(review["proposals"]),
            "research_signals": len(payload.get("research_signals", [])),
            "verification_checks": len(execution["checks"]),
        }

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

    def open_incident_once(self, severity: str, title: str, *,
                           correlation_id: str | None = None,
                           cycle_id: str | None = None, job_id: str | None = None,
                           detail: dict | None = None) -> str:
        """Abre como máximo un incidente activo por título."""
        with self.connect(readonly=True) as con:
            row = con.execute(
                "SELECT incident_id FROM incidents WHERE title=? AND status!='resolved' "
                "ORDER BY opened_at DESC LIMIT 1", (title,),
            ).fetchone()
        if row:
            return str(row["incident_id"])
        return self.open_incident(
            severity, title, correlation_id=correlation_id, cycle_id=cycle_id,
            job_id=job_id, detail=detail,
        )

    def outbox_status(self) -> dict:
        """Resumen sanitizado del canal de alertas, sin exponer payloads."""
        with self.connect(readonly=True) as con:
            rows = con.execute(
                "SELECT status,severity,COUNT(*) AS n FROM outbox_events "
                "GROUP BY status,severity ORDER BY status,severity"
            ).fetchall()
            due = con.execute(
                "SELECT COUNT(*) FROM outbox_events WHERE status IN ('pending','sending') "
                "AND available_at<=?", (utcnow(),),
            ).fetchone()[0]
            latest = con.execute(
                "SELECT outbox_id,event_key,created_at,available_at,event_type,severity,status,"
                "attempts,sent_at,acknowledged_at,last_error FROM outbox_events "
                "ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
        counts: dict[str, dict[str, int]] = {}
        for row in rows:
            counts.setdefault(str(row["status"]), {})[str(row["severity"])] = int(row["n"])
        return {
            "schema": "mova-alert-status-v1", "counts": counts,
            "due": int(due), "latest": [dict(row) for row in latest],
        }

    def enqueue_alert_probe(self, *, job_id: str, correlation_id: str,
                            destination_fingerprint: str) -> str:
        """Crea una prueba P3 idempotente sin fingir un incidente operativo."""
        event_key = f"alert_probe:{job_id}"
        with self.transaction() as con:
            existing = con.execute(
                "SELECT outbox_id FROM outbox_events WHERE event_key=?", (event_key,),
            ).fetchone()
            if existing:
                return str(existing["outbox_id"])
            outbox_id = new_id("outbox")
            con.execute(
                "INSERT INTO outbox_events(outbox_id,event_key,created_at,available_at,"
                "event_type,severity,status,payload_json) VALUES(?,?,?,?,?,?,'pending',?)",
                (outbox_id, event_key, utcnow(), utcnow(), "alert_channel_probe", "P3",
                 canonical_json({
                     "probe_id": job_id,
                     "title": "MOVA alert channel live ping",
                     "destination_fingerprint": destination_fingerprint,
                 })),
            )
            self.append_audit(
                "alert_channel_probe_enqueued", actor="mova-alert-dispatcher",
                correlation_id=correlation_id, job_id=job_id,
                subject_type="outbox_event", subject_id=outbox_id,
                payload={"destination_fingerprint": destination_fingerprint}, con=con,
            )
        return outbox_id

    def claim_outbox_by_id(self, outbox_id: str, *, lease_seconds: int = 120) -> dict | None:
        """Reclama exclusivamente el probe solicitado; nunca drena alertas vecinas."""
        now = datetime.now(timezone.utc)
        available = now.isoformat(timespec="milliseconds")
        lease_until = (now + timedelta(seconds=lease_seconds)).isoformat(timespec="milliseconds")
        with self.transaction() as con:
            row = con.execute(
                "SELECT * FROM outbox_events WHERE outbox_id=?", (outbox_id,),
            ).fetchone()
            if not row or row["status"] not in {"pending", "sending"}:
                return None
            if str(row["available_at"]) > available:
                return None
            con.execute(
                "UPDATE outbox_events SET status='sending',attempts=attempts+1,available_at=? "
                "WHERE outbox_id=?", (lease_until, outbox_id),
            )
            item = dict(row)
            item["attempts"] = int(item["attempts"]) + 1
            item["available_at"] = lease_until
            return item

    def outbox_event_status(self, outbox_id: str) -> dict | None:
        with self.connect(readonly=True) as con:
            row = con.execute(
                "SELECT outbox_id,event_key,created_at,event_type,severity,status,attempts,"
                "sent_at,acknowledged_at,last_error FROM outbox_events WHERE outbox_id=?",
                (outbox_id,),
            ).fetchone()
        return dict(row) if row else None

    def claim_outbox(self, *, limit: int = 20, lease_seconds: int = 120) -> list[dict]:
        """Reclama eventos vencidos con lease; un crash permite reintento posterior."""
        now = datetime.now(timezone.utc)
        available = now.isoformat(timespec="milliseconds")
        lease_until = (now + timedelta(seconds=lease_seconds)).isoformat(timespec="milliseconds")
        with self.transaction() as con:
            rows = con.execute(
                "SELECT * FROM outbox_events WHERE status='pending' AND available_at<=? "
                "OR (status='sending' AND available_at<=?) "
                "ORDER BY CASE severity WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 "
                "WHEN 'P2' THEN 2 ELSE 3 END,created_at LIMIT ?",
                (available, available, max(1, min(limit, 100))),
            ).fetchall()
            claimed = []
            for row in rows:
                con.execute(
                    "UPDATE outbox_events SET status='sending',attempts=attempts+1,"
                    "available_at=? WHERE outbox_id=?", (lease_until, row["outbox_id"]),
                )
                item = dict(row)
                item["attempts"] = int(item["attempts"]) + 1
                item["available_at"] = lease_until
                claimed.append(item)
        return claimed

    def finish_outbox(self, outbox_id: str, *, delivered: bool,
                      error: str | None = None, max_attempts: int = 5,
                      retry_seconds: int = 300) -> str:
        now = datetime.now(timezone.utc)
        with self.transaction() as con:
            row = con.execute(
                "SELECT attempts,status FROM outbox_events WHERE outbox_id=?", (outbox_id,),
            ).fetchone()
            if not row:
                raise ValueError("outbox event not found")
            if delivered:
                status = "sent"
                con.execute(
                    "UPDATE outbox_events SET status='sent',sent_at=?,last_error=NULL "
                    "WHERE outbox_id=?", (now.isoformat(timespec="milliseconds"), outbox_id),
                )
            else:
                status = "dead" if int(row["attempts"]) >= max_attempts else "pending"
                delay = retry_seconds * (2 ** max(0, int(row["attempts"]) - 1))
                con.execute(
                    "UPDATE outbox_events SET status=?,available_at=?,last_error=? "
                    "WHERE outbox_id=?",
                    (status, (now + timedelta(seconds=delay)).isoformat(timespec="milliseconds"),
                     (error or "delivery_failed")[:500], outbox_id),
                )
            self.append_audit(
                "alert_delivery_succeeded" if delivered else "alert_delivery_failed",
                actor="mova-alert-dispatcher", severity="info" if delivered else "warning",
                subject_type="outbox_event", subject_id=outbox_id,
                payload={"status": status, "attempts": int(row["attempts"]),
                         "error_code": (error or "")[:100]}, con=con,
            )
        return status

    def retry_outbox(self, outbox_id: str, *, actor: str, reason: str) -> dict:
        """Reabre explícitamente un evento dead; pending/sending son idempotentes."""
        with self.transaction() as con:
            row = con.execute(
                "SELECT status,attempts FROM outbox_events WHERE outbox_id=?", (outbox_id,),
            ).fetchone()
            if not row:
                raise ValueError("outbox event not found")
            if row["status"] in {"sent", "acknowledged"}:
                raise ValueError("delivered outbox event cannot be retried")
            reused = row["status"] in {"pending", "sending"}
            if not reused:
                con.execute(
                    "UPDATE outbox_events SET status='pending',available_at=?,last_error=NULL "
                    "WHERE outbox_id=?", (utcnow(), outbox_id),
                )
                self.append_audit(
                    "alert_retry_requested", actor=actor, severity="warning",
                    subject_type="outbox_event", subject_id=outbox_id,
                    payload={"reason": reason, "previous_attempts": int(row["attempts"])},
                    con=con,
                )
        return {"outbox_id": outbox_id,
                "status": row["status"] if reused else "pending", "reused": reused}

    def acknowledge_incident(self, incident_id: str, *, actor: str, reason: str) -> dict:
        with self.transaction() as con:
            row = con.execute(
                "SELECT status,title FROM incidents WHERE incident_id=?", (incident_id,),
            ).fetchone()
            if not row:
                raise ValueError("incident not found")
            reused = row["status"] in {"acknowledged", "resolved"}
            if not reused:
                con.execute(
                    "UPDATE incidents SET status='acknowledged',owner=? WHERE incident_id=?",
                    (actor, incident_id),
                )
                con.execute(
                    "UPDATE outbox_events SET status='acknowledged',acknowledged_at=? "
                    "WHERE event_key=? AND status!='acknowledged'",
                    (utcnow(), f"incident:{incident_id}"),
                )
                self.append_audit(
                    "incident_acknowledged", actor=actor, severity="info",
                    subject_type="incident", subject_id=incident_id,
                    payload={"reason": reason, "title": row["title"]}, con=con,
                )
        return {"incident_id": incident_id, "status": row["status"] if reused else "acknowledged",
                "reused": reused}

    def resolve_incidents(self, title: str, *, resolution: str,
                          actor: str = "mova-ops") -> int:
        with self.transaction() as con:
            incidents = con.execute(
                "SELECT incident_id,severity FROM incidents "
                "WHERE title=? AND status!='resolved'", (title,),
            ).fetchall()
            cur = con.execute(
                "UPDATE incidents SET status='resolved',closed_at=?,resolution=? "
                "WHERE title=? AND status!='resolved'", (utcnow(), resolution, title),
            )
            for incident in incidents:
                self.append_audit(
                    "incident_resolved", actor=actor,
                    severity="warning" if incident["severity"] in {"P0", "P1"} else "info",
                    subject_type="incident", subject_id=incident["incident_id"],
                    payload={"title": title, "resolution": resolution}, con=con,
                )
        return int(cur.rowcount)

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

    def resilience_drill_status(self) -> dict:
        with self.connect(readonly=True) as con:
            row = con.execute(
                "SELECT job_id,status,started_at,finished_at,output_sha256,metrics_json,"
                "error_code FROM job_runs WHERE job_type='resilience_drill' "
                "ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        if not row:
            return {"status": "missing", "checks": 0, "passed": 0}
        payload = dict(row)
        metrics = json.loads(payload.pop("metrics_json") or "{}")
        payload.update({"checks": int(metrics.get("checks") or 0),
                        "passed": int(metrics.get("passed") or 0)})
        return payload

    def orchestration_drill_status(self) -> dict:
        with self.connect(readonly=True) as con:
            row = con.execute(
                "SELECT job_id,status,started_at,finished_at,output_sha256,metrics_json,"
                "error_code FROM job_runs WHERE job_type='orchestration_drill' "
                "ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        if not row:
            return {"status": "missing", "checks": 0, "passed": 0}
        payload = dict(row)
        metrics = json.loads(payload.pop("metrics_json") or "{}")
        payload.update({
            "checks": int(metrics.get("checks") or 0),
            "passed": int(metrics.get("passed") or 0),
        })
        return payload

    def alert_channel_drill_status(self) -> dict:
        with self.connect(readonly=True) as con:
            row = con.execute(
                "SELECT job_id,status,started_at,finished_at,output_sha256,metrics_json,"
                "error_code FROM job_runs WHERE job_type='alert_channel_drill' "
                "ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        if not row:
            return {"status": "missing", "checks": 0, "passed": 0}
        payload = dict(row)
        metrics = json.loads(payload.pop("metrics_json") or "{}")
        payload.update({
            "checks": int(metrics.get("checks") or 0),
            "passed": int(metrics.get("passed") or 0),
        })
        return payload

    def alert_channel_live_status(self, destination_fingerprint: str | None = None) -> dict:
        with self.connect(readonly=True) as con:
            rows = con.execute(
                "SELECT job_id,status,started_at,finished_at,output_sha256,metrics_json,"
                "error_code FROM job_runs WHERE job_type='alert_channel_live_ping' "
                "ORDER BY started_at DESC LIMIT 100"
            ).fetchall()
        for row in rows:
            payload = dict(row)
            metrics = json.loads(payload.pop("metrics_json") or "{}")
            if (destination_fingerprint is not None
                    and metrics.get("destination_fingerprint") != destination_fingerprint):
                continue
            payload.update({
                "destination_fingerprint": metrics.get("destination_fingerprint"),
                "delivered": bool(metrics.get("delivered")),
                "external_calls": int(metrics.get("external_calls") or 0),
                "outbox_id": metrics.get("outbox_id"),
            })
            return payload
        return {"status": "missing", "delivered": False, "external_calls": 0}

    def snapshot_rejection_drill_status(self) -> dict:
        with self.connect(readonly=True) as con:
            row = con.execute(
                "SELECT job_id,status,started_at,finished_at,output_sha256,metrics_json,"
                "error_code FROM job_runs WHERE job_type='snapshot_rejection_drill' "
                "ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        if not row:
            return {"status": "missing", "checks": 0, "passed": 0}
        payload = dict(row)
        metrics = json.loads(payload.pop("metrics_json") or "{}")
        payload.update({
            "checks": int(metrics.get("checks") or 0),
            "passed": int(metrics.get("passed") or 0),
        })
        return payload

    def browser_failure_drill_status(self) -> dict:
        with self.connect(readonly=True) as con:
            row = con.execute(
                "SELECT job_id,status,started_at,finished_at,output_sha256,metrics_json,"
                "error_code FROM job_runs WHERE job_type='browser_failure_drill' "
                "ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        if not row:
            return {"status": "missing", "checks": 0, "passed": 0}
        payload = dict(row)
        metrics = json.loads(payload.pop("metrics_json") or "{}")
        payload.update({
            "checks": int(metrics.get("checks") or 0),
            "passed": int(metrics.get("passed") or 0),
        })
        return payload

    def host_recovery_drill_status(self) -> dict:
        """Resume la evidencia más reciente por escenario host requerido."""
        required = (
            "api_recovery", "postgres_recovery", "browser_recovery", "combined_recovery",
        )
        with self.connect(readonly=True) as con:
            rows = con.execute(
                "SELECT job_id,status,started_at,finished_at,output_sha256,metrics_json,"
                "error_code FROM job_runs WHERE job_type='host_recovery_drill' "
                "ORDER BY started_at DESC"
            ).fetchall()
        scenarios: dict[str, dict] = {}
        for raw in rows:
            row = dict(raw)
            metrics = json.loads(row.pop("metrics_json") or "{}")
            scenario = str(metrics.get("scenario") or "")
            if scenario not in required or scenario in scenarios:
                continue
            row.update({
                "checks": int(metrics.get("checks") or 0),
                "passed": int(metrics.get("passed") or 0),
                "downtime_seconds": metrics.get("downtime_seconds"),
            })
            scenarios[scenario] = row
        completed = sum(
            (scenarios.get(name) or {}).get("status") == "completed"
            and int((scenarios.get(name) or {}).get("checks") or 0) > 0
            and int((scenarios.get(name) or {}).get("passed") or 0)
            == int((scenarios.get(name) or {}).get("checks") or 0)
            for name in required
        )
        failed = any(
            (scenarios.get(name) or {}).get("status") == "failed"
            for name in required
        )
        return {
            "status": "completed" if completed == len(required) else
                      "failed" if failed else "incomplete",
            "completed": completed,
            "required": len(required),
            "scenarios": scenarios,
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

    def active_season_plan(self, season: str) -> dict | None:
        with self.connect(readonly=True) as con:
            row = con.execute(
                "SELECT * FROM season_plans WHERE season=? AND status='active' "
                "ORDER BY revision DESC LIMIT 1", (season,),
            ).fetchone()
        if not row:
            return None
        payload = dict(row)
        for key in ("assumptions_json", "chip_windows_json", "guardrails_json"):
            payload[key.removesuffix("_json")] = json.loads(payload.pop(key))
        return payload

    def activate_season_plan(self, season: str, payload: dict, *, actor: str,
                             reason: str) -> dict:
        body = {
            "season": season,
            "horizon_start_gw": int(payload["horizon_start_gw"]),
            "horizon_end_gw": int(payload["horizon_end_gw"]),
            "assumptions": payload.get("assumptions", []),
            "chip_windows": payload.get("chip_windows", []),
            "guardrails": payload.get("guardrails", {}),
            "rationale": str(payload["rationale"]).strip(),
        }
        if not 1 <= body["horizon_start_gw"] <= body["horizon_end_gw"] <= 38:
            raise ValueError("horizonte de plan inválido")
        if not body["rationale"]:
            raise ValueError("rationale del plan es obligatorio")
        content_sha = sha256_json(body)
        now = utcnow()
        with self.transaction() as con:
            existing = con.execute(
                "SELECT * FROM season_plans WHERE season=? AND content_sha256=? "
                "AND status='active' ORDER BY revision DESC LIMIT 1",
                (season, content_sha),
            ).fetchone()
            if existing:
                plan_id = str(existing["plan_id"])
                revision = int(existing["revision"])
            else:
                revision = int(con.execute(
                    "SELECT COALESCE(MAX(revision),0)+1 FROM season_plans WHERE season=?",
                    (season,),
                ).fetchone()[0])
                plan_id = new_id("plan")
                con.execute(
                    "UPDATE season_plans SET status='superseded' "
                    "WHERE season=? AND status='active'", (season,),
                )
                con.execute(
                    """INSERT INTO season_plans(
                    plan_id,season,revision,status,horizon_start_gw,horizon_end_gw,
                    assumptions_json,chip_windows_json,guardrails_json,rationale,
                    actor,reason,content_sha256,created_at)
                    VALUES(?,?,?,'active',?,?,?,?,?,?,?,?,?,?)""",
                    (plan_id, season, revision, body["horizon_start_gw"],
                     body["horizon_end_gw"], canonical_json(body["assumptions"]),
                     canonical_json(body["chip_windows"]), canonical_json(body["guardrails"]),
                     body["rationale"], actor, reason, content_sha, now),
                )
                self.append_audit(
                    "season_plan_activated", actor=actor, subject_type="season_plan",
                    subject_id=plan_id, payload={"season": season, "revision": revision,
                                                "reason": reason,
                                                "content_sha256": content_sha}, con=con,
                )
        return {"plan_id": plan_id, "revision": revision, "content_sha256": content_sha,
                "reused": existing is not None}

    def latest_cycle_manifest(self, cycle_id: str) -> dict | None:
        with self.connect(readonly=True) as con:
            row = con.execute(
                "SELECT * FROM cycle_manifests WHERE cycle_id=? "
                "ORDER BY revision DESC LIMIT 1", (cycle_id,),
            ).fetchone()
        if not row:
            return None
        payload = dict(row)
        for key in ("source_manifest_json", "analytics_manifest_json",
                    "research_summary_json", "memory_summary_json"):
            payload[key.removesuffix("_json")] = json.loads(payload.pop(key))
        return payload

    def add_cycle_manifest(self, payload: dict, *, actor: str = "mova-strategy") -> dict:
        body = {
            "cycle_id": payload["cycle_id"],
            "as_of_at": payload["as_of_at"],
            "deadline_at": payload["deadline_at"],
            "phase": payload["phase"],
            "team_state_id": payload.get("team_state_id"),
            "plan_id": payload.get("plan_id"),
            "source_manifest": payload["source_manifest"],
            "analytics_manifest": payload["analytics_manifest"],
            "research_summary": payload["research_summary"],
            "memory_summary": payload.get("memory_summary", {}),
        }
        content_sha = sha256_json(body)
        now = utcnow()
        with self.transaction() as con:
            existing = con.execute(
                "SELECT * FROM cycle_manifests WHERE cycle_id=? AND content_sha256=?",
                (body["cycle_id"], content_sha),
            ).fetchone()
            if existing:
                return {"manifest_id": existing["manifest_id"],
                        "revision": int(existing["revision"]),
                        "content_sha256": content_sha, "reused": True,
                        "artifact_path": existing["artifact_path"]}
            revision = int(con.execute(
                "SELECT COALESCE(MAX(revision),0)+1 FROM cycle_manifests WHERE cycle_id=?",
                (body["cycle_id"],),
            ).fetchone()[0])
            manifest_id = new_id("manifest")
            artifact_path = str(payload["artifact_path"])
            con.execute(
                """INSERT INTO cycle_manifests(
                manifest_id,cycle_id,revision,as_of_at,deadline_at,phase,team_state_id,
                plan_id,source_manifest_json,analytics_manifest_json,research_summary_json,
                memory_summary_json,artifact_path,content_sha256,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (manifest_id, body["cycle_id"], revision, body["as_of_at"],
                 body["deadline_at"], body["phase"], body["team_state_id"], body["plan_id"],
                 canonical_json(body["source_manifest"]),
                 canonical_json(body["analytics_manifest"]),
                 canonical_json(body["research_summary"]),
                 canonical_json(body["memory_summary"]), artifact_path, content_sha, now),
            )
            self.append_audit(
                "cycle_manifest_sealed", actor=actor, cycle_id=body["cycle_id"],
                subject_type="cycle_manifest", subject_id=manifest_id,
                payload={"revision": revision, "content_sha256": content_sha,
                         "artifact_path": artifact_path}, con=con,
            )
        return {"manifest_id": manifest_id, "revision": revision,
                "content_sha256": content_sha, "reused": False,
                "artifact_path": artifact_path}

    @staticmethod
    def _agent_budget_aggregates(con: sqlite3.Connection, *,
                                 cycle_id: str | None = None,
                                 month: str | None = None) -> dict:
        """Return physical-call accounting while retaining pre-budget ledger rows."""
        if (cycle_id is None) == (month is None):
            raise ValueError("budget scope requiere exactamente cycle_id o month")
        if cycle_id is not None:
            reservation_where, ledger_where = "r.cycle_id=?", "c.cycle_id=?"
            params = (cycle_id,)
        else:
            reservation_where = "substr(r.created_at,1,7)=?"
            ledger_where = "substr(c.occurred_at,1,7)=?"
            params = (month,)
        settled = con.execute(
            f"""WITH accounted(tokens,uses) AS (
              SELECT COALESCE(r.actual_tokens,0),COALESCE(r.attempt_count,1)
              FROM agent_budget_reservations r
              WHERE r.status='settled' AND {reservation_where}
              UNION ALL
              SELECT COALESCE(c.input_tokens,0)+COALESCE(c.output_tokens,0),1
              FROM cost_ledger c WHERE {ledger_where}
                AND NOT EXISTS (SELECT 1 FROM agent_budget_reservations r
                  WHERE r.subject_id=c.subject_id AND r.status='settled')
            ) SELECT COALESCE(SUM(tokens),0) tokens,COALESCE(SUM(uses),0) uses
            FROM accounted""", (*params, *params),
        ).fetchone()
        reserved = con.execute(
            f"""SELECT COUNT(*) uses,COALESCE(SUM(reserved_tokens),0) tokens
            FROM agent_budget_reservations r
            WHERE r.status='reserved' AND {reservation_where}""", params,
        ).fetchone()
        charged = con.execute(
            f"""SELECT COALESCE(SUM(COALESCE(attempt_count,1)),0) uses,
            COALESCE(SUM(COALESCE(actual_tokens,reserved_tokens)),0) tokens,
            COALESCE(SUM(COALESCE(estimated_tokens,
              CASE WHEN accounting_mode='conservative' THEN actual_tokens ELSE 0 END)),0)
              estimated_tokens,
            COALESCE(SUM(CASE WHEN COALESCE(estimated_tokens,0)>0
              THEN COALESCE(attempt_count,1) ELSE 0 END),0) estimated_uses
            FROM agent_budget_reservations r
            WHERE r.status='charged' AND {reservation_where}""", params,
        ).fetchone()
        cost = con.execute(
            f"""SELECT SUM(c.estimated_cost_usd) estimated_cost_usd
            FROM cost_ledger c WHERE {ledger_where}""", params,
        ).fetchone()
        return {"settled": settled, "reserved": reserved, "charged": charged,
                "estimated_cost_usd": cost["estimated_cost_usd"]}

    def _reserve_agent_budget(self, con: sqlite3.Connection, *, cycle_id: str,
                              subject_type: str, subject_id: str, provider: str,
                              policy: dict | None, actor: str, now: str,
                              job_id: str | None = None) -> dict | None:
        """Reserva presupuesto junto con el job; `None` conserva fixtures legacy."""
        if policy is None:
            return None
        required = {"reservation_tokens", "job_tokens", "gw_tokens", "month_tokens",
                    "gw_uses", "month_uses"}
        if set(policy) != required or any(
            not isinstance(policy[key], int) or policy[key] <= 0 for key in required
        ):
            raise ValueError("agent budget policy inválida")
        existing = con.execute(
            "SELECT * FROM agent_budget_reservations WHERE subject_id=?", (subject_id,)
        ).fetchone()
        if existing:
            return {**dict(existing), "reused": True}
        month = now[:7]
        gw_accounting = self._agent_budget_aggregates(con, cycle_id=cycle_id)
        month_accounting = self._agent_budget_aggregates(con, month=month)
        estimate = int(policy["reservation_tokens"])
        gw_tokens = sum(int(gw_accounting[k]["tokens"])
                        for k in ("settled", "reserved", "charged"))
        month_tokens = sum(int(month_accounting[k]["tokens"])
                           for k in ("settled", "reserved", "charged"))
        gw_uses = sum(int(gw_accounting[k]["uses"])
                      for k in ("settled", "reserved", "charged"))
        month_uses = sum(int(month_accounting[k]["uses"])
                         for k in ("settled", "reserved", "charged"))
        checks = {
            "job_tokens": {"used": estimate, "limit": policy["job_tokens"],
                           "passed": estimate <= policy["job_tokens"]},
            "gw_tokens": {"used": gw_tokens + estimate, "limit": policy["gw_tokens"],
                          "passed": gw_tokens + estimate <= policy["gw_tokens"]},
            "month_tokens": {"used": month_tokens + estimate,
                             "limit": policy["month_tokens"],
                             "passed": month_tokens + estimate <= policy["month_tokens"]},
            "gw_uses": {"used": gw_uses + 1, "limit": policy["gw_uses"],
                        "passed": gw_uses + 1 <= policy["gw_uses"]},
            "month_uses": {"used": month_uses + 1, "limit": policy["month_uses"],
                           "passed": month_uses + 1 <= policy["month_uses"]},
        }
        passed = all(item["passed"] for item in checks.values())
        result = {"status": "reserved" if passed else "blocked", "month": month,
                  "estimate_tokens": estimate, "checks": checks,
                  "policy": dict(policy)}
        if not passed:
            self.append_audit(
                "agent_budget_blocked", actor=actor, severity="warning",
                cycle_id=cycle_id, job_id=job_id, subject_type=subject_type,
                subject_id=subject_id, payload=result, con=con,
            )
            return result
        reservation_id = "budget_" + hashlib.sha256(
            f"{subject_type}:{subject_id}".encode("utf-8")
        ).hexdigest()[:24]
        con.execute(
            """INSERT INTO agent_budget_reservations(
            reservation_id,cycle_id,subject_type,subject_id,provider,reserved_tokens,
            status,policy_json,created_at) VALUES(?,?,?,?,?,?,'reserved',?,?)""",
            (reservation_id, cycle_id, subject_type, subject_id, provider, estimate,
             canonical_json(policy), now),
        )
        self.append_audit(
            "agent_budget_reserved", actor=actor, cycle_id=cycle_id, job_id=job_id,
            subject_type=subject_type, subject_id=subject_id,
            payload={**result, "reservation_id": reservation_id}, con=con,
        )
        return {**result, "reservation_id": reservation_id}

    @staticmethod
    def _physical_attempt_accounting(con: sqlite3.Connection, *, reservation,
                                     usage: dict | None = None) -> dict:
        """Account every physical start; estimate only attempts without token evidence."""
        rows = con.execute(
            """SELECT attempt_id,status,input_tokens,output_tokens
            FROM agent_worker_attempt_events
            WHERE subject_id=? AND event_type='finished' ORDER BY occurred_at""",
            (reservation["subject_id"],),
        ).fetchall()
        starts = int(con.execute(
            "SELECT COUNT(DISTINCT attempt_id) FROM agent_worker_attempt_events "
            "WHERE subject_id=? AND event_type='started'",
            (reservation["subject_id"],),
        ).fetchone()[0])
        raw_input = int((usage or {}).get("input_tokens") or 0)
        raw_output = int((usage or {}).get("output_tokens") or 0)
        observed_input = 0
        observed_output = 0
        unknown = 0
        used_result_fallback = False
        for row in rows:
            if row["input_tokens"] is not None and row["output_tokens"] is not None:
                observed_input += int(row["input_tokens"])
                observed_output += int(row["output_tokens"])
            elif row["status"] == "succeeded" and usage is not None and not used_result_fallback:
                observed_input += raw_input
                observed_output += raw_output
                used_result_fallback = True
            else:
                unknown += 1
        unknown += max(0, starts - len(rows))
        if starts == 0:
            if usage is not None:
                return {
                    "accounted_tokens": raw_input + raw_output,
                    "observed_tokens": raw_input + raw_output,
                    "estimated_tokens": 0, "attempt_count": 1,
                    "finished_attempts": 0, "accounting_mode": "legacy",
                }
            unknown = 1
            starts = 1
        estimate = unknown * int(reservation["reserved_tokens"])
        observed = observed_input + observed_output
        return {
            "accounted_tokens": observed + estimate,
            "observed_tokens": observed,
            "estimated_tokens": estimate,
            "attempt_count": starts,
            "finished_attempts": len(rows),
            "accounting_mode": "exact" if unknown == 0 else "conservative",
        }

    def _settle_agent_budget(self, con: sqlite3.Connection, *, subject_id: str,
                             usage: dict, cycle_id: str, actor: str, now: str,
                             job_id: str | None = None) -> dict | None:
        reservation = con.execute(
            "SELECT * FROM agent_budget_reservations WHERE subject_id=?", (subject_id,)
        ).fetchone()
        if not reservation:
            return None
        accounting = self._physical_attempt_accounting(
            con, reservation=reservation, usage=usage
        )
        actual = (int(reservation["actual_tokens"])
                  if reservation["status"] == "settled"
                  else int(accounting["accounted_tokens"]))
        policy = json.loads(reservation["policy_json"])
        overrun = actual > int(policy["job_tokens"])
        result = {"status": "settled", "reservation_id": reservation["reservation_id"],
                  "reserved_tokens": int(reservation["reserved_tokens"]),
                  "actual_tokens": actual, "job_limit": int(policy["job_tokens"]),
                  "overrun": overrun,
                  "attempt_count": int(reservation["attempt_count"] or 1)
                  if reservation["status"] == "settled"
                  else accounting["attempt_count"],
                  "accounting_mode": reservation["accounting_mode"] or "legacy"
                  if reservation["status"] == "settled"
                  else accounting["accounting_mode"]}
        if reservation["status"] == "settled":
            return {**result, "reused": True}
        con.execute(
            "UPDATE agent_budget_reservations SET status='settled',actual_tokens=?,"
            "accounting_mode=?,attempt_count=?,estimated_tokens=?,settled_at=? "
            "WHERE reservation_id=?",
            (actual, accounting["accounting_mode"], accounting["attempt_count"],
             accounting["estimated_tokens"], now, reservation["reservation_id"]),
        )
        self.append_audit(
            "agent_budget_settled", actor=actor,
            severity="warning" if overrun else "info", cycle_id=cycle_id, job_id=job_id,
            subject_type=reservation["subject_type"], subject_id=subject_id,
            payload=result, con=con,
        )
        return {**result, "reused": False}

    def _charge_agent_budget_estimate(self, con: sqlite3.Connection, *,
                                      subject_id: str, cycle_id: str,
                                      actor: str, now: str,
                                      job_id: str | None = None) -> None:
        reservation = con.execute(
            "SELECT * FROM agent_budget_reservations WHERE subject_id=?", (subject_id,)
        ).fetchone()
        if not reservation or reservation["status"] != "reserved":
            return
        accounting = self._physical_attempt_accounting(con, reservation=reservation)
        con.execute(
            "UPDATE agent_budget_reservations SET status='charged',actual_tokens=?,"
            "accounting_mode=?,attempt_count=?,estimated_tokens=?,settled_at=? "
            "WHERE reservation_id=?",
            (accounting["accounted_tokens"], accounting["accounting_mode"],
             accounting["attempt_count"], accounting["estimated_tokens"], now,
             reservation["reservation_id"]),
        )
        self.append_audit(
            ("agent_budget_charged" if accounting["accounting_mode"] == "exact"
             else "agent_budget_charged_estimate"),
            actor=actor, severity="warning",
            cycle_id=cycle_id, job_id=job_id,
            subject_type=reservation["subject_type"], subject_id=subject_id,
            payload={"reservation_id": reservation["reservation_id"],
                     "accounted_tokens": accounting["accounted_tokens"],
                     "observed_tokens": accounting["observed_tokens"],
                     "estimated_tokens": accounting["estimated_tokens"],
                     "attempt_count": accounting["attempt_count"],
                     "accounting_mode": accounting["accounting_mode"],
                     "reason": "result_unavailable_or_rejected"}, con=con,
        )

    def queue_research_run(self, payload: dict) -> dict:
        now = utcnow()
        with self.transaction() as con:
            existing = con.execute(
                "SELECT * FROM research_runs WHERE cycle_id=? AND manifest_id=? "
                "AND provider=? AND request_sha256=?",
                (payload["cycle_id"], payload["manifest_id"], payload["provider"],
                 payload["request_sha256"]),
            ).fetchone()
            if existing:
                return {**dict(existing), "reused": True}
            run_id = payload["research_run_id"]
            budget = self._reserve_agent_budget(
                con, cycle_id=payload["cycle_id"], subject_type="research",
                subject_id=run_id, provider=payload["provider"],
                policy=payload.get("budget_policy"), actor="mova-research",
                job_id=payload.get("job_id"), now=now,
            )
            if budget and budget["status"] == "blocked":
                return {"research_run_id": run_id, "status": "blocked",
                        "reason": "agent_budget_exceeded", "budget": budget,
                        "reused": False}
            con.execute(
                """INSERT INTO research_runs(
                research_run_id,job_id,cycle_id,manifest_id,provider,status,
                request_path,request_sha256,queued_at)
                VALUES(?,?,?,?,?,'queued',?,?,?)""",
                (run_id, payload.get("job_id"), payload["cycle_id"], payload["manifest_id"],
                 payload["provider"], payload["request_path"], payload["request_sha256"], now),
            )
            self.append_audit(
                "research_queued", actor="mova-research", cycle_id=payload["cycle_id"],
                job_id=payload.get("job_id"), subject_type="research_run", subject_id=run_id,
                payload={"provider": payload["provider"],
                         "request_sha256": payload["request_sha256"]}, con=con,
            )
        return {"research_run_id": run_id, "status": "queued", "queued_at": now,
                "budget": budget, "reused": False}

    def research_run(self, research_run_id: str) -> dict | None:
        with self.connect(readonly=True) as con:
            row = con.execute(
                "SELECT * FROM research_runs WHERE research_run_id=?",
                (research_run_id,),
            ).fetchone()
        return dict(row) if row else None

    def agent_subject(self, subject_type: str, subject_id: str) -> dict | None:
        if subject_type == "research":
            table, key = "research_runs", "research_run_id"
        elif subject_type == "deliberation":
            table, key = "decision_deliberations", "deliberation_id"
        else:
            raise ValueError("subject_type agentic inválido")
        with self.connect(readonly=True) as con:
            row = con.execute(
                f"SELECT * FROM {table} WHERE {key}=?", (subject_id,)
            ).fetchone()
        return dict(row) if row else None

    def pending_agent_subjects(self) -> list[dict]:
        with self.connect(readonly=True) as con:
            rows = con.execute(
                """SELECT 'research' subject_type,research_run_id subject_id,cycle_id,
                request_path,request_sha256,queued_at FROM research_runs WHERE status='queued'
                UNION ALL
                SELECT 'deliberation',deliberation_id,cycle_id,request_path,request_sha256,
                queued_at FROM decision_deliberations WHERE status='queued'
                ORDER BY queued_at,subject_id"""
            ).fetchall()
        return [dict(row) for row in rows]

    def prepare_agent_attempt_authorization(
        self, *, subject_type: str, subject_id: str, permit_dir: str,
        now: datetime, permit_ttl_seconds: int, final_cutoff_seconds: int,
    ) -> dict:
        """Atomically re-check budget/deadline before a physical agent call."""
        current = now.astimezone(timezone.utc)
        now_text = current.isoformat(timespec="milliseconds")
        with self.transaction() as con:
            if subject_type == "research":
                table, key = "research_runs", "research_run_id"
            elif subject_type == "deliberation":
                table, key = "decision_deliberations", "deliberation_id"
            else:
                raise ValueError("subject_type agentic inválido")
            subject = con.execute(
                f"SELECT * FROM {table} WHERE {key}=?", (subject_id,)
            ).fetchone()
            if not subject or subject["status"] != "queued":
                return {"status": "skipped", "reason": "subject_not_queued"}
            cycle = con.execute(
                "SELECT * FROM gameweek_cycles WHERE cycle_id=?", (subject["cycle_id"],)
            ).fetchone()
            if not cycle:
                return {"status": "blocked", "reason": "cycle_missing"}
            deadline = datetime.fromisoformat(
                str(cycle["deadline_at"]).replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            seconds_to_deadline = int((deadline - current).total_seconds())
            starts = int(con.execute(
                "SELECT COUNT(DISTINCT attempt_id) FROM agent_worker_attempt_events "
                "WHERE subject_type=? AND subject_id=? AND event_type='started'",
                (subject_type, subject_id),
            ).fetchone()[0])
            successes = int(con.execute(
                "SELECT COUNT(DISTINCT attempt_id) FROM agent_worker_attempt_events "
                "WHERE subject_type=? AND subject_id=? AND event_type='finished' "
                "AND status='succeeded'", (subject_type, subject_id),
            ).fetchone()[0])
            attempt_number = starts + 1
            reservation = con.execute(
                "SELECT * FROM agent_budget_reservations WHERE subject_id=?",
                (subject_id,),
            ).fetchone()
            checks: dict[str, dict] = {
                "subject_queued": {"passed": True, "observed": subject["status"]},
                "no_success": {"passed": successes == 0, "observed": successes},
                "attempt_limit": {"passed": attempt_number <= 2,
                                  "observed": attempt_number, "limit": 2},
                "deadline_open": {
                    "passed": seconds_to_deadline > final_cutoff_seconds,
                    "observed_seconds": seconds_to_deadline,
                    "required_seconds": final_cutoff_seconds,
                },
                "reservation_active": {
                    "passed": bool(reservation and reservation["status"] == "reserved"),
                    "observed": reservation["status"] if reservation else "missing",
                },
            }

            def audit_blocked(result: dict) -> None:
                already = con.execute(
                    "SELECT 1 FROM audit_events WHERE "
                    "event_type='agent_attempt_authorization_blocked' "
                    "AND subject_type=? AND subject_id=? "
                    "AND json_extract(payload_json,'$.attempt_number')=? "
                    "AND json_extract(payload_json,'$.reason')=? LIMIT 1",
                    (subject_type, subject_id, attempt_number, result["reason"]),
                ).fetchone()
                if not already:
                    self.append_audit(
                        "agent_attempt_authorization_blocked",
                        actor="mova-agent-authorizer", severity="warning",
                        cycle_id=subject["cycle_id"], subject_type=subject_type,
                        subject_id=subject_id, payload=result, con=con,
                    )

            if not all(item["passed"] for item in checks.values()):
                result = {"status": "blocked", "reason": "pre_attempt_gate_failed",
                          "subject_type": subject_type, "subject_id": subject_id,
                          "attempt_number": attempt_number, "checks": checks}
                audit_blocked(result)
                return result
            policy = json.loads(reservation["policy_json"])
            physical = self._physical_attempt_accounting(con, reservation=reservation)
            previous_tokens = int(physical["accounted_tokens"]) if starts else 0
            gw = self._agent_budget_aggregates(con, cycle_id=subject["cycle_id"])
            month = self._agent_budget_aggregates(con, month=now_text[:7])

            def committed(scope: dict, field: str) -> int:
                return sum(int(scope[name][field])
                           for name in ("settled", "reserved", "charged"))

            projected_job = previous_tokens + int(reservation["reserved_tokens"])
            projected_gw_tokens = committed(gw, "tokens") + previous_tokens
            projected_month_tokens = committed(month, "tokens") + previous_tokens
            projected_gw_uses = committed(gw, "uses") + starts
            projected_month_uses = committed(month, "uses") + starts
            checks.update({
                "job_tokens": {"passed": projected_job <= int(policy["job_tokens"]),
                               "used": projected_job, "limit": int(policy["job_tokens"])},
                "gw_tokens": {"passed": projected_gw_tokens <= int(policy["gw_tokens"]),
                              "used": projected_gw_tokens,
                              "limit": int(policy["gw_tokens"])},
                "month_tokens": {
                    "passed": projected_month_tokens <= int(policy["month_tokens"]),
                    "used": projected_month_tokens,
                    "limit": int(policy["month_tokens"]),
                },
                "gw_uses": {"passed": projected_gw_uses <= int(policy["gw_uses"]),
                            "used": projected_gw_uses, "limit": int(policy["gw_uses"])},
                "month_uses": {
                    "passed": projected_month_uses <= int(policy["month_uses"]),
                    "used": projected_month_uses, "limit": int(policy["month_uses"]),
                },
            })
            if not all(item["passed"] for item in checks.values()):
                result = {"status": "blocked", "reason": "pre_attempt_budget_exceeded",
                          "subject_type": subject_type, "subject_id": subject_id,
                          "attempt_number": attempt_number, "checks": checks}
                audit_blocked(result)
                return result
            con.execute(
                "UPDATE agent_attempt_authorizations SET status='expired' "
                "WHERE subject_id=? AND status IN ('preparing','authorized') AND expires_at<=?",
                (subject_id, now_text),
            )
            existing = con.execute(
                "SELECT * FROM agent_attempt_authorizations WHERE subject_id=? "
                "AND request_sha256=? AND attempt_number=? "
                "AND status IN ('preparing','authorized') AND expires_at>? "
                "ORDER BY created_at DESC LIMIT 1",
                (subject_id, subject["request_sha256"], attempt_number, now_text),
            ).fetchone()
            if existing:
                return {**dict(existing), "budget_snapshot": json.loads(
                    existing["budget_snapshot_json"]), "reused": True}
            expires = min(
                current + timedelta(seconds=permit_ttl_seconds),
                deadline - timedelta(seconds=final_cutoff_seconds),
            )
            authorization_id = new_id("agentauth")
            permit_path = str(
                Path(permit_dir) / f"{subject_id}.{authorization_id}.permit.json"
            )
            snapshot = {
                "checks": checks, "previous_attempts": starts,
                "previous_accounted_tokens": previous_tokens,
                "reservation_id": reservation["reservation_id"],
                "reservation_tokens": int(reservation["reserved_tokens"]),
            }
            con.execute(
                """INSERT INTO agent_attempt_authorizations(
                authorization_id,subject_type,subject_id,request_sha256,attempt_number,status,
                budget_snapshot_json,deadline_at,expires_at,permit_path,created_at)
                VALUES(?,?,?,?,?,'preparing',?,?,?,?,?)""",
                (authorization_id, subject_type, subject_id, subject["request_sha256"],
                 attempt_number, canonical_json(snapshot), deadline.isoformat(),
                 expires.isoformat(), permit_path, now_text),
            )
        return {
            "authorization_id": authorization_id, "subject_type": subject_type,
            "subject_id": subject_id, "request_sha256": subject["request_sha256"],
            "attempt_number": attempt_number, "status": "preparing",
            "deadline_at": deadline.isoformat(), "expires_at": expires.isoformat(),
            "permit_path": permit_path, "budget_snapshot": snapshot, "reused": False,
        }

    def seal_agent_attempt_authorization(self, authorization_id: str, *,
                                         permit_sha256: str) -> dict:
        if not re.fullmatch(r"[0-9a-f]{64}", permit_sha256):
            raise ValueError("permit_sha256 inválido")
        with self.transaction() as con:
            row = con.execute(
                "SELECT * FROM agent_attempt_authorizations WHERE authorization_id=?",
                (authorization_id,),
            ).fetchone()
            if not row:
                raise ValueError("autorización agentic desconocida")
            if row["status"] == "authorized":
                if row["permit_sha256"] != permit_sha256:
                    raise ValueError("replay de permiso con contenido diferente")
                return {**dict(row), "reused": True}
            if row["status"] != "preparing":
                raise ValueError("autorización agentic no sellable")
            con.execute(
                "UPDATE agent_attempt_authorizations SET status='authorized',permit_sha256=? "
                "WHERE authorization_id=?", (permit_sha256, authorization_id),
            )
            if row["subject_type"] == "research":
                subject_table, subject_key = "research_runs", "research_run_id"
            else:
                subject_table, subject_key = "decision_deliberations", "deliberation_id"
            cycle_id = con.execute(
                f"SELECT cycle_id FROM {subject_table} WHERE {subject_key}=?",
                (row["subject_id"],),
            ).fetchone()[0]
            self.append_audit(
                "agent_attempt_authorized", actor="mova-agent-authorizer",
                cycle_id=cycle_id,
                subject_type=row["subject_type"], subject_id=row["subject_id"],
                payload={"authorization_id": authorization_id,
                         "attempt_number": int(row["attempt_number"]),
                         "permit_sha256": permit_sha256,
                         "expires_at": row["expires_at"]}, con=con,
            )
        return {**dict(row), "status": "authorized", "permit_sha256": permit_sha256,
                "reused": False}

    def agent_attempt_authorization(self, authorization_id: str) -> dict | None:
        with self.connect(readonly=True) as con:
            row = con.execute(
                "SELECT * FROM agent_attempt_authorizations WHERE authorization_id=?",
                (authorization_id,),
            ).fetchone()
        return dict(row) if row else None

    def record_agent_worker_attempt_event(self, payload: dict, *, receipt_path: str,
                                          receipt_sha256: str) -> dict:
        event_id = "agentattempt_" + hashlib.sha256(
            f"{payload['attempt_id']}:{payload['event_type']}".encode("utf-8")
        ).hexdigest()[:24]
        with self.transaction() as con:
            existing = con.execute(
                "SELECT * FROM agent_worker_attempt_events WHERE event_id=?", (event_id,)
            ).fetchone()
            if existing:
                if existing["receipt_sha256"] != receipt_sha256:
                    raise ValueError("receipt replay con contenido diferente")
                return {**dict(existing), "reused": True}
            authorization_id = payload.get("authorization_id")
            if authorization_id:
                authorization = con.execute(
                    "SELECT * FROM agent_attempt_authorizations WHERE authorization_id=?",
                    (authorization_id,),
                ).fetchone()
                if not authorization:
                    raise ValueError("receipt sin autorización durable")
                if (authorization["subject_type"] != payload["subject_type"]
                        or authorization["subject_id"] != payload["subject_id"]
                        or authorization["request_sha256"] != payload["request_sha256"]):
                    raise ValueError("receipt no coincide con su autorización")
                occurred = datetime.fromisoformat(
                    str(payload["occurred_at"]).replace("Z", "+00:00")
                )
                expires = datetime.fromisoformat(
                    str(authorization["expires_at"]).replace("Z", "+00:00")
                )
                if payload["event_type"] == "started":
                    if authorization["status"] != "authorized" or occurred > expires:
                        raise ValueError("autorización expirada o ya consumida")
                    con.execute(
                        "UPDATE agent_attempt_authorizations SET status='started',"
                        "attempt_id=?,started_at=? WHERE authorization_id=?",
                        (payload["attempt_id"], payload["occurred_at"], authorization_id),
                    )
                else:
                    if (authorization["status"] != "started"
                            or authorization["attempt_id"] != payload["attempt_id"]):
                        raise ValueError("finish no corresponde al start autorizado")
                    con.execute(
                        "UPDATE agent_attempt_authorizations SET status='finished',"
                        "finished_at=? WHERE authorization_id=?",
                        (payload["occurred_at"], authorization_id),
                    )
            elif payload.get("schema") != "mova-agent-attempt-v1":
                raise ValueError("receipt actual exige autorización")
            con.execute(
                """INSERT INTO agent_worker_attempt_events(
                event_id,attempt_id,subject_type,subject_id,request_sha256,event_type,status,
                model,input_tokens,output_tokens,duration_ms,error_code,output_present,
                receipt_path,receipt_sha256,occurred_at,authorization_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (event_id, payload["attempt_id"], payload["subject_type"],
                 payload["subject_id"], payload["request_sha256"], payload["event_type"],
                 payload["status"], payload["model"], payload.get("input_tokens"),
                 payload.get("output_tokens"), payload.get("duration_ms"),
                 payload.get("error_code"), payload.get("output_present"), receipt_path,
                 receipt_sha256, payload["occurred_at"], authorization_id),
            )
            subject = self.agent_subject(payload["subject_type"], payload["subject_id"])
            self.append_audit(
                "agent_worker_attempt_" + payload["event_type"], actor="mova-agent-worker",
                severity="warning" if payload["status"] == "failed" else "info",
                cycle_id=subject.get("cycle_id") if subject else None,
                subject_type=payload["subject_type"], subject_id=payload["subject_id"],
                payload={
                    "attempt_id": payload["attempt_id"], "status": payload["status"],
                    "authorization_id": authorization_id,
                    "error_code": payload.get("error_code"),
                    "input_tokens": payload.get("input_tokens"),
                    "output_tokens": payload.get("output_tokens"),
                    "duration_ms": payload.get("duration_ms"),
                    "receipt_sha256": receipt_sha256,
                }, con=con,
            )
        return {"event_id": event_id, "attempt_id": payload["attempt_id"],
                "event_type": payload["event_type"], "reused": False}

    def agent_worker_attempt_status(self) -> dict:
        with self.connect(readonly=True) as con:
            rows = con.execute(
                """SELECT subject_type,subject_id,
                COUNT(DISTINCT CASE WHEN event_type='started' THEN attempt_id END) AS attempts,
                COUNT(DISTINCT CASE WHEN event_type='finished' AND status='failed'
                                    THEN attempt_id END) AS failures,
                COUNT(DISTINCT CASE WHEN event_type='finished' AND status='succeeded'
                                    THEN attempt_id END) AS successes,
                MAX(occurred_at) AS last_event_at
                FROM agent_worker_attempt_events
                GROUP BY subject_type,subject_id ORDER BY last_event_at DESC"""
            ).fetchall()
            authorization_rows = con.execute(
                "SELECT status,COUNT(*) count FROM agent_attempt_authorizations "
                "GROUP BY status ORDER BY status"
            ).fetchall()
        subjects = [dict(row) for row in rows]
        totals = {"attempts": 0, "failures": 0, "successes": 0}
        for row in subjects:
            for key in totals:
                totals[key] += int(row[key])
        exhausted = sum(
            int(row["attempts"]) >= 2 and not int(row["successes"]) for row in subjects
        )
        authorizations = {row["status"]: int(row["count"])
                          for row in authorization_rows}
        return {"status": "ok", "max_automatic_attempts": 2,
                "subjects": subjects, "subject_count": len(subjects),
                "totals": totals, "exhausted_subjects": exhausted,
                "authorizations": authorizations}

    def agent_worker_attempt_prometheus(self) -> str:
        report = self.agent_worker_attempt_status()
        lines = [
            "# HELP mova_agent_worker_attempts Agent worker attempts by terminal outcome.",
            "# TYPE mova_agent_worker_attempts gauge",
            "# HELP mova_agent_worker_exhausted_subjects Subjects that reached the replay limit.",
            "# TYPE mova_agent_worker_exhausted_subjects gauge",
            "# HELP mova_agent_attempt_authorizations Physical-call permits by state.",
            "# TYPE mova_agent_attempt_authorizations gauge",
            f'mova_agent_worker_attempts{{status="started"}} {report["totals"]["attempts"]}',
            f'mova_agent_worker_attempts{{status="failed"}} {report["totals"]["failures"]}',
            f'mova_agent_worker_attempts{{status="succeeded"}} {report["totals"]["successes"]}',
            f'mova_agent_worker_exhausted_subjects {report["exhausted_subjects"]}',
        ]
        for status in ("preparing", "authorized", "started", "finished", "expired"):
            lines.append(
                f'mova_agent_attempt_authorizations{{status="{status}"}} '
                f'{report["authorizations"].get(status, 0)}'
            )
        return "\n".join(lines) + "\n"

    def reject_research_run(self, research_run_id: str, *, error_code: str,
                            error_detail: str) -> None:
        with self.transaction() as con:
            run = con.execute(
                "SELECT cycle_id,job_id,status FROM research_runs WHERE research_run_id=?",
                (research_run_id,),
            ).fetchone()
            if not run or run["status"] == "imported":
                return
            con.execute(
                "UPDATE research_runs SET status='rejected',error_code=?,error_detail=?,"
                "finished_at=? WHERE research_run_id=?",
                (error_code, error_detail[:500], utcnow(), research_run_id),
            )
            self._charge_agent_budget_estimate(
                con, subject_id=research_run_id, cycle_id=run["cycle_id"],
                job_id=run["job_id"], actor="mova-research-validator", now=utcnow(),
            )
            self.append_audit(
                "research_rejected", actor="mova-research-validator",
                cycle_id=run["cycle_id"], job_id=run["job_id"],
                subject_type="research_run", subject_id=research_run_id,
                severity="warning",
                payload={"error_code": error_code, "error_detail": error_detail[:500]},
                con=con,
            )

    def import_research_result(self, research_run_id: str, payload: dict, *,
                               result_path: str, result_sha256: str) -> dict:
        now = utcnow()
        with self.transaction() as con:
            run = con.execute(
                "SELECT * FROM research_runs WHERE research_run_id=?",
                (research_run_id,),
            ).fetchone()
            if not run:
                raise ValueError("research_run desconocido")
            if run["status"] == "imported":
                return {"research_run_id": research_run_id, "status": "imported",
                        "reused": True}
            document_ids: dict[str, str] = {}
            documents_by_url: dict[str, dict] = {}
            for document in payload["documents"]:
                document_id = document.get("document_id") or new_id("document")
                document_ids[document["source_url"]] = document_id
                documents_by_url[document["source_url"]] = document
                con.execute(
                    """INSERT OR IGNORE INTO research_documents(
                    document_id,research_run_id,source_url,title,publisher,published_at,
                    observed_at,source_tier,content_sha256,final_url,fetch_status,http_status,
                    content_type,body_sha256,normalized_sha256,storage_mode,locator_type,locator,
                    excerpt,excerpt_sha256,artifact_path,artifact_sha256,fetch_error_code)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (document_id, research_run_id, document["source_url"], document["title"],
                     document["publisher"], document.get("published_at"), now,
                     document["source_tier"], sha256_json(document),
                     document.get("final_url"),
                     document.get("fetch_status", "legacy_unverified"),
                     document.get("http_status"), document.get("content_type"),
                     document.get("body_sha256"), document.get("normalized_sha256"),
                     document.get("storage_mode"), document.get("locator_type"),
                     document.get("locator"), document.get("excerpt"),
                     document.get("excerpt_sha256"), document.get("artifact_path"),
                     document.get("artifact_sha256"), document.get("error_code")),
                )
            accepted = 0
            for signal in payload["signals"]:
                evidence_urls = signal["source_urls"]
                validation = signal["validation_status"]
                source_url = evidence_urls[0]
                signal_body = {
                    "claim": signal["claim_text"], "source_urls": evidence_urls,
                    "direction": signal["direction"],
                }
                evidence_refs = [{
                    "document_id": document_ids.get(url),
                    "locator_type": documents_by_url[url].get("locator_type"),
                    "locator": documents_by_url[url].get("locator"),
                    "excerpt_sha256": documents_by_url[url].get("excerpt_sha256"),
                    "fetch_status": documents_by_url[url].get(
                        "fetch_status", "legacy_unverified"
                    ),
                } for url in evidence_urls]
                con.execute(
                    """INSERT OR IGNORE INTO research_signals(
                    signal_id,job_id,cycle_id,player_element,claim_type,claim_text,
                    source_url,source_tier,observed_at,published_at,expires_at,confidence,
                    conflict_status,content_sha256,research_run_id,subject_name,direction,
                    validation_status,evidence_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (new_id("signal"), run["job_id"], run["cycle_id"],
                     signal.get("player_element"), signal["claim_type"],
                     signal["claim_text"], source_url, signal["source_tier"], now,
                     signal.get("published_at"), signal["expires_at"], signal["confidence"],
                     signal["conflict_status"], sha256_json(signal_body), research_run_id,
                     signal["subject_name"], signal["direction"], validation,
                     canonical_json({"source_urls": evidence_urls,
                                     "document_ids": [document_ids.get(url)
                                                      for url in evidence_urls],
                                     "evidence_refs": evidence_refs})),
                )
                accepted += validation == "accepted"
            for conflict in payload["conflicts"]:
                con.execute(
                    """INSERT INTO research_conflicts(
                    conflict_id,research_run_id,cycle_id,subject,claim_type,description,
                    source_urls_json,status,created_at) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (new_id("conflict"), research_run_id, run["cycle_id"],
                     conflict["subject"], conflict["claim_type"], conflict["description"],
                     canonical_json(conflict["source_urls"]), conflict["status"], now),
                )
            usage = payload.get("usage", {})
            coverage = payload.get("coverage", {})
            con.execute(
                """UPDATE research_runs SET status='imported',result_path=?,
                result_sha256=?,usage_json=?,finished_at=?,imported_at=?,
                result_schema=?,coverage_json=?,coverage_status=?,coverage_ratio=?,
                evidence_ratio=?,error_code=NULL,error_detail=NULL
                WHERE research_run_id=?""",
                (result_path, result_sha256, canonical_json(usage), now, now,
                 payload.get("schema", "mova-research-brief-v1"),
                 canonical_json(coverage),
                 coverage.get("status", "legacy_unmeasured"),
                 coverage.get("coverage_ratio"), coverage.get("evidence_ratio"),
                 research_run_id),
            )
            con.execute(
                """INSERT INTO cost_ledger(
                cost_id,research_run_id,provider,model,input_tokens,output_tokens,
                estimated_cost_usd,subscription_usage,detail_json,occurred_at,
                cycle_id,subject_type,subject_id,category,duration_ms,search_requests)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (new_id("cost"), research_run_id, run["provider"], usage.get("model"),
                 usage.get("input_tokens"), usage.get("output_tokens"),
                 usage.get("estimated_cost_usd"), 1, canonical_json(usage), now,
                 run["cycle_id"], "research", research_run_id, "news_research",
                 usage.get("duration_ms"), usage.get("search_requests")),
            )
            budget_settlement = self._settle_agent_budget(
                con, subject_id=research_run_id, usage=usage, cycle_id=run["cycle_id"],
                job_id=run["job_id"], actor="mova-research-validator", now=now,
            )
            self.append_audit(
                "research_imported", actor="mova-research-validator",
                cycle_id=run["cycle_id"], job_id=run["job_id"],
                subject_type="research_run", subject_id=research_run_id,
                payload={"documents": len(payload["documents"]),
                         "signals": len(payload["signals"]), "accepted": accepted,
                         "conflicts": len(payload["conflicts"]),
                         "coverage_status": coverage.get("status", "legacy_unmeasured"),
                         "coverage_ratio": coverage.get("coverage_ratio"),
                         "evidence_ratio": coverage.get("evidence_ratio"),
                         "result_sha256": result_sha256}, con=con,
            )
        return {"research_run_id": research_run_id, "status": "imported",
                "documents": len(payload["documents"]), "signals": len(payload["signals"]),
                "accepted": accepted, "conflicts": len(payload["conflicts"]),
                "coverage": coverage,
                "budget_settlement": budget_settlement,
                "reused": False}

    def deliberation_source(self) -> dict | None:
        """Último envelope vigente con los enlaces necesarios para deliberar."""
        with self.connect(readonly=True) as con:
            row = con.execute(
                """SELECT e.envelope_id,e.cycle_id,e.manifest_id,e.artifact_path,
                e.artifact_sha256,e.content_sha256,d.manifest_sha256,c.season,c.gw
                FROM decision_envelopes e
                JOIN decision_runs d ON d.decision_id=e.decision_id
                JOIN gameweek_cycles c ON c.cycle_id=e.cycle_id
                WHERE e.status IN ('blocked','staged')
                ORDER BY e.created_at DESC LIMIT 1"""
            ).fetchone()
        return dict(row) if row else None

    def decision_deliberation_for_envelope(self, envelope_id: str) -> dict | None:
        with self.connect(readonly=True) as con:
            row = con.execute(
                """SELECT d.*,b.binding_type,b.envelope_id AS bound_envelope_id
                FROM decision_deliberation_bindings b
                JOIN decision_deliberations d ON d.deliberation_id=b.deliberation_id
                WHERE b.envelope_id=?""",
                (envelope_id,),
            ).fetchone()
            if not row:  # filas legacy anteriores a migration 017
                row = con.execute(
                    "SELECT * FROM decision_deliberations WHERE envelope_id=?",
                    (envelope_id,),
                ).fetchone()
        return dict(row) if row else None

    def decision_deliberation(self, deliberation_id: str) -> dict | None:
        with self.connect(readonly=True) as con:
            row = con.execute(
                "SELECT * FROM decision_deliberations WHERE deliberation_id=?",
                (deliberation_id,),
            ).fetchone()
        return dict(row) if row else None

    def queue_decision_deliberation(self, payload: dict) -> dict:
        now = utcnow()
        with self.transaction() as con:
            existing = con.execute(
                """SELECT d.*,b.binding_type,b.envelope_id AS bound_envelope_id
                FROM decision_deliberation_bindings b
                JOIN decision_deliberations d ON d.deliberation_id=b.deliberation_id
                WHERE b.envelope_id=?""",
                (payload["envelope_id"],),
            ).fetchone()
            if not existing:  # filas legacy anteriores a migration 017
                existing = con.execute(
                    "SELECT * FROM decision_deliberations WHERE envelope_id=?",
                    (payload["envelope_id"],),
                ).fetchone()
            if existing:
                binding_type = existing["binding_type"] if "binding_type" in existing.keys() else None
                return {**dict(existing), "reused": True,
                        "semantic_reused": binding_type == "semantic_reuse",
                        "budget_reserved": False}
            # Legacy fixtures/callers still receive a one-request-only binding. They do
            # not gain cross-envelope reuse until they provide the explicit semantic SHA.
            semantic_sha = payload.get("semantic_input_sha256") or payload["request_sha256"]
            semantic_dedupe_enabled = bool(payload.get("semantic_input_sha256"))
            semantic = con.execute(
                "SELECT * FROM decision_deliberations WHERE cycle_id=? AND provider=? "
                "AND semantic_input_sha256=? ORDER BY queued_at DESC LIMIT 1",
                (payload["cycle_id"], payload["provider"], semantic_sha),
            ).fetchone() if semantic_dedupe_enabled else None
            if semantic:
                con.execute(
                    """INSERT INTO decision_deliberation_bindings(
                    envelope_id,deliberation_id,semantic_input_sha256,binding_type,created_at)
                    VALUES(?,?,?,'semantic_reuse',?)""",
                    (payload["envelope_id"], semantic["deliberation_id"], semantic_sha, now),
                )
                self.append_audit(
                    "decision_deliberation_semantically_reused", actor="mova-strategy",
                    cycle_id=payload["cycle_id"], subject_type="decision_deliberation",
                    subject_id=semantic["deliberation_id"], payload={
                        "source_envelope_id": semantic["envelope_id"],
                        "bound_envelope_id": payload["envelope_id"],
                        "semantic_input_sha256": semantic_sha,
                        "budget_reserved": False,
                    }, con=con,
                )
                return {**dict(semantic), "reused": True, "semantic_reused": True,
                        "source_envelope_id": semantic["envelope_id"],
                        "bound_envelope_id": payload["envelope_id"],
                        "budget_reserved": False}
            budget = self._reserve_agent_budget(
                con, cycle_id=payload["cycle_id"], subject_type="deliberation",
                subject_id=payload["deliberation_id"], provider=payload["provider"],
                policy=payload.get("budget_policy"), actor="mova-strategy", now=now,
            )
            if budget and budget["status"] == "blocked":
                return {"deliberation_id": payload["deliberation_id"],
                        "status": "blocked", "reason": "agent_budget_exceeded",
                        "budget": budget, "reused": False}
            con.execute(
                """INSERT INTO decision_deliberations(
                deliberation_id,cycle_id,envelope_id,manifest_id,provider,status,
                request_path,request_sha256,semantic_input_sha256,queued_at)
                VALUES(?,?,?,?,?,'queued',?,?,?,?)""",
                (payload["deliberation_id"], payload["cycle_id"], payload["envelope_id"],
                 payload["manifest_id"], payload["provider"], payload["request_path"],
                 payload["request_sha256"], semantic_sha, now),
            )
            con.execute(
                """INSERT INTO decision_deliberation_bindings(
                envelope_id,deliberation_id,semantic_input_sha256,binding_type,created_at)
                VALUES(?,?,?,'original',?)""",
                (payload["envelope_id"], payload["deliberation_id"], semantic_sha, now),
            )
            self.append_audit(
                "decision_deliberation_queued", actor="mova-strategy",
                cycle_id=payload["cycle_id"], subject_type="decision_deliberation",
                subject_id=payload["deliberation_id"], payload={
                    "envelope_id": payload["envelope_id"],
                    "manifest_id": payload["manifest_id"],
                    "request_sha256": payload["request_sha256"],
                    "authority": "advisory_shadow_only",
                }, con=con,
            )
        return {"deliberation_id": payload["deliberation_id"], "status": "queued",
                "queued_at": now, "budget": budget, "reused": False,
                "semantic_reused": False, "budget_reserved": bool(budget)}

    def reject_decision_deliberation(self, deliberation_id: str, *, error_code: str,
                                     error_detail: str) -> None:
        with self.transaction() as con:
            row = con.execute(
                "SELECT cycle_id,status FROM decision_deliberations WHERE deliberation_id=?",
                (deliberation_id,),
            ).fetchone()
            if not row or row["status"] in {"accepted", "review_required", "blocked"}:
                return
            con.execute(
                "UPDATE decision_deliberations SET status='rejected',error_code=?,"
                "error_detail=?,finished_at=? WHERE deliberation_id=?",
                (error_code, error_detail[:500], utcnow(), deliberation_id),
            )
            self._charge_agent_budget_estimate(
                con, subject_id=deliberation_id, cycle_id=row["cycle_id"],
                actor="mova-deliberation-validator", now=utcnow(),
            )
            self.append_audit(
                "decision_deliberation_rejected", actor="mova-deliberation-validator",
                cycle_id=row["cycle_id"], subject_type="decision_deliberation",
                subject_id=deliberation_id, severity="warning",
                payload={"error_code": error_code, "error_detail": error_detail[:500]},
                con=con,
            )

    def import_decision_deliberation(self, deliberation_id: str, payload: dict, *,
                                     result_path: str, result_sha256: str) -> dict:
        now = utcnow()
        strategist = payload["strategist"]
        critic = payload["critic"]
        intervention = strategist["intervention"]
        intervention_sha = sha256_json(intervention)
        intervention_id = f"intervention_{intervention_sha[:24]}"
        with self.transaction() as con:
            run = con.execute(
                """SELECT q.*,e.job_id FROM decision_deliberations q
                JOIN decision_envelopes e ON e.envelope_id=q.envelope_id
                WHERE q.deliberation_id=?""", (deliberation_id,),
            ).fetchone()
            if not run:
                raise ValueError("deliberación desconocida")
            if run["status"] in {"accepted", "review_required", "blocked"}:
                return {"deliberation_id": deliberation_id, "status": run["status"],
                        "reused": True}
            con.execute(
                """UPDATE decision_deliberations SET status=?,result_path=?,result_sha256=?,
                preferred_candidate_key=?,critic_verdict=?,strategist_json=?,critic_json=?,
                intervention_json=?,intervention_sha256=?,usage_json=?,finished_at=?,
                imported_at=?,error_code=NULL,error_detail=NULL WHERE deliberation_id=?""",
                (payload["status"], result_path, result_sha256,
                 strategist["preferred_candidate_key"], critic["verdict"],
                 canonical_json(strategist), canonical_json(critic),
                 canonical_json(intervention), intervention_sha,
                 canonical_json(payload["usage"]), now, now, deliberation_id),
            )
            con.execute(
                """INSERT OR IGNORE INTO intervention_runs(
                intervention_id,job_id,cycle_id,policy_version,payload_json,payload_sha256,
                rationale,rationale_sha256,created_at) VALUES(?,?,?,?,?,?,?,?,?)""",
                (intervention_id, run["job_id"], run["cycle_id"],
                 intervention["policy_version"], canonical_json(intervention),
                 intervention_sha, intervention["rationale"],
                 hashlib.sha256(intervention["rationale"].encode("utf-8")).hexdigest(), now),
            )
            for risk in critic["risks"]:
                risk_id = "deliberationrisk_" + hashlib.sha256(
                    f"{deliberation_id}:{risk['code']}".encode("utf-8")
                ).hexdigest()[:24]
                con.execute(
                    """INSERT INTO decision_deliberation_risks(
                    risk_id,deliberation_id,code,severity,candidate_key,claim,mitigation,
                    created_at) VALUES(?,?,?,?,?,?,?,?)""",
                    (risk_id, deliberation_id, risk["code"], risk["severity"],
                     risk.get("candidate_key"), risk["claim"], risk["mitigation"], now),
                )
            usage = payload["usage"]
            con.execute(
                """INSERT INTO cost_ledger(
                cost_id,research_run_id,provider,model,input_tokens,output_tokens,
                estimated_cost_usd,subscription_usage,detail_json,occurred_at,
                cycle_id,subject_type,subject_id,category,duration_ms,search_requests)
                VALUES(?,NULL,?,?,?,?,?,1,?,?,?,?,?,?,?,?)""",
                (new_id("cost"), run["provider"], usage.get("model"),
                 usage.get("input_tokens"), usage.get("output_tokens"),
                 usage.get("estimated_cost_usd"), canonical_json({
                     **usage, "deliberation_id": deliberation_id,
                     "kind": "strategy_critic",
                 }), now, run["cycle_id"], "deliberation", deliberation_id,
                 "strategy_critic", usage.get("duration_ms"),
                 usage.get("search_requests")),
            )
            budget_settlement = self._settle_agent_budget(
                con, subject_id=deliberation_id, usage=usage,
                cycle_id=run["cycle_id"], job_id=run["job_id"],
                actor="mova-deliberation-validator", now=now,
            )
            self.append_audit(
                "decision_deliberation_imported", actor="mova-deliberation-validator",
                cycle_id=run["cycle_id"], job_id=run["job_id"],
                subject_type="decision_deliberation", subject_id=deliberation_id,
                severity="warning" if payload["status"] == "blocked" else "info",
                payload={
                    "envelope_id": run["envelope_id"], "status": payload["status"],
                    "preferred_candidate_key": strategist["preferred_candidate_key"],
                    "critic_verdict": critic["verdict"],
                    "risk_count": len(critic["risks"]),
                    "intervention_sha256": intervention_sha,
                    "intervention_applied": False,
                    "result_sha256": result_sha256,
                }, con=con,
            )
        return {"deliberation_id": deliberation_id, "status": payload["status"],
                "preferred_candidate_key": strategist["preferred_candidate_key"],
                "critic_verdict": critic["verdict"], "risks": len(critic["risks"]),
                "intervention_id": intervention_id, "intervention_applied": False,
                "budget_settlement": budget_settlement,
                "reused": False}

    def deliberation_status(self, cycle_id: str | None = None) -> dict:
        with self.connect(readonly=True) as con:
            if cycle_id is None:
                cycle = con.execute(
                    "SELECT cycle_id FROM gameweek_cycles ORDER BY deadline_at DESC LIMIT 1"
                ).fetchone()
                cycle_id = str(cycle["cycle_id"]) if cycle else None
            if not cycle_id:
                return {"status": "empty", "cycle_id": None, "latest": None}
            latest = con.execute(
                """SELECT d.*,b.binding_type,b.envelope_id AS bound_envelope_id
                FROM decision_envelopes e
                JOIN decision_deliberation_bindings b ON b.envelope_id=e.envelope_id
                JOIN decision_deliberations d ON d.deliberation_id=b.deliberation_id
                WHERE e.cycle_id=? AND e.status IN ('blocked','staged')
                ORDER BY e.created_at DESC LIMIT 1""", (cycle_id,),
            ).fetchone()
            if not latest:
                latest = con.execute(
                    "SELECT * FROM decision_deliberations WHERE cycle_id=? "
                    "ORDER BY queued_at DESC LIMIT 1", (cycle_id,),
                ).fetchone()
            risks = []
            if latest:
                risks = con.execute(
                    "SELECT code,severity,candidate_key,claim,mitigation FROM "
                    "decision_deliberation_risks WHERE deliberation_id=? ORDER BY code",
                    (latest["deliberation_id"],),
                ).fetchall()
        return {"status": str(latest["status"]) if latest else "missing",
                "cycle_id": cycle_id, "latest": dict(latest) if latest else None,
                "risks": [dict(row) for row in risks]}

    def strategic_status(self, cycle_id: str | None = None) -> dict:
        with self.connect(readonly=True) as con:
            if cycle_id is None:
                row = con.execute(
                    "SELECT cycle_id FROM gameweek_cycles ORDER BY deadline_at DESC LIMIT 1"
                ).fetchone()
                cycle_id = str(row["cycle_id"]) if row else None
            if not cycle_id:
                return {"status": "empty", "cycle_id": None}
            manifest = con.execute(
                "SELECT * FROM cycle_manifests WHERE cycle_id=? "
                "ORDER BY revision DESC LIMIT 1", (cycle_id,),
            ).fetchone()
            runs = con.execute(
                "SELECT research_run_id,provider,status,queued_at,finished_at,imported_at,"
                "error_code FROM research_runs WHERE cycle_id=? ORDER BY queued_at DESC",
                (cycle_id,),
            ).fetchall()
            signals = con.execute(
                "SELECT validation_status,conflict_status,COUNT(*) n FROM research_signals "
                "WHERE cycle_id=? GROUP BY validation_status,conflict_status", (cycle_id,),
            ).fetchall()
            conflicts = int(con.execute(
                "SELECT COUNT(*) FROM research_conflicts WHERE cycle_id=? AND status='unresolved'",
                (cycle_id,),
            ).fetchone()[0])
            latest_global = con.execute(
                "SELECT research_run_id,cycle_id,provider,status,queued_at,finished_at,"
                "imported_at,error_code FROM research_runs ORDER BY queued_at DESC LIMIT 1"
            ).fetchone()
            global_counts = {
                str(row["status"]): int(row["n"])
                for row in con.execute(
                    "SELECT status,COUNT(*) n FROM research_runs GROUP BY status"
                ).fetchall()
            }
            global_documents = int(con.execute(
                "SELECT COUNT(*) FROM research_documents"
            ).fetchone()[0])
            global_accepted = int(con.execute(
                "SELECT COUNT(*) FROM research_signals "
                "WHERE validation_status='accepted'"
            ).fetchone()[0])
            global_conflicts = int(con.execute(
                "SELECT COUNT(*) FROM research_conflicts WHERE status='unresolved'"
            ).fetchone()[0])
        latest_payload = dict(latest_global) if latest_global else None
        manifest_payload = dict(manifest) if manifest else None
        memory_summary = None
        if manifest_payload:
            try:
                memory_summary = json.loads(manifest_payload["memory_summary_json"])
            except (KeyError, TypeError, json.JSONDecodeError):
                memory_summary = {"status": "invalid", "quality_status": "invalid"}
        service_status = "missing"
        if latest_payload:
            service_status = (
                "healthy" if latest_payload["status"] == "imported"
                else "running" if latest_payload["status"] in {"queued", "running", "completed"}
                else "degraded"
            )
        coverage = self.research_coverage(limit=12)
        return {
            "status": "ready" if manifest else "not_prepared", "cycle_id": cycle_id,
            "manifest": manifest_payload,
            "memory_summary": memory_summary,
            "research_runs": [dict(row) for row in runs],
            "signals": [dict(row) for row in signals],
            "unresolved_conflicts": conflicts,
            "service": {
                "status": service_status,
                "latest_run": latest_payload,
                "run_counts": global_counts,
                "documents": global_documents,
                "accepted_signals": global_accepted,
                "unresolved_conflicts": global_conflicts,
                "coverage": coverage,
            },
        }

    def research_coverage(self, *, limit: int = 20) -> dict:
        """Evaluate evidence coverage across immutable imported research runs."""
        policy = {
            "version": "research-coverage-2026.08.1",
            "minimum_measured_gameweeks": 3,
            "minimum_coverage_ratio": 0.90,
            "minimum_evidence_ratio": 0.80,
            "maximum_unresolved_conflicts": 0,
        }
        with self.connect(readonly=True) as con:
            rows = con.execute(
                """SELECT r.research_run_id,r.cycle_id,c.season,c.gw,r.status,
                r.result_schema,r.coverage_status,r.coverage_ratio,r.evidence_ratio,
                r.coverage_json,r.queued_at,r.imported_at,
                (SELECT COUNT(*) FROM research_documents d
                  WHERE d.research_run_id=r.research_run_id) documents,
                (SELECT COUNT(*) FROM research_documents d
                  WHERE d.research_run_id=r.research_run_id AND d.fetch_status='verified')
                  verified_documents,
                (SELECT COUNT(*) FROM research_signals s
                  WHERE s.research_run_id=r.research_run_id
                    AND s.validation_status='accepted') accepted_signals,
                (SELECT COUNT(*) FROM research_signals s
                  WHERE s.research_run_id=r.research_run_id
                    AND s.validation_status='candidate') candidate_signals,
                (SELECT COUNT(*) FROM research_conflicts x
                  WHERE x.research_run_id=r.research_run_id AND x.status='unresolved')
                  unresolved_conflicts
                FROM research_runs r JOIN gameweek_cycles c ON c.cycle_id=r.cycle_id
                WHERE r.status='imported' ORDER BY r.imported_at DESC LIMIT ?""",
                (max(1, min(int(limit), 100)),),
            ).fetchall()
        runs = []
        for row in rows:
            item = dict(row)
            try:
                item["coverage"] = json.loads(item.pop("coverage_json"))
            except (TypeError, json.JSONDecodeError):
                item["coverage"] = {"status": "failed", "reason": "invalid_json"}
                item.pop("coverage_json", None)
            runs.append(item)
        latest_by_cycle = {}
        for row in runs:
            latest_by_cycle.setdefault(row["cycle_id"], row)
        measured = [
            row for row in latest_by_cycle.values()
            if row["coverage_status"] in {"complete", "partial", "failed"}
        ]
        passing = [
            row for row in measured
            if float(row["coverage_ratio"] or 0) >= policy["minimum_coverage_ratio"]
            and float(row["evidence_ratio"] or 0) >= policy["minimum_evidence_ratio"]
            and int(row["unresolved_conflicts"] or 0)
                <= policy["maximum_unresolved_conflicts"]
        ]
        if len(measured) < policy["minimum_measured_gameweeks"]:
            gate = "insufficient_gameweeks"
        elif len(passing) == len(measured):
            gate = "passed"
        else:
            gate = "failed"
        return {
            "schema": "mova-research-coverage-report-v1", "policy": policy,
            "status": gate, "measured_gameweeks": len(measured),
            "passing_gameweeks": len(passing),
            "legacy_unmeasured_gameweeks": sum(
                row["coverage_status"] == "legacy_unmeasured"
                for row in latest_by_cycle.values()
            ),
            "latest": runs[0] if runs else None, "runs": runs,
        }

    def gameweek_review_status(self, season: str, gw: int) -> dict:
        """Devuelve la memoria post-settlement sin abrir SQLite fuera del runtime."""
        with self.connect(readonly=True) as con:
            review = con.execute(
                """SELECT r.*,s.cycle_id,s.settled_at,s.entry_points,s.entry_rank,
                s.average_points,s.bench_points,s.hit_cost,s.captain_points,
                s.auto_subs_json,s.official_json
                FROM gameweek_reviews r
                JOIN gameweek_settlements s ON s.settlement_id=r.settlement_id
                JOIN gameweek_cycles c ON c.cycle_id=s.cycle_id
                WHERE c.season=? AND c.gw=?
                ORDER BY r.created_at DESC LIMIT 1""", (season, int(gw)),
            ).fetchone()
            if not review:
                return {"status": "not_found", "season": season, "gw": int(gw)}
            payload = dict(review)
            players = con.execute(
                "SELECT * FROM review_player_outcomes WHERE review_id=? "
                "ORDER BY scenario,role DESC,element",
                (review["review_id"],),
            ).fetchall()
            proposals = con.execute(
                """SELECT p.* FROM change_proposals p
                JOIN gameweek_reviews rr ON rr.review_id=p.review_id
                WHERE rr.settlement_id=? ORDER BY p.priority,p.created_at,p.proposal_id""",
                (review["settlement_id"],),
            ).fetchall()
        for key in ("metrics_json", "findings_json", "auto_subs_json", "official_json"):
            payload[key.removesuffix("_json")] = json.loads(payload.pop(key))
        proposal_rows = []
        for row in proposals:
            item = dict(row)
            item["evidence"] = json.loads(item.pop("evidence_json"))
            item["acceptance"] = json.loads(item.pop("acceptance_json"))
            proposal_rows.append(item)
        return {
            "status": "closed", "season": season, "gw": int(gw),
            "review": payload, "player_outcomes": [dict(row) for row in players],
            "change_proposals": proposal_rows,
        }

    def causal_review_source(self, season: str, gw: int) -> dict | None:
        with self.connect(readonly=True) as con:
            row = con.execute(
                """SELECT r.*,s.cycle_id,s.source_artifact_id,s.official_json,
                s.settled_at,c.season,c.gw
                FROM gameweek_reviews r
                JOIN gameweek_settlements s ON s.settlement_id=r.settlement_id
                JOIN gameweek_cycles c ON c.cycle_id=s.cycle_id
                WHERE c.season=? AND c.gw=? AND r.review_type='retrospective'
                ORDER BY r.created_at DESC LIMIT 1""", (season, int(gw)),
            ).fetchone()
        if not row:
            return None
        payload = dict(row)
        payload["official"] = json.loads(payload.pop("official_json"))
        payload["metrics"] = json.loads(payload.pop("metrics_json"))
        payload["findings"] = json.loads(payload.pop("findings_json"))
        return payload

    def pending_causal_review_gws(self, season: str) -> list[int]:
        with self.connect(readonly=True) as con:
            rows = con.execute(
                """SELECT c.gw FROM gameweek_settlements s
                JOIN gameweek_cycles c ON c.cycle_id=s.cycle_id
                JOIN gameweek_reviews r ON r.settlement_id=s.settlement_id
                  AND r.review_type='retrospective'
                LEFT JOIN gameweek_reviews causal ON causal.settlement_id=s.settlement_id
                  AND causal.review_type='causal'
                WHERE c.season=? AND causal.review_id IS NULL ORDER BY c.gw""", (season,),
            ).fetchall()
        return [int(row["gw"]) for row in rows]

    def causal_review_context(self, cycle_id: str) -> dict:
        with self.connect(readonly=True) as con:
            conflicts = con.execute(
                "SELECT COUNT(*) FROM research_conflicts WHERE cycle_id=? AND status='unresolved'",
                (cycle_id,),
            ).fetchone()[0]
            checks = con.execute(
                """SELECT COUNT(*) FROM decision_validation_checks v
                JOIN decision_envelopes e ON e.envelope_id=v.envelope_id
                WHERE e.cycle_id=? AND v.passed=0""",
                (cycle_id,),
            ).fetchone()[0]
            executions = con.execute(
                """SELECT COUNT(*) FROM execution_attempts a
                JOIN execution_plans p ON p.plan_id=a.plan_id
                WHERE p.cycle_id=? AND a.status IN ('failed','ambiguous')""", (cycle_id,),
            ).fetchone()[0]
            reviews = con.execute(
                "SELECT findings_json FROM gameweek_reviews WHERE review_type='causal'"
            ).fetchall()
        occurrences: dict[str, int] = {}
        for row in reviews:
            for finding in json.loads(row["findings_json"]):
                category = str(finding.get("category") or "")
                occurrences[category] = occurrences.get(category, 0) + 1
        return {"unresolved_research_conflicts": int(conflicts),
                "failed_validation_checks": int(checks),
                "execution_failures": int(executions),
                "category_occurrences": occurrences}

    def record_causal_review(self, payload: dict) -> dict:
        source = payload["source"]
        with self.transaction() as con:
            existing = con.execute(
                "SELECT review_id FROM gameweek_reviews WHERE settlement_id=? "
                "AND review_type='causal'", (source["settlement_id"],),
            ).fetchone()
            if existing:
                return {"review_id": existing["review_id"], "reused": True}
            con.execute(
                """INSERT INTO gameweek_reviews(
                review_id,job_id,settlement_id,decision_id,review_type,causality_status,
                expected_points,actual_points,comparator_label,comparator_expected_points,
                comparator_actual_points,realized_delta,metrics_json,findings_json,
                artifact_path,artifact_sha256,created_at)
                VALUES(?,?,?,?,'causal','eligible',?,?,?,?,?,?,?,?,?,?,?)""",
                (payload["review_id"], payload["job_id"], source["settlement_id"],
                 source["decision_id"], source["expected_points"], source["actual_points"],
                 source["comparator_label"], source["comparator_expected_points"],
                 source["comparator_actual_points"], source["realized_delta"],
                 canonical_json(payload["metrics"]), canonical_json(payload["findings"]),
                 payload["artifact_path"], payload["artifact_sha256"], payload["created_at"]),
            )
            con.execute(
                """INSERT INTO review_player_outcomes
                SELECT ?,scenario,element,player_name,role,is_captain,expected_points,p60,
                actual_points,minutes,effective_points FROM review_player_outcomes
                WHERE review_id=?""", (payload["review_id"], source["review_id"]),
            )
            for proposal in payload["proposals"]:
                con.execute(
                    """INSERT INTO change_proposals(
                    proposal_id,review_id,category,change_level,priority,title,hypothesis,
                    evidence_json,acceptance_json,status,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (proposal["proposal_id"], payload["review_id"], proposal["category"],
                     proposal["change_level"], proposal["priority"], proposal["title"],
                     proposal["hypothesis"], canonical_json(proposal["evidence"]),
                     canonical_json(proposal["acceptance"]), proposal["status"],
                     payload["created_at"]),
                )
            self.append_audit(
                "causal_review_recorded", actor=payload["actor"],
                correlation_id=payload["correlation_id"], cycle_id=source["cycle_id"],
                job_id=payload["job_id"], subject_type="gameweek_review",
                subject_id=payload["review_id"], payload={
                    "reason": payload["reason"], "findings": len(payload["findings"]),
                    "proposals": len(payload["proposals"]),
                    "single_gw_optimization_forbidden": True,
                }, con=con,
            )
        return {"review_id": payload["review_id"], "reused": False}

    def transition_budget_overrun(self, reservation_id: str, *, to_status: str,
                                  action: str, followup_reservation_id: str | None,
                                  actor: str, reason: str,
                                  idempotency_key: str) -> dict:
        """Revisa un overrun real sin cambiar límites ni liberar presupuesto."""
        if not all(str(value).strip() for value in (
            reservation_id, to_status, action, actor, reason, idempotency_key,
        )):
            raise ValueError("campos obligatorios de revisión de overrun vacíos")
        allowed_actions = {
            "reviewed": {"optimize_prompt", "reduce_scope", "adjust_limit"},
            "resolved": {"verified_followup"},
            "waived": {"accept_variance"},
        }
        if action not in allowed_actions.get(to_status, set()):
            raise ValueError("action incompatible con to_status")
        now = utcnow()
        with self.transaction() as con:
            existing = con.execute(
                "SELECT * FROM agent_budget_overrun_events WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                if (existing["reservation_id"] != reservation_id
                        or existing["to_status"] != to_status
                        or existing["action"] != action
                        or existing["followup_reservation_id"] != followup_reservation_id
                        or existing["actor"] != actor or existing["reason"] != reason):
                    raise ValueError("idempotency_key ya usada con otro contenido")
                return {
                    "status": "reused", "event_id": existing["event_id"],
                    "reservation_id": existing["reservation_id"],
                    "sequence": int(existing["sequence"]),
                    "from_status": existing["from_status"],
                    "to_status": existing["to_status"], "action": existing["action"],
                    "followup_reservation_id": existing["followup_reservation_id"],
                    "actual_tokens": int(existing["actual_tokens"]),
                    "job_limit": int(existing["job_limit"]),
                    "excess_tokens": int(existing["excess_tokens"]),
                    "evidence_sha256": existing["evidence_sha256"],
                    "runtime_mutated": False,
                }
            reservation = con.execute(
                "SELECT * FROM agent_budget_reservations WHERE reservation_id=?",
                (reservation_id,),
            ).fetchone()
            if not reservation:
                raise ValueError("reservation_id no existe")
            policy = json.loads(reservation["policy_json"])
            actual = int(reservation["actual_tokens"] or 0)
            job_limit = int(policy.get("job_tokens") or 0)
            if reservation["status"] != "settled" or actual <= job_limit:
                raise ValueError("reservation_id no corresponde a un overrun settled")
            latest = con.execute(
                "SELECT * FROM agent_budget_overrun_events WHERE reservation_id=? "
                "ORDER BY sequence DESC LIMIT 1", (reservation_id,),
            ).fetchone()
            current = str(latest["to_status"]) if latest else "open"
            transitions = {
                "open": {"reviewed", "waived"},
                "reviewed": {"resolved", "waived"},
            }
            if to_status not in transitions.get(current, set()):
                raise ValueError(f"transición de overrun inválida: {current} -> {to_status}")
            followup = None
            if to_status == "resolved":
                if not followup_reservation_id or followup_reservation_id == reservation_id:
                    raise ValueError("resolved exige followup_reservation_id distinto")
                followup = con.execute(
                    "SELECT * FROM agent_budget_reservations WHERE reservation_id=?",
                    (followup_reservation_id,),
                ).fetchone()
                if not followup:
                    raise ValueError("followup_reservation_id no existe")
                followup_policy = json.loads(followup["policy_json"])
                followup_actual = int(followup["actual_tokens"] or 0)
                followup_limit = int(followup_policy.get("job_tokens") or 0)
                if (followup["status"] != "settled"
                        or followup["subject_type"] != reservation["subject_type"]
                        or followup["provider"] != reservation["provider"]
                        or followup["created_at"] < reservation["created_at"]
                        or followup_actual > followup_limit):
                    raise ValueError("followup no prueba un run posterior equivalente dentro de límite")
            elif followup_reservation_id:
                raise ValueError("followup_reservation_id sólo aplica a resolved")
            evidence = {
                "schema": "mova-agent-budget-overrun-evidence-v1",
                "reservation": {
                    "reservation_id": reservation_id,
                    "cycle_id": reservation["cycle_id"],
                    "subject_type": reservation["subject_type"],
                    "subject_id": reservation["subject_id"],
                    "provider": reservation["provider"],
                    "actual_tokens": actual,
                    "job_limit": job_limit,
                    "excess_tokens": actual - job_limit,
                },
                "transition": {"from_status": current, "to_status": to_status,
                               "action": action},
                "followup": ({
                    "reservation_id": followup["reservation_id"],
                    "subject_id": followup["subject_id"],
                    "actual_tokens": int(followup["actual_tokens"]),
                    "job_limit": int(json.loads(followup["policy_json"])["job_tokens"]),
                } if followup else None),
            }
            evidence_sha = sha256_json(evidence)
            sequence = int(latest["sequence"] or 0) + 1 if latest else 1
            event_id = "budgetoverrun_" + hashlib.sha256(
                f"{reservation_id}:{idempotency_key}".encode("utf-8")
            ).hexdigest()[:24]
            con.execute(
                """INSERT INTO agent_budget_overrun_events(
                event_id,reservation_id,sequence,from_status,to_status,action,
                followup_reservation_id,actual_tokens,job_limit,excess_tokens,
                evidence_json,evidence_sha256,idempotency_key,actor,reason,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (event_id, reservation_id, sequence, current, to_status, action,
                 followup_reservation_id, actual, job_limit, actual - job_limit,
                 canonical_json(evidence), evidence_sha, idempotency_key, actor, reason, now),
            )
            self.append_audit(
                "agent_budget_overrun_transitioned", actor=actor,
                severity="warning" if to_status == "waived" else "info",
                cycle_id=reservation["cycle_id"], subject_type="budget_reservation",
                subject_id=reservation_id, payload={
                    "event_id": event_id, "from_status": current,
                    "to_status": to_status, "action": action,
                    "evidence_sha256": evidence_sha, "reason": reason,
                    "runtime_mutated": False,
                }, con=con,
            )
        return {
            "status": "completed", "event_id": event_id,
            "reservation_id": reservation_id, "sequence": sequence,
            "from_status": current, "to_status": to_status, "action": action,
            "followup_reservation_id": followup_reservation_id,
            "actual_tokens": actual, "job_limit": job_limit,
            "excess_tokens": actual - job_limit,
            "evidence_sha256": evidence_sha, "runtime_mutated": False,
        }

    def cost_report(self, policy: dict, *, season: str | None = None,
                    gw: int | None = None, month: str | None = None) -> dict:
        """Uso real + reservas activas contra límites configurados."""
        observed_month = month or utcnow()[:7]
        try:
            parsed_month = datetime.strptime(observed_month, "%Y-%m").strftime("%Y-%m")
        except ValueError as exc:
            raise ValueError("month debe usar YYYY-MM") from exc
        if parsed_month != observed_month:
            raise ValueError("month debe usar YYYY-MM")
        with self.connect(readonly=True) as con:
            cycle = None
            if gw is not None:
                cycle = con.execute(
                    "SELECT cycle_id,season,gw,deadline_at FROM gameweek_cycles "
                    "WHERE season=? AND gw=?", (season or "2026-27", int(gw)),
                ).fetchone()
            elif season is not None:
                cycle = con.execute(
                    "SELECT cycle_id,season,gw,deadline_at FROM gameweek_cycles "
                    "WHERE season=? ORDER BY deadline_at DESC LIMIT 1", (season,),
                ).fetchone()
            else:
                cycle = con.execute(
                    "SELECT cycle_id,season,gw,deadline_at FROM gameweek_cycles "
                    "ORDER BY deadline_at DESC LIMIT 1"
                ).fetchone()
            cycle_id = cycle["cycle_id"] if cycle else None
            if cycle_id:
                gw_accounting = self._agent_budget_aggregates(con, cycle_id=cycle_id)
            else:
                empty = {"uses": 0, "tokens": 0, "estimated_tokens": 0,
                         "estimated_uses": 0}
                gw_accounting = {"settled": empty, "reserved": empty,
                                 "charged": empty, "estimated_cost_usd": None}
            month_accounting = self._agent_budget_aggregates(con, month=observed_month)
            gw_semantic_reuses = int(con.execute(
                "SELECT COUNT(*) FROM decision_deliberation_bindings b "
                "JOIN decision_deliberations d ON d.deliberation_id=b.deliberation_id "
                "WHERE d.cycle_id=? AND b.binding_type='semantic_reuse'",
                (cycle_id,),
            ).fetchone()[0]) if cycle_id else 0
            month_semantic_reuses = int(con.execute(
                "SELECT COUNT(*) FROM decision_deliberation_bindings "
                "WHERE binding_type='semantic_reuse' AND substr(created_at,1,7)=?",
                (observed_month,),
            ).fetchone()[0])
            orphan_predicate = """r.status='reserved' AND (
              (r.subject_type='research' AND NOT EXISTS (
                SELECT 1 FROM research_runs x WHERE x.research_run_id=r.subject_id
                AND x.status='queued'))
              OR (r.subject_type='deliberation' AND NOT EXISTS (
                SELECT 1 FROM decision_deliberations x WHERE x.deliberation_id=r.subject_id
                AND x.status='queued'))
            )"""
            gw_orphans = con.execute(
                f"""SELECT COUNT(*) uses,COALESCE(SUM(r.reserved_tokens),0) tokens
                FROM agent_budget_reservations r WHERE r.cycle_id=?
                AND {orphan_predicate}""", (cycle_id,),
            ).fetchone() if cycle_id else {"uses": 0, "tokens": 0}
            month_orphans = con.execute(
                f"""SELECT COUNT(*) uses,COALESCE(SUM(r.reserved_tokens),0) tokens
                FROM agent_budget_reservations r WHERE substr(r.created_at,1,7)=?
                AND {orphan_predicate}""", (observed_month,),
            ).fetchone()
            by_category = con.execute(
                """WITH physical(category,uses,tokens,estimated_cost_usd) AS (
                  SELECT COALESCE(c.category,'unknown'),
                    COALESCE(r.attempt_count,1),
                    COALESCE(r.actual_tokens,
                      COALESCE(c.input_tokens,0)+COALESCE(c.output_tokens,0)),
                    c.estimated_cost_usd
                  FROM cost_ledger c
                  LEFT JOIN agent_budget_reservations r
                    ON r.subject_id=c.subject_id AND r.status='settled'
                  WHERE substr(c.occurred_at,1,7)=?
                  UNION ALL
                  SELECT CASE r.subject_type WHEN 'research' THEN 'news_research'
                    WHEN 'deliberation' THEN 'strategy_critic' ELSE 'unknown' END,
                    COALESCE(r.attempt_count,1),
                    COALESCE(r.actual_tokens,r.reserved_tokens),NULL
                  FROM agent_budget_reservations r
                  WHERE substr(r.created_at,1,7)=? AND r.status='charged'
                ) SELECT category,COALESCE(SUM(uses),0) uses,
                  COALESCE(SUM(tokens),0) tokens,SUM(estimated_cost_usd) estimated_cost_usd
                FROM physical GROUP BY category ORDER BY category""",
                (observed_month, observed_month),
            ).fetchall()
            latest = con.execute(
                "SELECT * FROM agent_budget_reservations ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
            overrun_rows = con.execute(
                """SELECT r.reservation_id,r.cycle_id,r.subject_type,r.subject_id,
                r.provider,r.actual_tokens,r.created_at,
                CAST(json_extract(r.policy_json,'$.job_tokens') AS INTEGER) job_limit,
                r.actual_tokens-CAST(json_extract(r.policy_json,'$.job_tokens') AS INTEGER)
                  excess_tokens,
                COALESCE((SELECT e.to_status FROM agent_budget_overrun_events e
                  WHERE e.reservation_id=r.reservation_id ORDER BY e.sequence DESC LIMIT 1),
                  'open') review_status,
                (SELECT e.action FROM agent_budget_overrun_events e
                  WHERE e.reservation_id=r.reservation_id ORDER BY e.sequence DESC LIMIT 1)
                  review_action,
                (SELECT e.created_at FROM agent_budget_overrun_events e
                  WHERE e.reservation_id=r.reservation_id ORDER BY e.sequence DESC LIMIT 1)
                  reviewed_at
                FROM agent_budget_reservations r
                WHERE r.status='settled'
                  AND r.actual_tokens>CAST(json_extract(r.policy_json,'$.job_tokens') AS INTEGER)
                  AND (r.cycle_id=? OR substr(r.created_at,1,7)=?)
                ORDER BY r.created_at DESC""",
                (cycle_id, observed_month),
            ).fetchall()

        def scope(accounting, *, token_limit: int,
                  use_limit: int) -> dict:
            consumed = accounting["settled"]
            reserved = accounting["reserved"]
            charged = accounting["charged"]
            tokens = (int(consumed["tokens"]) + int(reserved["tokens"])
                      + int(charged["tokens"]))
            uses = (int(consumed["uses"]) + int(reserved["uses"])
                    + int(charged["uses"]))
            return {
                "consumed_tokens": int(consumed["tokens"]),
                "reserved_tokens": int(reserved["tokens"]), "committed_tokens": tokens,
                "charged_tokens": int(charged["tokens"]),
                "charged_estimate_tokens": int(charged["estimated_tokens"]),
                "token_limit": token_limit, "remaining_tokens": max(0, token_limit - tokens),
                "consumed_uses": int(consumed["uses"]),
                "reserved_uses": int(reserved["uses"]), "committed_uses": uses,
                "charged_uses": int(charged["uses"]),
                "charged_estimate_uses": int(charged["estimated_uses"]),
                "use_limit": use_limit, "remaining_uses": max(0, use_limit - uses),
                "status": "within_budget" if tokens <= token_limit and uses <= use_limit
                else "exceeded",
                "estimated_cost_usd": accounting["estimated_cost_usd"],
            }

        overrun_items = [dict(row) for row in overrun_rows]

        def overrun_scope(rows: list[dict]) -> dict:
            states = {name: sum(row["review_status"] == name for row in rows)
                      for name in ("open", "reviewed", "resolved", "waived")}
            if states["open"]:
                status = "unreviewed"
            elif states["reviewed"]:
                status = "reviewed_pending"
            elif rows:
                status = "closed"
            else:
                status = "none"
            return {
                "status": status, "uses": len(rows),
                "excess_tokens": sum(int(row["excess_tokens"]) for row in rows),
                "max_actual_tokens": max(
                    (int(row["actual_tokens"]) for row in rows), default=0
                ),
                "states": states,
            }

        gw_overrun_state = overrun_scope([
            row for row in overrun_items if row["cycle_id"] == cycle_id
        ])
        month_overrun_state = overrun_scope([
            row for row in overrun_items if str(row["created_at"])[:7] == observed_month
        ])
        active_overrun = any(
            item["status"] in {"unreviewed", "reviewed_pending"}
            for item in (gw_overrun_state, month_overrun_state)
        )
        if int(gw_orphans["uses"]) or int(month_orphans["uses"]):
            report_status = "orphaned_reservation_observed"
        elif active_overrun:
            report_status = "job_overrun_observed"
        else:
            report_status = "within_budget"
        return {
            "schema": "mova-agent-cost-report-v1", "observed_at": utcnow(),
            "status": report_status,
            "policy": dict(policy), "cycle": dict(cycle) if cycle else None,
            "gameweek": scope(gw_accounting,
                              token_limit=policy["gw_tokens"], use_limit=policy["gw_uses"]),
            "month": {"month": observed_month, **scope(
                month_accounting,
                token_limit=policy["month_tokens"],
                use_limit=policy["month_uses"])},
            "job_overruns": {
                "status": ("unreviewed" if any(
                    item["status"] == "unreviewed"
                    for item in (gw_overrun_state, month_overrun_state)
                ) else "reviewed_pending" if active_overrun else
                    "closed" if overrun_items else "none"),
                "gameweek": gw_overrun_state,
                "month": {"month": observed_month, **month_overrun_state},
                "items": overrun_items[:20],
            },
            "orphaned_reservations": {
                "status": ("observed" if int(gw_orphans["uses"])
                           or int(month_orphans["uses"]) else "none"),
                "gameweek": dict(gw_orphans),
                "month": {"month": observed_month, **dict(month_orphans)},
            },
            "semantic_reuse": {
                "gameweek_avoided_uses": gw_semantic_reuses,
                "month_avoided_uses": month_semantic_reuses,
            },
            "by_category": [dict(row) for row in by_category],
            "latest_reservations": [dict(row) for row in latest],
        }

    def cost_prometheus(self, policy: dict, *, season: str) -> str:
        report = self.cost_report(policy, season=season)
        lines = [
            "# HELP mova_agent_budget_tokens Tokens consumed, reserved or limited.",
            "# TYPE mova_agent_budget_tokens gauge",
            "# HELP mova_agent_budget_uses Calls consumed, reserved or limited.",
            "# TYPE mova_agent_budget_uses gauge",
            "# HELP mova_agent_budget_within_limit Whether the scope is within budget.",
            "# TYPE mova_agent_budget_within_limit gauge",
            "# HELP mova_agent_budget_job_overruns Jobs whose actual tokens exceeded policy.",
            "# TYPE mova_agent_budget_job_overruns gauge",
            "# HELP mova_agent_budget_job_overrun_tokens Tokens above per-job policy.",
            "# TYPE mova_agent_budget_job_overrun_tokens gauge",
            "# HELP mova_agent_budget_overrun_reviews Overrun lifecycle by review state.",
            "# TYPE mova_agent_budget_overrun_reviews gauge",
            "# HELP mova_agent_budget_orphaned_reservations Reserved budgets without queued jobs.",
            "# TYPE mova_agent_budget_orphaned_reservations gauge",
            "# HELP mova_agent_deliberation_semantic_reuses Agent calls avoided by semantic idempotency.",
            "# TYPE mova_agent_deliberation_semantic_reuses counter",
        ]
        for scope_name, scope in (("gameweek", report["gameweek"]),
                                  ("month", report["month"])):
            for kind in ("consumed", "reserved", "charged", "charged_estimate",
                         "remaining"):
                lines.append(
                    f'mova_agent_budget_tokens{{scope="{scope_name}",kind="{kind}"}} '
                    f'{scope[f"{kind}_tokens"]}'
                )
                lines.append(
                    f'mova_agent_budget_uses{{scope="{scope_name}",kind="{kind}"}} '
                    f'{scope[f"{kind}_uses"]}'
                )
            lines.append(
                f'mova_agent_budget_tokens{{scope="{scope_name}",kind="limit"}} '
                f'{scope["token_limit"]}'
            )
            lines.append(
                f'mova_agent_budget_uses{{scope="{scope_name}",kind="limit"}} '
                f'{scope["use_limit"]}'
            )
            lines.append(
                f'mova_agent_budget_within_limit{{scope="{scope_name}"}} '
                f'{1 if scope["status"] == "within_budget" else 0}'
            )
            overrun = report["job_overruns"][scope_name]
            lines.append(
                f'mova_agent_budget_job_overruns{{scope="{scope_name}"}} '
                f'{overrun["uses"]}'
            )
            lines.append(
                f'mova_agent_budget_job_overrun_tokens{{scope="{scope_name}"}} '
                f'{overrun["excess_tokens"]}'
            )
            for state in ("open", "reviewed", "resolved", "waived"):
                lines.append(
                    f'mova_agent_budget_overrun_reviews{{scope="{scope_name}",'
                    f'status="{state}"}} {overrun["states"][state]}'
                )
            lines.append(
                f'mova_agent_budget_orphaned_reservations{{scope="{scope_name}"}} '
                f'{report["orphaned_reservations"][scope_name]["uses"]}'
            )
            avoided_key = f"{scope_name}_avoided_uses"
            lines.append(
                f'mova_agent_deliberation_semantic_reuses{{scope="{scope_name}"}} '
                f'{report["semantic_reuse"][avoided_key]}'
            )
        return "\n".join(lines) + "\n"

    def improvement_status(self, *, season: str | None = None,
                           gw: int | None = None) -> dict:
        """Memoria de mejora y gasto LLM, sin mutar configuración productiva."""
        filters: list[str] = []
        params: list[object] = []
        if season is not None:
            filters.append("c.season=?")
            params.append(season)
        if gw is not None:
            filters.append("c.gw=?")
            params.append(int(gw))
        where = ("WHERE " + " AND ".join(filters)) if filters else ""
        with self.connect(readonly=True) as con:
            proposals = con.execute(
                f"""SELECT p.*,c.season,c.gw,r.causality_status
                FROM change_proposals p
                JOIN gameweek_reviews r ON r.review_id=p.review_id
                JOIN gameweek_settlements s ON s.settlement_id=r.settlement_id
                JOIN gameweek_cycles c ON c.cycle_id=s.cycle_id
                {where} ORDER BY c.gw DESC,p.priority,p.created_at""", params,
            ).fetchall()
            lessons = con.execute(
                f"""SELECT l.*,c.season,c.gw
                FROM lessons l
                JOIN gameweek_reviews r ON r.review_id=l.review_id
                JOIN gameweek_settlements s ON s.settlement_id=r.settlement_id
                JOIN gameweek_cycles c ON c.cycle_id=s.cycle_id
                {where} ORDER BY l.created_at DESC""", params,
            ).fetchall()
            evaluations = con.execute(
                f"""SELECT e.* FROM change_proposal_evaluations e
                JOIN change_proposals p ON p.proposal_id=e.proposal_id
                JOIN gameweek_reviews r ON r.review_id=p.review_id
                JOIN gameweek_settlements s ON s.settlement_id=r.settlement_id
                JOIN gameweek_cycles c ON c.cycle_id=s.cycle_id
                {where} ORDER BY e.created_at DESC LIMIT 100""", params,
            ).fetchall()
            costs = con.execute(
                """SELECT provider,model,COUNT(*) uses,
                COALESCE(SUM(input_tokens),0) input_tokens,
                COALESCE(SUM(output_tokens),0) output_tokens,
                SUM(estimated_cost_usd) estimated_cost_usd,
                SUM(subscription_usage) subscription_uses
                FROM cost_ledger GROUP BY provider,model ORDER BY provider,model"""
            ).fetchall()
            cost_months = con.execute(
                """SELECT substr(occurred_at,1,7) month,COUNT(*) uses,
                COALESCE(SUM(input_tokens),0) input_tokens,
                COALESCE(SUM(output_tokens),0) output_tokens,
                SUM(estimated_cost_usd) estimated_cost_usd,
                SUM(subscription_usage) subscription_uses
                FROM cost_ledger GROUP BY substr(occurred_at,1,7) ORDER BY month DESC"""
            ).fetchall()
            releases = con.execute(
                "SELECT * FROM model_bundle_releases ORDER BY created_at DESC"
            ).fetchall()
            release_events = con.execute(
                "SELECT * FROM model_bundle_release_events "
                "ORDER BY occurred_at DESC,sequence DESC LIMIT 100"
            ).fetchall()
            active_bundle = con.execute(
                """SELECT value_json,effective_at,actor,reason FROM runtime_controls
                WHERE control_key='active_model_bundle'
                ORDER BY effective_at DESC,control_id DESC LIMIT 1"""
            ).fetchone()
        proposal_rows = []
        for row in proposals:
            item = dict(row)
            item["evidence"] = json.loads(item.pop("evidence_json"))
            item["acceptance"] = json.loads(item.pop("acceptance_json"))
            proposal_rows.append(item)
        lesson_rows = []
        for row in lessons:
            item = dict(row)
            item["evidence"] = json.loads(item.pop("evidence_json"))
            lesson_rows.append(item)
        evaluation_rows = []
        for row in evaluations:
            item = dict(row)
            item["evidence"] = json.loads(item.pop("evidence_json"))
            evaluation_rows.append(item)
        total_uses = sum(int(row["uses"]) for row in costs)
        known_costs = [float(row["estimated_cost_usd"])
                       for row in costs if row["estimated_cost_usd"] is not None]
        totals = {
            "uses": total_uses,
            "input_tokens": sum(int(row["input_tokens"]) for row in costs),
            "output_tokens": sum(int(row["output_tokens"]) for row in costs),
            "subscription_uses": sum(int(row["subscription_uses"]) for row in costs),
            "estimated_cost_usd": (round(sum(known_costs), 6) if known_costs
                                   else (0.0 if total_uses == 0 else None)),
            "unknown_cost_uses": sum(int(row["uses"])
                                     for row in costs if row["estimated_cost_usd"] is None),
        }
        release_rows = [self._release_row(row) for row in releases]
        release_event_rows = []
        for row in release_events:
            item = dict(row)
            item["evidence"] = json.loads(item.pop("evidence_json"))
            release_event_rows.append(item)
        return {
            "schema": "mova-continuous-improvement-status-v1",
            "filters": {"season": season, "gw": gw},
            "proposal_counts": {
                status: sum(item["status"] == status for item in proposal_rows)
                for status in ("proposed", "testing", "accepted", "rejected")
            },
            "proposals": proposal_rows, "evaluations": evaluation_rows,
            "lessons": lesson_rows,
            "model_bundle_releases": release_rows,
            "model_bundle_release_events": release_event_rows,
            "active_model_bundle": ({"value": json.loads(active_bundle["value_json"]),
                                     "effective_at": active_bundle["effective_at"],
                                     "actor": active_bundle["actor"],
                                     "reason": active_bundle["reason"]}
                                    if active_bundle else None),
            "costs": {"scope": "all_time", "totals": totals,
                      "by_provider_model": [dict(row) for row in costs],
                      "by_month": [dict(row) for row in cost_months]},
            "runtime_mutated": active_bundle is not None,
        }

    def transition_change_proposal(self, proposal_id: str, *, to_status: str,
                                   evidence: dict, actor: str, reason: str,
                                   idempotency_key: str) -> dict:
        """Registra evaluación; aceptar crea memoria, nunca aplica el cambio propuesto."""
        transitions = {"proposed": {"testing", "rejected"},
                       "testing": {"accepted", "rejected"}}
        evidence_sha = sha256_json(evidence)
        now = utcnow()
        with self.transaction() as con:
            reused = con.execute(
                "SELECT * FROM change_proposal_evaluations WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if reused:
                if (reused["proposal_id"] != proposal_id or reused["to_status"] != to_status
                        or reused["evidence_sha256"] != evidence_sha):
                    raise ValueError("idempotency_key ya usada con otro contenido")
                return {"status": "reused", "proposal_id": proposal_id,
                        "evaluation_id": reused["evaluation_id"],
                        "proposal_status": reused["to_status"], "runtime_mutated": False}
            proposal = con.execute(
                "SELECT * FROM change_proposals WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
            if not proposal:
                raise ValueError("proposal_id no existe")
            current = str(proposal["status"])
            if to_status not in transitions.get(current, set()):
                raise ValueError(f"transición inválida: {current} -> {to_status}")
            evaluation_id = new_id("evaluation")
            con.execute(
                """INSERT INTO change_proposal_evaluations(
                evaluation_id,proposal_id,idempotency_key,from_status,to_status,
                evidence_json,evidence_sha256,actor,reason,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (evaluation_id, proposal_id, idempotency_key, current, to_status,
                 canonical_json(evidence), evidence_sha, actor, reason, now),
            )
            con.execute("UPDATE change_proposals SET status=? WHERE proposal_id=?",
                        (to_status, proposal_id))
            lesson_id = None
            if to_status == "accepted":
                lesson_id = "lesson_" + hashlib.sha256(
                    proposal_id.encode("utf-8")
                ).hexdigest()[:24]
                con.execute(
                    """INSERT INTO lessons(lesson_id,proposal_id,review_id,category,
                    statement,evidence_json,status,created_at)
                    VALUES(?,?,?,?,?,?,'validated',?)""",
                    (lesson_id, proposal_id, proposal["review_id"], proposal["category"],
                     proposal["hypothesis"], canonical_json(evidence), now),
                )
            self.append_audit(
                "change_proposal_evaluated", actor=actor,
                severity="warning" if to_status == "accepted" else "info",
                subject_type="change_proposal", subject_id=proposal_id,
                payload={"from_status": current, "to_status": to_status,
                         "evaluation_id": evaluation_id, "lesson_id": lesson_id,
                         "reason": reason, "runtime_mutated": False}, con=con,
            )
        return {"status": "completed", "proposal_id": proposal_id,
                "evaluation_id": evaluation_id, "proposal_status": to_status,
                "lesson_id": lesson_id, "runtime_mutated": False}

    @staticmethod
    def _release_row(row) -> dict | None:
        if not row:
            return None
        item = dict(row)
        for source, target in (
            ("candidate_manifest_json", "candidate_manifest"),
            ("baseline_manifest_json", "baseline_manifest"),
            ("promotion_policy_json", "promotion_policy"),
        ):
            item[target] = json.loads(item.pop(source))
        return item

    def model_bundle_release_status(self) -> dict:
        self.migrate()
        with self.connect(readonly=True) as con:
            releases = con.execute(
                "SELECT * FROM model_bundle_releases ORDER BY created_at DESC"
            ).fetchall()
            events = con.execute(
                "SELECT * FROM model_bundle_release_events "
                "ORDER BY occurred_at DESC,sequence DESC LIMIT 100"
            ).fetchall()
            control = con.execute(
                """SELECT value_json,effective_at,actor,reason FROM runtime_controls
                WHERE control_key='active_model_bundle'
                ORDER BY effective_at DESC,control_id DESC LIMIT 1"""
            ).fetchone()
        event_items = []
        for row in events:
            item = dict(row)
            item["evidence"] = json.loads(item.pop("evidence_json"))
            event_items.append(item)
        return {
            "schema": "mova-model-bundle-release-status-v1",
            "releases": [self._release_row(row) for row in releases],
            "events": event_items,
            "active_model_bundle": ({"value": json.loads(control["value_json"]),
                                     "effective_at": control["effective_at"],
                                     "actor": control["actor"],
                                     "reason": control["reason"]} if control else None),
        }

    def model_release_prometheus(self) -> str:
        with self.connect(readonly=True) as con:
            rows = con.execute(
                "SELECT status,COUNT(*) count FROM model_bundle_releases GROUP BY status"
            ).fetchall()
            events = int(con.execute(
                "SELECT COUNT(*) FROM model_bundle_release_events"
            ).fetchone()[0])
            pointer = con.execute(
                "SELECT 1 FROM runtime_controls WHERE control_key='active_model_bundle' LIMIT 1"
            ).fetchone()
        counts = {str(row["status"]): int(row["count"]) for row in rows}
        lines = [
            f'mova_model_bundle_releases{{status="{status}"}} {counts.get(status, 0)}'
            for status in ("prepared", "shadow", "promoted", "superseded", "rolled_back")
        ]
        lines.extend((f"mova_model_bundle_release_events_total {events}",
                      f"mova_model_bundle_pointer_present {1 if pointer else 0}"))
        return "\n".join(lines) + "\n"

    def active_model_bundle(self) -> dict | None:
        self.migrate()
        with self.connect(readonly=True) as con:
            row = con.execute(
                """SELECT value_json FROM runtime_controls
                WHERE control_key='active_model_bundle'
                ORDER BY effective_at DESC,control_id DESC LIMIT 1"""
            ).fetchone()
        return json.loads(row["value_json"]) if row else None

    def shadow_model_bundle_release(self) -> dict | None:
        self.migrate()
        with self.connect(readonly=True) as con:
            row = con.execute(
                "SELECT * FROM model_bundle_releases WHERE status='shadow' "
                "ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
        return self._release_row(row)

    @staticmethod
    def _insert_release_event(con, *, release_id: str, idempotency_key: str,
                              from_status: str | None, to_status: str, actor: str,
                              reason: str, evidence: dict, occurred_at: str) -> str:
        sequence = int(con.execute(
            "SELECT COALESCE(MAX(sequence),0)+1 FROM model_bundle_release_events "
            "WHERE release_id=?", (release_id,)
        ).fetchone()[0])
        event_id = new_id("release_event")
        con.execute(
            """INSERT INTO model_bundle_release_events(
            release_event_id,release_id,sequence,idempotency_key,from_status,to_status,
            actor,reason,evidence_json,evidence_sha256,occurred_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (event_id, release_id, sequence, idempotency_key, from_status, to_status,
             actor, reason, canonical_json(evidence), sha256_json(evidence), occurred_at),
        )
        return event_id

    def prepare_model_bundle_release(self, *, proposal_id: str, candidate: dict,
                                     baseline: dict, promotion_policy: dict,
                                     actor: str, reason: str,
                                     idempotency_key: str) -> dict:
        content = {"proposal_id": proposal_id, "candidate": candidate,
                   "baseline": baseline, "promotion_policy": promotion_policy}
        content_sha = sha256_json(content)
        now = utcnow()
        with self.transaction() as con:
            reused = con.execute(
                "SELECT * FROM model_bundle_releases WHERE prepare_idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if reused:
                if reused["content_sha256"] != content_sha:
                    raise ValueError("idempotency_key ya usada con otro release")
                item = self._release_row(reused)
                return {"status": "reused", "release": item, "runtime_mutated": False}
            proposal = con.execute(
                """SELECT p.status,l.status lesson_status FROM change_proposals p
                LEFT JOIN lessons l ON l.proposal_id=p.proposal_id
                WHERE p.proposal_id=?""", (proposal_id,),
            ).fetchone()
            if not proposal:
                raise ValueError("proposal_id no existe")
            if proposal["status"] != "accepted" or proposal["lesson_status"] != "validated":
                raise ValueError("la propuesta requiere aceptación y lección validada")
            prior = con.execute(
                "SELECT release_id FROM model_bundle_releases WHERE proposal_id=?",
                (proposal_id,),
            ).fetchone()
            if prior:
                raise ValueError("la propuesta ya tiene un release")
            for status, manifest in (("approved", baseline), ("candidate", candidate)):
                for name, model in manifest["models"].items():
                    existing = con.execute(
                        "SELECT * FROM model_releases WHERE model_name=? AND version=?",
                        (name, model["version"]),
                    ).fetchone()
                    if existing:
                        if (existing["artifact_sha256"] != model["artifact_sha256"]
                                or existing["artifact_path"] != model["artifact_path"]):
                            raise ValueError(f"release inmutable en conflicto: {name}")
                        continue
                    model_id = "model_" + hashlib.sha256(
                        f"{name}:{model['version']}:{model['artifact_sha256']}".encode()
                    ).hexdigest()[:24]
                    con.execute(
                        """INSERT INTO model_releases(model_release_id,model_name,version,
                        dataset_id,artifact_path,artifact_sha256,metrics_json,status,created_at)
                        VALUES(?,?,?,NULL,?,?,?,?,?)""",
                        (model_id, name, model["version"], model["artifact_path"],
                         model["artifact_sha256"], canonical_json(model.get("metrics") or {}),
                         status, now),
                    )
            release_id = "release_" + hashlib.sha256(
                f"{proposal_id}:{content_sha}".encode()
            ).hexdigest()[:24]
            con.execute(
                """INSERT INTO model_bundle_releases(
                release_id,proposal_id,prepare_idempotency_key,candidate_manifest_json,
                baseline_manifest_json,promotion_policy_json,status,content_sha256,
                created_at,updated_at) VALUES(?,?,?,?,?,?,'prepared',?,?,?)""",
                (release_id, proposal_id, idempotency_key, canonical_json(candidate),
                 canonical_json(baseline), canonical_json(promotion_policy), content_sha,
                 now, now),
            )
            event_id = self._insert_release_event(
                con, release_id=release_id, idempotency_key=idempotency_key,
                from_status=None, to_status="prepared", actor=actor, reason=reason,
                evidence={"content_sha256": content_sha}, occurred_at=now,
            )
            self.append_audit(
                "model_bundle_release_prepared", actor=actor, severity="warning",
                subject_type="model_bundle_release", subject_id=release_id,
                payload={"proposal_id": proposal_id, "event_id": event_id,
                         "content_sha256": content_sha, "runtime_mutated": False,
                         "reason": reason}, con=con,
            )
        return {"status": "completed", "release_id": release_id,
                "release_status": "prepared", "event_id": event_id,
                "runtime_mutated": False}

    def transition_model_bundle_release(self, release_id: str, *, to_status: str,
                                        evidence: dict, actor: str, reason: str,
                                        idempotency_key: str) -> dict:
        transitions = {"prepared": {"shadow", "rolled_back"},
                       "shadow": {"promoted", "rolled_back"},
                       "promoted": {"rolled_back"}}
        evidence_sha = sha256_json(evidence)
        now = utcnow()
        with self.transaction() as con:
            reused = con.execute(
                "SELECT * FROM model_bundle_release_events WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if reused:
                if (reused["release_id"] != release_id or reused["to_status"] != to_status
                        or reused["evidence_sha256"] != evidence_sha):
                    raise ValueError("idempotency_key ya usada con otro contenido")
                return {"status": "reused", "release_id": release_id,
                        "release_status": reused["to_status"],
                        "event_id": reused["release_event_id"],
                        "runtime_mutated": reused["to_status"] in {"promoted", "rolled_back"}}
            row = con.execute(
                "SELECT * FROM model_bundle_releases WHERE release_id=?", (release_id,)
            ).fetchone()
            if not row:
                raise ValueError("release_id no existe")
            current = str(row["status"])
            if to_status not in transitions.get(current, set()):
                raise ValueError(f"transición inválida: {current} -> {to_status}")
            candidate = json.loads(row["candidate_manifest_json"])
            baseline = json.loads(row["baseline_manifest_json"])
            if to_status == "promoted":
                prior = con.execute(
                    "SELECT release_id FROM model_bundle_releases "
                    "WHERE status='promoted' AND release_id<>?", (release_id,)
                ).fetchone()
                if prior:
                    prior_id = str(prior["release_id"])
                    con.execute(
                        "UPDATE model_bundle_releases SET status='superseded',updated_at=? "
                        "WHERE release_id=?", (now, prior_id),
                    )
                    self._insert_release_event(
                        con, release_id=prior_id,
                        idempotency_key=f"{idempotency_key}:supersede:{prior_id}",
                        from_status="promoted", to_status="superseded", actor=actor,
                        reason=f"superseded por {release_id}",
                        evidence={"successor_release_id": release_id}, occurred_at=now,
                    )
                for name, model in baseline["models"].items():
                    con.execute(
                        "UPDATE model_releases SET status='retired' "
                        "WHERE model_name=? AND version=?", (name, model["version"]),
                    )
                for name, model in candidate["models"].items():
                    con.execute(
                        "UPDATE model_releases SET status='approved' "
                        "WHERE model_name=? AND version=?", (name, model["version"]),
                    )
                pointer = {"schema": "mova-active-model-bundle-v1",
                           "release_id": release_id, "models": candidate["models"],
                           "activated_at": now}
                con.execute(
                    "INSERT INTO runtime_controls(control_key,value_json,effective_at,actor,reason) "
                    "VALUES('active_model_bundle',?,?,?,?)",
                    (canonical_json(pointer), now, actor, reason),
                )
            elif to_status == "rolled_back" and current == "promoted":
                # Libera primero el índice de único promoted para poder restaurar
                # el release anterior dentro de la misma transacción.
                con.execute(
                    "UPDATE model_bundle_releases SET status='rolled_back',updated_at=? "
                    "WHERE release_id=?", (now, release_id),
                )
                for name, model in candidate["models"].items():
                    con.execute(
                        "UPDATE model_releases SET status='retired' "
                        "WHERE model_name=? AND version=?", (name, model["version"]),
                    )
                for name, model in baseline["models"].items():
                    con.execute(
                        "UPDATE model_releases SET status='approved' "
                        "WHERE model_name=? AND version=?", (name, model["version"]),
                    )
                baseline_release_id = baseline.get("source_release_id")
                if baseline_release_id:
                    prior = con.execute(
                        "SELECT status FROM model_bundle_releases WHERE release_id=?",
                        (baseline_release_id,),
                    ).fetchone()
                    if prior and prior["status"] == "superseded":
                        con.execute(
                            "UPDATE model_bundle_releases SET status='promoted',updated_at=? "
                            "WHERE release_id=?", (now, baseline_release_id),
                        )
                        self._insert_release_event(
                            con, release_id=baseline_release_id,
                            idempotency_key=f"{idempotency_key}:restore:{baseline_release_id}",
                            from_status="superseded", to_status="promoted", actor=actor,
                            reason=f"restaurado por rollback de {release_id}",
                            evidence={"rollback_release_id": release_id}, occurred_at=now,
                        )
                pointer = {"schema": "mova-active-model-bundle-v1",
                           "release_id": baseline_release_id, "rollback_of": release_id,
                           "models": baseline["models"], "activated_at": now}
                con.execute(
                    "INSERT INTO runtime_controls(control_key,value_json,effective_at,actor,reason) "
                    "VALUES('active_model_bundle',?,?,?,?)",
                    (canonical_json(pointer), now, actor, reason),
                )
            elif to_status == "shadow":
                for name, model in candidate["models"].items():
                    con.execute(
                        "UPDATE model_releases SET status='shadow' "
                        "WHERE model_name=? AND version=?", (name, model["version"]),
                    )
            elif to_status == "rolled_back":
                for name, model in candidate["models"].items():
                    con.execute(
                        "UPDATE model_releases SET status='retired' "
                        "WHERE model_name=? AND version=?", (name, model["version"]),
                    )
            con.execute(
                "UPDATE model_bundle_releases SET status=?,updated_at=? WHERE release_id=?",
                (to_status, now, release_id),
            )
            event_id = self._insert_release_event(
                con, release_id=release_id, idempotency_key=idempotency_key,
                from_status=current, to_status=to_status, actor=actor, reason=reason,
                evidence=evidence, occurred_at=now,
            )
            runtime_mutated = to_status == "promoted" or (
                to_status == "rolled_back" and current == "promoted"
            )
            self.append_audit(
                f"model_bundle_release_{to_status}", actor=actor, severity="warning",
                subject_type="model_bundle_release", subject_id=release_id,
                payload={"from_status": current, "to_status": to_status,
                         "event_id": event_id, "evidence_sha256": evidence_sha,
                         "runtime_mutated": runtime_mutated, "reason": reason}, con=con,
            )
        return {"status": "completed", "release_id": release_id,
                "release_status": to_status, "event_id": event_id,
                "runtime_mutated": runtime_mutated}

    def recent(self, table: str, limit: int = 50) -> list[dict]:
        allowed = {"job_runs", "job_steps", "audit_events", "incidents", "health_samples",
                   "source_snapshots", "team_state_snapshots", "decision_runs",
                   "decision_envelopes", "decision_candidates",
                   "decision_validation_checks",
                   "decision_deliberations", "decision_deliberation_bindings",
                   "decision_deliberation_risks",
                   "execution_plans", "execution_preflight_checks",
                   "execution_attempts", "execution_attempt_events",
                   "outbox_events", "chip_strategy_runs", "gameweek_settlements",
                   "gameweek_reviews", "change_proposals", "season_plans",
                   "cycle_manifests", "research_runs", "research_documents",
                   "research_signals", "research_conflicts", "cost_ledger",
                   "agent_budget_reservations", "agent_budget_overrun_events",
                   "agent_worker_attempt_events",
                   "change_proposal_evaluations", "lessons",
                   "model_bundle_releases", "model_bundle_release_events",
                   "browser_rehearsals"}
        if table not in allowed:
            raise ValueError(f"tabla no permitida: {table}")
        order = {
            "job_runs": "started_at", "job_steps": "started_at", "audit_events": "occurred_at",
            "incidents": "opened_at", "health_samples": "observed_at",
            "source_snapshots": "captured_at", "decision_runs": "created_at",
            "decision_envelopes": "created_at",
            "decision_candidates": "rowid",
            "decision_validation_checks": "created_at",
            "decision_deliberations": "queued_at",
            "decision_deliberation_bindings": "created_at",
            "decision_deliberation_risks": "created_at",
            "execution_plans": "created_at",
            "execution_preflight_checks": "created_at",
            "execution_attempts": "created_at",
            "execution_attempt_events": "occurred_at",
            "team_state_snapshots": "observed_at",
            "outbox_events": "created_at", "chip_strategy_runs": "created_at",
            "gameweek_settlements": "settled_at", "gameweek_reviews": "created_at",
            "change_proposals": "created_at",
            "season_plans": "created_at", "cycle_manifests": "created_at",
            "research_runs": "queued_at", "research_documents": "observed_at",
            "research_signals": "observed_at", "research_conflicts": "created_at",
            "cost_ledger": "occurred_at",
            "agent_budget_reservations": "created_at",
            "agent_budget_overrun_events": "created_at",
            "agent_worker_attempt_events": "occurred_at",
            "change_proposal_evaluations": "created_at", "lessons": "created_at",
            "model_bundle_releases": "created_at",
            "model_bundle_release_events": "occurred_at",
            "browser_rehearsals": "observed_at",
        }[table]
        with self.connect(readonly=True) as con:
            rows = con.execute(
                f"SELECT * FROM {table} ORDER BY {order} DESC LIMIT ?", (max(1, min(limit, 500)),)
            ).fetchall()
        payload = [dict(r) for r in rows]
        if table == "execution_attempts":
            for row in payload:
                row.pop("claim_token_sha256", None)
        return payload

    def recent_jobs_by_type(self, job_type: str, limit: int = 20) -> list[dict]:
        with self.connect(readonly=True) as con:
            rows = con.execute(
                "SELECT * FROM job_runs WHERE job_type=? ORDER BY started_at DESC LIMIT ?",
                (job_type, max(1, min(limit, 100))),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_browser_rehearsal(self, *, cycle_id: str, capability: str,
                                 contract_version: str, evidence_mode: str,
                                 status: str, checks: list[dict], evidence_path: str,
                                 evidence_sha256: str, content_sha256: str,
                                 idempotency_key: str, actor: str, reason: str,
                                 observed_at: str) -> dict:
        rehearsal_id = f"rehearsal_{content_sha256[:24]}"
        with self.transaction() as con:
            existing = con.execute(
                "SELECT * FROM browser_rehearsals WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                if existing["content_sha256"] != content_sha256:
                    raise ValueError("idempotency_key reutilizada con evidencia distinta")
                return {**dict(existing), "reused": True}
            cycle = con.execute(
                "SELECT cycle_id FROM gameweek_cycles WHERE cycle_id=?", (cycle_id,)
            ).fetchone()
            if not cycle:
                raise ValueError("cycle_id de rehearsal no existe")
            try:
                con.execute(
                    """
                    INSERT INTO browser_rehearsals(
                      rehearsal_id,cycle_id,capability,contract_version,evidence_mode,
                      status,writes_attempted,checks_json,evidence_path,evidence_sha256,
                      content_sha256,idempotency_key,actor,reason,observed_at,created_at
                    ) VALUES(?,?,?,?,?,?,0,?,?,?,?,?,?,?,?,?)
                    """,
                    (rehearsal_id, cycle_id, capability, contract_version, evidence_mode,
                     status, canonical_json(checks), evidence_path, evidence_sha256,
                     content_sha256, idempotency_key, actor, reason, observed_at, utcnow()),
                )
            except sqlite3.IntegrityError as exc:
                duplicate = con.execute(
                    "SELECT * FROM browser_rehearsals WHERE content_sha256=? OR "
                    "(cycle_id=? AND capability=? AND contract_version=? AND status='passed')",
                    (content_sha256, cycle_id, capability, contract_version),
                ).fetchone()
                if duplicate:
                    return {**dict(duplicate), "reused": True,
                            "deduplicated_by": "evidence_or_gameweek"}
                raise exc
            self.append_audit(
                "browser_rehearsal_recorded", actor=actor, cycle_id=cycle_id,
                subject_type="browser_rehearsal", subject_id=rehearsal_id,
                payload={"capability": capability, "contract_version": contract_version,
                         "status": status, "evidence_mode": evidence_mode,
                         "writes_attempted": False, "reason": reason}, con=con,
            )
            row = con.execute(
                "SELECT * FROM browser_rehearsals WHERE rehearsal_id=?", (rehearsal_id,)
            ).fetchone()
        return {**dict(row), "reused": False}

    def browser_rehearsal_summary(self, contract_versions: dict[str, str]) -> dict:
        counts = {key: 0 for key in contract_versions}
        with self.connect(readonly=True) as con:
            for capability, version in contract_versions.items():
                counts[capability] = int(con.execute(
                    "SELECT COUNT(DISTINCT cycle_id) FROM browser_rehearsals "
                    "WHERE capability=? AND contract_version=? AND status='passed' "
                    "AND writes_attempted=0", (capability, version),
                ).fetchone()[0])
        return counts

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
        research_counts = {"queued": 0, "imported": 0, "rejected": 0, "failed": 0}
        research_global_counts = {
            "queued": 0, "imported": 0, "rejected": 0, "failed": 0
        }
        research_signals = 0
        research_conflicts = 0
        research_last_import_epoch = 0.0
        research_coverage_ratio = 0.0
        research_evidence_ratio = 0.0
        research_measured_gameweeks = 0
        decision_envelope_status = "missing"
        execution_plan_status = "missing"
        execution_plan_blockers = 0
        execution_attempt_status = "missing"
        execution_attempt_counts: dict[str, int] = {}
        decision_blocking_checks = 0
        deliberation_status = "missing"
        deliberation_blocking_risks = 0
        strategic_memory_status = "missing"
        strategic_memory_counts = {"decisions": 0, "reviews": 0, "lessons": 0}
        strategic_plan_revision = 0
        browser_rehearsals = {"captaincy": 0, "lineup": 0, "r3": 0}
        postgres_cutover_status = "missing"
        postgres_cutover_rollback_verified = 0
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
            if cycle.get("cycle_id"):
                for row in con.execute(
                    "SELECT status,COUNT(*) n FROM research_runs WHERE cycle_id=? "
                    "GROUP BY status", (cycle["cycle_id"],),
                ).fetchall():
                    research_counts[str(row["status"])] = int(row["n"])
                research_signals = int(con.execute(
                    "SELECT COUNT(*) FROM research_signals WHERE cycle_id=? "
                    "AND validation_status='accepted'", (cycle["cycle_id"],),
                ).fetchone()[0])
                research_conflicts = int(con.execute(
                    "SELECT COUNT(*) FROM research_conflicts WHERE cycle_id=? "
                    "AND status='unresolved'", (cycle["cycle_id"],),
                ).fetchone()[0])
                latest_memory = con.execute(
                    "SELECT memory_summary_json FROM cycle_manifests WHERE cycle_id=? "
                    "ORDER BY revision DESC LIMIT 1", (cycle["cycle_id"],),
                ).fetchone()
                if latest_memory:
                    try:
                        memory = json.loads(latest_memory["memory_summary_json"])
                        strategic_memory_status = str(memory.get("status") or "invalid")
                        strategic_memory_counts = {
                            "decisions": len(memory.get("decision_records") or []),
                            "reviews": len(memory.get("gw_reviews") or []),
                            "lessons": len(memory.get("lessons") or []),
                        }
                        strategic_plan_revision = int(
                            (memory.get("plan_comparison") or {}).get("active_revision") or 0
                        )
                    except (TypeError, ValueError, json.JSONDecodeError):
                        strategic_memory_status = "invalid"
            for row in con.execute(
                "SELECT status,COUNT(*) n FROM research_runs GROUP BY status"
            ).fetchall():
                research_global_counts[str(row["status"])] = int(row["n"])
            last_import = con.execute(
                "SELECT imported_at FROM research_runs WHERE imported_at IS NOT NULL "
                "ORDER BY imported_at DESC LIMIT 1"
            ).fetchone()
            if last_import:
                try:
                    research_last_import_epoch = datetime.fromisoformat(
                        str(last_import["imported_at"]).replace("Z", "+00:00")
                    ).timestamp()
                except ValueError:
                    pass
            latest_coverage = con.execute(
                "SELECT coverage_ratio,evidence_ratio FROM research_runs "
                "WHERE status='imported' AND coverage_status IN ('complete','partial','failed') "
                "ORDER BY imported_at DESC LIMIT 1"
            ).fetchone()
            if latest_coverage:
                research_coverage_ratio = float(latest_coverage["coverage_ratio"] or 0)
                research_evidence_ratio = float(latest_coverage["evidence_ratio"] or 0)
            research_measured_gameweeks = int(con.execute(
                "SELECT COUNT(DISTINCT cycle_id) FROM research_runs "
                "WHERE status='imported' AND coverage_status IN ('complete','partial','failed')"
            ).fetchone()[0])
            latest_envelope = con.execute(
                "SELECT envelope_id,status FROM decision_envelopes "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if latest_envelope:
                decision_envelope_status = str(latest_envelope["status"])
                decision_blocking_checks = int(con.execute(
                    "SELECT COUNT(*) FROM decision_validation_checks "
                    "WHERE envelope_id=? AND severity='block' AND passed=0",
                    (latest_envelope["envelope_id"],),
                ).fetchone()[0])
            latest_plan = con.execute(
                "SELECT plan_id,status FROM execution_plans ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if latest_plan:
                execution_plan_status = str(latest_plan["status"])
                execution_plan_blockers = int(con.execute(
                    "SELECT COUNT(*) FROM execution_preflight_checks "
                    "WHERE plan_id=? AND passed=0", (latest_plan["plan_id"],)
                ).fetchone()[0])
            latest_attempt = con.execute(
                "SELECT execution_id,status FROM execution_attempts "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if latest_attempt:
                execution_attempt_status = str(latest_attempt["status"])
            execution_attempt_counts = {
                str(row["status"]): int(row["n"])
                for row in con.execute(
                    "SELECT status,COUNT(*) AS n FROM execution_attempts GROUP BY status"
                ).fetchall()
            }
            latest_deliberation = con.execute(
                """SELECT d.deliberation_id,d.status
                FROM decision_envelopes e
                JOIN decision_deliberation_bindings b ON b.envelope_id=e.envelope_id
                JOIN decision_deliberations d ON d.deliberation_id=b.deliberation_id
                WHERE e.status IN ('blocked','staged')
                ORDER BY e.created_at DESC LIMIT 1"""
            ).fetchone()
            if not latest_deliberation:
                latest_deliberation = con.execute(
                    "SELECT deliberation_id,status FROM decision_deliberations "
                    "ORDER BY queued_at DESC LIMIT 1"
                ).fetchone()
            if latest_deliberation:
                deliberation_status = str(latest_deliberation["status"])
                deliberation_blocking_risks = int(con.execute(
                    "SELECT COUNT(*) FROM decision_deliberation_risks "
                    "WHERE deliberation_id=? AND severity='block'",
                    (latest_deliberation["deliberation_id"],),
                ).fetchone()[0])
            from mova_fpl.ops.browser_driver import (
                DRIVER_CONTRACT_VERSION, R3_DRIVER_CONTRACT_VERSION,
            )
            rehearsal_versions = {
                "captaincy": DRIVER_CONTRACT_VERSION,
                "lineup": DRIVER_CONTRACT_VERSION,
                "r3": R3_DRIVER_CONTRACT_VERSION,
            }
            for capability, version in rehearsal_versions.items():
                browser_rehearsals[capability] = int(con.execute(
                    "SELECT COUNT(DISTINCT cycle_id) FROM browser_rehearsals "
                    "WHERE capability=? AND contract_version=? AND status='passed' "
                    "AND writes_attempted=0", (capability, version),
                ).fetchone()[0])
            latest_cutover = con.execute(
                "SELECT status,metrics_json FROM job_runs "
                "WHERE job_type='postgres_read_cutover_drill' "
                "ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            if latest_cutover:
                postgres_cutover_status = str(latest_cutover["status"])
                try:
                    cutover_metrics = json.loads(latest_cutover["metrics_json"] or "{}")
                    postgres_cutover_rollback_verified = int(
                        cutover_metrics.get("rollback_verified") is True
                    )
                except (TypeError, json.JSONDecodeError):
                    postgres_cutover_rollback_verified = 0
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
            "# HELP mova_research_runs Research runs by status for current cycle.",
            "# TYPE mova_research_runs gauge",
            *[f'mova_research_runs{{status="{name}"}} {count}'
              for name, count in sorted(research_counts.items())],
            "# HELP mova_research_accepted_signals Accepted signals for current cycle.",
            "# TYPE mova_research_accepted_signals gauge",
            f"mova_research_accepted_signals {research_signals}",
            "# HELP mova_research_unresolved_conflicts Unresolved research conflicts.",
            "# TYPE mova_research_unresolved_conflicts gauge",
            f"mova_research_unresolved_conflicts {research_conflicts}",
            "# HELP mova_research_runs_total Research runs by terminal status across cycles.",
            "# TYPE mova_research_runs_total gauge",
            *[f'mova_research_runs_total{{status="{name}"}} {count}'
              for name, count in sorted(research_global_counts.items())],
            "# HELP mova_research_last_import_timestamp_seconds Last imported research run.",
            "# TYPE mova_research_last_import_timestamp_seconds gauge",
            f"mova_research_last_import_timestamp_seconds {research_last_import_epoch:.3f}",
            "# HELP mova_research_coverage_ratio Checked focus subjects in latest measured run.",
            "# TYPE mova_research_coverage_ratio gauge",
            f"mova_research_coverage_ratio {research_coverage_ratio:.6f}",
            "# HELP mova_research_evidence_ratio Focus subjects backed by sealed locators.",
            "# TYPE mova_research_evidence_ratio gauge",
            f"mova_research_evidence_ratio {research_evidence_ratio:.6f}",
            "# HELP mova_research_measured_gameweeks Gameweeks with explicit coverage v2.",
            "# TYPE mova_research_measured_gameweeks gauge",
            f"mova_research_measured_gameweeks {research_measured_gameweeks}",
            "# HELP mova_strategic_memory_status Latest sealed memory lifecycle status.",
            "# TYPE mova_strategic_memory_status gauge",
            *[f'mova_strategic_memory_status{{status="{name}"}} '
              f'{1 if strategic_memory_status == name else 0}'
              for name in ("missing", "empty", "ready", "invalid")],
            "# HELP mova_strategic_memory_items Included memory items by promoted type.",
            "# TYPE mova_strategic_memory_items gauge",
            *[f'mova_strategic_memory_items{{type="{name}"}} {count}'
              for name, count in sorted(strategic_memory_counts.items())],
            "# HELP mova_strategic_plan_revision Active season-plan revision in memory.",
            "# TYPE mova_strategic_plan_revision gauge",
            f"mova_strategic_plan_revision {strategic_plan_revision}",
            "# HELP mova_decision_envelope_status Latest envelope lifecycle status.",
            "# TYPE mova_decision_envelope_status gauge",
            *[f'mova_decision_envelope_status{{status="{name}"}} '
              f'{1 if decision_envelope_status == name else 0}'
              for name in ("missing", "blocked", "staged", "superseded")],
            "# HELP mova_decision_blocking_checks Failed hard gates in latest envelope.",
            "# TYPE mova_decision_blocking_checks gauge",
            f"mova_decision_blocking_checks {decision_blocking_checks}",
            "# HELP mova_execution_plan_status Latest deterministic preflight status.",
            "# TYPE mova_execution_plan_status gauge",
            *[f'mova_execution_plan_status{{status="{name}"}} '
              f'{1 if execution_plan_status == name else 0}'
              for name in ("missing", "blocked", "authorized", "noop", "superseded")],
            "# HELP mova_execution_preflight_blocking_checks Failed execution gates.",
            "# TYPE mova_execution_preflight_blocking_checks gauge",
            f"mova_execution_preflight_blocking_checks {execution_plan_blockers}",
            "# HELP mova_execution_attempt_status Latest apply-once attempt status.",
            "# TYPE mova_execution_attempt_status gauge",
            *[f'mova_execution_attempt_status{{status="{name}"}} '
              f'{1 if execution_attempt_status == name else 0}'
              for name in ("missing", "prepared", "claimed", "applying", "ambiguous",
                           "verified", "failed", "blocked", "expired")],
            "# HELP mova_execution_attempts_total Execution attempts by lifecycle status.",
            "# TYPE mova_execution_attempts_total gauge",
            *[f'mova_execution_attempts_total{{status="{name}"}} '
              f'{execution_attempt_counts.get(name, 0)}'
              for name in ("prepared", "claimed", "applying", "ambiguous", "verified",
                           "failed", "blocked", "expired")],
            "# HELP mova_deliberation_status Latest Strategist+Critic lifecycle status.",
            "# TYPE mova_deliberation_status gauge",
            *[f'mova_deliberation_status{{status="{name}"}} '
              f'{1 if deliberation_status == name else 0}'
              for name in ("missing", "queued", "accepted", "review_required", "blocked",
                           "rejected", "failed")],
            "# HELP mova_deliberation_blocking_risks Blocking risks in latest critique.",
            "# TYPE mova_deliberation_blocking_risks gauge",
            f"mova_deliberation_blocking_risks {deliberation_blocking_risks}",
            "# HELP mova_browser_rehearsals Distinct gameweeks with passed read-only rehearsals.",
            "# TYPE mova_browser_rehearsals gauge",
            *[f'mova_browser_rehearsals{{capability="{name}"}} {count}'
              for name, count in sorted(browser_rehearsals.items())],
            "# HELP mova_postgres_cutover_drill_status Latest read cutover drill lifecycle.",
            "# TYPE mova_postgres_cutover_drill_status gauge",
            *[f'mova_postgres_cutover_drill_status{{status="{name}"}} '
              f'{1 if postgres_cutover_status == name else 0}'
              for name in ("missing", "running", "completed", "failed")],
            "# HELP mova_postgres_cutover_rollback_verified Whether the latest drill returned to SQLite.",
            "# TYPE mova_postgres_cutover_rollback_verified gauge",
            f"mova_postgres_cutover_rollback_verified {postgres_cutover_rollback_verified}",
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
