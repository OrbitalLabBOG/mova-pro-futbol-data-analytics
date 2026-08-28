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

    def resolve_incidents(self, title: str, *, resolution: str) -> int:
        with self.transaction() as con:
            cur = con.execute(
                "UPDATE incidents SET status='resolved',closed_at=?,resolution=? "
                "WHERE title=? AND status!='resolved'", (utcnow(), resolution, title),
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
                    "research_summary_json"):
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
                artifact_path,content_sha256,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (manifest_id, body["cycle_id"], revision, body["as_of_at"],
                 body["deadline_at"], body["phase"], body["team_state_id"], body["plan_id"],
                 canonical_json(body["source_manifest"]),
                 canonical_json(body["analytics_manifest"]),
                 canonical_json(body["research_summary"]), artifact_path, content_sha, now),
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
                "reused": False}

    def research_run(self, research_run_id: str) -> dict | None:
        with self.connect(readonly=True) as con:
            row = con.execute(
                "SELECT * FROM research_runs WHERE research_run_id=?",
                (research_run_id,),
            ).fetchone()
        return dict(row) if row else None

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
            for document in payload["documents"]:
                document_id = new_id("document")
                document_ids[document["source_url"]] = document_id
                con.execute(
                    """INSERT OR IGNORE INTO research_documents(
                    document_id,research_run_id,source_url,title,publisher,published_at,
                    observed_at,source_tier,content_sha256) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (document_id, research_run_id, document["source_url"], document["title"],
                     document["publisher"], document.get("published_at"), now,
                     document["source_tier"], sha256_json(document)),
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
                                                      for url in evidence_urls]})),
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
            con.execute(
                """UPDATE research_runs SET status='imported',result_path=?,
                result_sha256=?,usage_json=?,finished_at=?,imported_at=?,
                error_code=NULL,error_detail=NULL WHERE research_run_id=?""",
                (result_path, result_sha256, canonical_json(usage), now, now,
                 research_run_id),
            )
            con.execute(
                """INSERT INTO cost_ledger(
                cost_id,research_run_id,provider,model,input_tokens,output_tokens,
                estimated_cost_usd,subscription_usage,detail_json,occurred_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (new_id("cost"), research_run_id, run["provider"], usage.get("model"),
                 usage.get("input_tokens"), usage.get("output_tokens"),
                 usage.get("estimated_cost_usd"), 1, canonical_json(usage), now),
            )
            self.append_audit(
                "research_imported", actor="mova-research-validator",
                cycle_id=run["cycle_id"], job_id=run["job_id"],
                subject_type="research_run", subject_id=research_run_id,
                payload={"documents": len(payload["documents"]),
                         "signals": len(payload["signals"]), "accepted": accepted,
                         "conflicts": len(payload["conflicts"]),
                         "result_sha256": result_sha256}, con=con,
            )
        return {"research_run_id": research_run_id, "status": "imported",
                "documents": len(payload["documents"]), "signals": len(payload["signals"]),
                "accepted": accepted, "conflicts": len(payload["conflicts"]),
                "reused": False}

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
        return {
            "status": "ready" if manifest else "not_prepared", "cycle_id": cycle_id,
            "manifest": dict(manifest) if manifest else None,
            "research_runs": [dict(row) for row in runs],
            "signals": [dict(row) for row in signals],
            "unresolved_conflicts": conflicts,
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
                "SELECT * FROM change_proposals WHERE review_id=? "
                "ORDER BY priority,created_at,proposal_id", (review["review_id"],),
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

    def recent(self, table: str, limit: int = 50) -> list[dict]:
        allowed = {"job_runs", "job_steps", "audit_events", "incidents", "health_samples",
                   "source_snapshots", "team_state_snapshots", "decision_runs",
                   "outbox_events", "chip_strategy_runs", "gameweek_settlements",
                   "gameweek_reviews", "change_proposals", "season_plans",
                   "cycle_manifests", "research_runs", "research_documents",
                   "research_signals", "research_conflicts", "cost_ledger"}
        if table not in allowed:
            raise ValueError(f"tabla no permitida: {table}")
        order = {
            "job_runs": "started_at", "job_steps": "started_at", "audit_events": "occurred_at",
            "incidents": "opened_at", "health_samples": "observed_at",
            "source_snapshots": "captured_at", "decision_runs": "created_at",
            "team_state_snapshots": "observed_at",
            "outbox_events": "created_at", "chip_strategy_runs": "created_at",
            "gameweek_settlements": "settled_at", "gameweek_reviews": "created_at",
            "change_proposals": "created_at",
            "season_plans": "created_at", "cycle_manifests": "created_at",
            "research_runs": "queued_at", "research_documents": "observed_at",
            "research_signals": "observed_at", "research_conflicts": "created_at",
            "cost_ledger": "occurred_at",
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
        research_counts = {"queued": 0, "imported": 0, "rejected": 0, "failed": 0}
        research_signals = 0
        research_conflicts = 0
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
