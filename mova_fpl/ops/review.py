"""Cierre manual y review retrospectivo de una gameweek asentada."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

from mova_fpl.analytics.gameweek_review import (
    analyze_scenarios, load_closeout_package,
)
from mova_fpl.analytics.strategy_shadow import (
    aggregate_strategy_shadow, settle_strategy_shadow,
)
from mova_fpl.data.private_state import load as load_private_state
from mova_fpl.ops.decision_envelope import decision_fingerprint
from mova_fpl.ops.collector.contracts import canonical_bytes, write_atomic
from mova_fpl.ops.db import OpsDB, sha256_json, utcnow
from mova_fpl.ops.harness import Harness
from mova_fpl.ops.tick import exclusive_lock
from mova_fpl.postgres.store import connect


def _deterministic_id(prefix: str, key: str, suffix: str) -> str:
    token = hashlib.sha256(f"{key}:{suffix}".encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{token}"


def _official_state(config, season: str, gw: int, entry_id: int) -> dict:
    with connect(config, autocommit=True) as con:
        event = con.execute(
            """select distinct on(event_id) artifact_id,observed_at,event_id,deadline_time,
            finished,data_checked,payload from analytics.fpl_event_observations
            where season=%s and event_id=%s order by event_id,observed_at desc""",
            (season, gw),
        ).fetchone()
        if not event or not event["finished"] or not event["data_checked"]:
            raise RuntimeError(f"GW{gw} todavía no está finished + data_checked")
        entry = con.execute(
            """select * from game.fpl_entry_observations
            where season=%s and entry_id=%s and current_event=%s
            order by observed_at desc limit 1""", (season, entry_id, gw),
        ).fetchone()
        if not entry:
            raise RuntimeError(f"sin resultado oficial para entry {entry_id} GW{gw}")
        artifact_id = entry["artifact_id"]
        picks = con.execute(
            "select * from game.fpl_pick_observations where artifact_id=%s and event=%s "
            "order by position", (artifact_id, gw),
        ).fetchall()
        live = con.execute(
            """select element,total_points,minutes,stats from
            analytics.fpl_event_live_observations where artifact_id=%s and event=%s
            order by element""", (artifact_id, gw),
        ).fetchall()
        players = con.execute(
            """select element,web_name,team_id,element_type,now_cost from
            analytics.fpl_player_observations where artifact_id=%s order by element""",
            (artifact_id,),
        ).fetchall()
        source = con.execute(
            "select * from raw.source_artifacts where artifact_id=%s", (artifact_id,),
        ).fetchone()
        projection_count = int(con.execute(
            "select count(*) n from analytics.model_projection_batches "
            "where season=%s and target_gw=%s", (season, gw),
        ).fetchone()["n"])
    if len(picks) != 15 or not live or not source:
        raise RuntimeError(
            f"settlement incompleto: picks={len(picks)} live={len(live)} source={bool(source)}"
        )
    return {
        "event": event, "entry": entry, "picks": picks, "live": live,
        "players": players, "source": source, "projection_count": projection_count,
    }


def _load_strategy_shadow(db: OpsDB, cycle_id: str) -> dict | None:
    """Lee el último envelope del ciclo y verifica su artefacto sellado."""
    row = db.latest_decision_envelope(cycle_id)
    if not row:
        return None
    path = Path(str(row["artifact_path"]))
    if not path.is_file():
        return {"status": "invalid", "reason": "envelope_artifact_missing",
                "envelope_id": row["envelope_id"]}
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != str(row["artifact_sha256"]):
        return {"status": "invalid", "reason": "envelope_artifact_sha256_mismatch",
                "envelope_id": row["envelope_id"]}
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "invalid",
                "reason": f"envelope_json_invalid:{type(exc).__name__}",
                "envelope_id": row["envelope_id"]}
    if str(envelope.get("content_sha256")) != str(row["content_sha256"]):
        return {"status": "invalid", "reason": "envelope_content_sha256_mismatch",
                "envelope_id": row["envelope_id"]}
    shadow = envelope.get("strategy_shadow")
    if not shadow:
        return None
    return {
        "status": "ready", "envelope_id": row["envelope_id"],
        "envelope_sha256": row["content_sha256"], "shadow": shadow,
    }


class GameweekReviewService:
    def __init__(self, config, db: OpsDB):
        self.config = config
        self.db = db

    def run(self, *, package_path: Path, actor: str, reason: str,
            idempotency_key: str) -> dict:
        if not actor.strip() or not reason.strip() or not idempotency_key.strip():
            raise ValueError("actor, reason e idempotency_key son obligatorios")
        package = load_closeout_package(package_path)
        if package["season"] != self.config.season or int(package["entry_id"]) != self.config.team_id:
            raise ValueError("package no corresponde al runtime configurado")
        self.db.migrate()
        cycle_id = self.db.upsert_cycle(
            package["season"], int(package["gw"]), package["deadline_at"],
            phase="settlement", status="active",
        )
        correlation_id = _deterministic_id("corr", idempotency_key, "correlation")
        with exclusive_lock(self.config.lock_path):
            job_id, reused = self.db.start_job(
                "gameweek_review", idempotency_key, correlation_id, cycle_id=cycle_id,
                input_sha256=sha256_json(package),
            )
            if reused:
                existing = self.db.get_job_by_key(idempotency_key) or {}
                if existing.get("status") == "completed":
                    self.db.resolve_incidents(
                        f"Settlement GW{package['gw']} falló",
                        resolution=f"settlement recuperado por job exitoso {job_id}",
                        actor=actor,
                    )
                return {"status": "reused", "job_id": job_id,
                        "existing_status": existing.get("status")}
            harness = Harness(self.db, job_id, correlation_id=correlation_id, cycle_id=cycle_id)
            try:
                official = harness.call("load_official_settlement", lambda: _official_state(
                    self.config, package["season"], int(package["gw"]), int(package["entry_id"])
                ))
                strategy_shadow = harness.call(
                    "load_strategy_shadow",
                    lambda: _load_strategy_shadow(self.db, cycle_id),
                )
                result = harness.call("validate_and_score", lambda: self._build(
                    package, official, package_path, job_id, cycle_id, correlation_id,
                    actor, reason, idempotency_key, strategy_shadow,
                ))
                trace_result = harness.command(
                    "export_trace",
                    [sys.executable, "-m", "mova_fpl.cli.settle_trace",
                     "--package", str(package_path), "--review-artifact",
                     result["ledger"]["review"]["artifact_path"],
                     "--trace-db", str(self.config.trace_db)],
                    timeout=60, env=os.environ.copy(), cwd=Path(__file__).resolve().parents[2],
                )
                if trace_result.returncode != 0:
                    raise RuntimeError(f"export trace falló: {trace_result.stderr[-500:]}")
                trace = json.loads(trace_result.stdout)
                persisted = harness.call(
                    "persist_closeout", lambda: self.db.record_gameweek_closeout(result["ledger"])
                )
                shadow_gate = None
                shadow_gate_artifact = None
                if (result.get("strategy_shadow") or {}).get("status") == "settled":
                    shadow_gate = aggregate_strategy_shadow(
                        self.db.strategy_shadow_settlements(package["season"])
                    )
                    gate_bytes = canonical_bytes(shadow_gate)
                    gate_sha = hashlib.sha256(gate_bytes).hexdigest()
                    gate_path = (
                        self.config.artifact_root / "reviews" / package["season"]
                        / "strategy-shadow-gates" / f"{gate_sha}.json"
                    )
                    write_atomic(gate_path, gate_bytes)
                    shadow_gate_artifact = {"path": str(gate_path), "sha256": gate_sha}
            except Exception as exc:
                self.db.finish_job(job_id, "failed", error_code=type(exc).__name__,
                                   error_detail=str(exc)[:2000])
                self.db.open_incident_once(
                    "P2", f"Settlement GW{package['gw']} falló", correlation_id=correlation_id,
                    cycle_id=cycle_id, job_id=job_id,
                    detail={"error_code": type(exc).__name__, "error": str(exc)[:1000]},
                )
                raise
            output = {"status": "completed", "job_id": job_id,
                      "correlation_id": correlation_id, **persisted, "trace": trace,
                      "artifact_path": result["ledger"]["review"]["artifact_path"],
                      "artifact_sha256": result["ledger"]["review"]["artifact_sha256"]}
            if result.get("strategy_shadow"):
                output.update({
                    "strategy_shadow": result["strategy_shadow"],
                    "strategy_shadow_gate": shadow_gate,
                    "strategy_shadow_gate_artifact": shadow_gate_artifact,
                })
            job_metrics = {
                "gw": package["gw"], "entry_points": result["selected_score"]["points"],
                "comparator_points": result["comparator_score"]["points"],
                "causal_scorecard_created": False,
            }
            if result.get("strategy_shadow"):
                job_metrics.update({
                    "strategy_shadow_status": result["strategy_shadow"].get("status"),
                    "strategy_shadow_realized_delta": result[
                        "strategy_shadow"
                    ].get("comparison", {}).get("realized_points_delta"),
                })
            self.db.finish_job(
                job_id, "completed", output_sha256=sha256_json(output), metrics=job_metrics,
            )
            self.db.resolve_incidents(
                f"Settlement GW{package['gw']} falló",
                resolution=f"settlement recuperado por job exitoso {job_id}",
                actor=actor,
            )
            return output

    def run_autonomous(self, *, gw: int, actor: str, reason: str,
                       idempotency_key: str) -> dict:
        """Construye y consume un closeout sólo desde evidencia sellada compatible.

        La ruta falla cerrada si la ejecución verificada no reproduce exactamente un
        candidato del DecisionEnvelope o si falta el batch causal predeadline.
        """
        package_path = self._autonomous_package(gw=gw)
        return self.run(
            package_path=package_path, actor=actor, reason=reason,
            idempotency_key=idempotency_key,
        )

    def _autonomous_package(self, *, gw: int) -> Path:
        cycle_id = f"{self.config.season}-gw{int(gw):02d}"
        with self.db.connect(readonly=True) as con:
            cycle = con.execute(
                "SELECT * FROM gameweek_cycles WHERE cycle_id=?", (cycle_id,),
            ).fetchone()
            executed = con.execute(
                """SELECT d.*,e.execution_id,e.action_level,e.envelope_sha256,e.started_at,
                e.finished_at,e.evidence_path,e.evidence_sha256
                FROM decision_runs d JOIN web_executions e ON e.decision_id=d.decision_id
                WHERE d.cycle_id=? AND d.status='executed_verified' AND e.status='verified'
                ORDER BY e.finished_at DESC,e.rowid DESC LIMIT 1""", (cycle_id,),
            ).fetchone()
            source_type = "web_execution"
            if not executed:
                executed = con.execute(
                    """SELECT d.*,a.execution_id,p.required_action_level AS action_level,
                    de.content_sha256 AS envelope_sha256,a.started_at,a.finished_at,
                    a.evidence_path,a.evidence_sha256,a.observed_post_fingerprint
                    FROM execution_attempts a JOIN execution_plans p ON p.plan_id=a.plan_id
                    JOIN decision_runs d ON d.decision_id=p.decision_id
                    JOIN decision_envelopes de ON de.envelope_id=p.envelope_id
                    WHERE p.cycle_id=? AND d.status='executed_verified' AND a.status='verified'
                    ORDER BY a.finished_at DESC,a.rowid DESC LIMIT 1""", (cycle_id,),
                ).fetchone()
                source_type = "execution_attempt"
            checks = [] if not executed or source_type != "web_execution" else con.execute(
                "SELECT * FROM verification_checks WHERE execution_id=? ORDER BY checked_at,check_id",
                (executed["execution_id"],),
            ).fetchall()
            strategy = con.execute(
                "SELECT inventory_json FROM chip_strategy_runs WHERE cycle_id=? "
                "ORDER BY created_at DESC LIMIT 1", (cycle_id,),
            ).fetchone()
            executed_players = [] if not executed else con.execute(
                "SELECT * FROM decision_players WHERE decision_id=? ORDER BY squad_position",
                (executed["decision_id"],),
            ).fetchall()
            execution_audit = None if not executed or source_type != "web_execution" else con.execute(
                """SELECT payload_json,payload_sha256 FROM audit_events
                WHERE event_type='manual_verified_execution_recorded'
                  AND subject_type='web_execution' AND subject_id=?
                ORDER BY occurred_at DESC LIMIT 1""", (executed["execution_id"],),
            ).fetchone()
        if not cycle:
            raise RuntimeError(f"ciclo {cycle_id} inexistente")
        if not executed:
            raise RuntimeError(f"GW{gw} sin ejecución verificada")
        evidence_path = Path(str(executed["evidence_path"]))
        if (not evidence_path.is_file()
                or not evidence_path.resolve().is_relative_to(self.config.artifact_root.resolve())
                or hashlib.sha256(evidence_path.read_bytes()).hexdigest()
                != str(executed["evidence_sha256"])):
            raise RuntimeError("evidencia de ejecución ausente, externa o alterada")
        evidence_payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        required_checks = {"authorization", "pre_state", "post_reload_state", "exact_diff"}
        if source_type == "web_execution":
            passed_checks = {str(row["check_name"]) for row in checks if bool(row["passed"])}
            if (not required_checks <= passed_checks
                    or any(not bool(row["passed"]) for row in checks)):
                raise RuntimeError("ejecución sin set completo de verificaciones aprobadas")
            if len(executed_players) != 15 or not execution_audit:
                raise RuntimeError("ejecución sin decisión posicional o audit v2 completos")
            audit_payload = json.loads(str(execution_audit["payload_json"]))
            if sha256_json(audit_payload) != str(execution_audit["payload_sha256"]):
                raise RuntimeError("audit de ejecución no reproduce su hash")
            hit_cost = int(audit_payload.get("hits", 0))
            if hit_cost < 0 or hit_cost % 4:
                raise RuntimeError("audit de ejecución contiene hit_cost inválido")
            executed_decision = {
                "season": self.config.season, "gw": int(gw),
                "squad_15": [int(row["element"]) for row in executed_players],
                "starters": [int(row["element"]) for row in executed_players
                             if row["role"] == "starter"],
                "bench_order": [int(row["element"]) for row in executed_players
                                if row["role"] == "bench"],
                "captain": next(int(row["element"]) for row in executed_players
                                if bool(row["is_captain"])),
                "vice_captain": next(int(row["element"]) for row in executed_players
                                     if bool(row["is_vice_captain"])),
                "transfers_in": audit_payload.get("transfers_in") or [],
                "transfers_out": audit_payload.get("transfers_out") or [],
                "hits": hit_cost // 4, "chip": audit_payload.get("chip"),
            }
            executed_decision_fingerprint = decision_fingerprint(executed_decision)
            team_fingerprint = str(executed["fingerprint"])
        else:
            native_checks = list(evidence_payload.get("verification_checks") or [])
            if (evidence_payload.get("schema") != "mova-execution-evidence-v1"
                    or len(native_checks) < 4
                    or not all(check.get("passed") is True for check in native_checks)
                    or str(executed["observed_post_fingerprint"])
                    != str(executed["fingerprint"])):
                raise RuntimeError("evidencia nativa no acredita post-reload exacto")
            executed_decision_fingerprint = str(executed["observed_post_fingerprint"])
            team_fingerprint = str(evidence_payload.get("private_state_fingerprint") or "")
            checks = native_checks
        if str(executed["action_level"]) not in {"A2", "A3"}:
            raise RuntimeError("ejecución verificada fuera de A2/A3")
        with self.db.connect(readonly=True) as con:
            verified_team_state = con.execute(
                """SELECT * FROM team_state_snapshots WHERE cycle_id=?
                AND fingerprint=? AND quality_status='valid' AND observed_at>=?
                ORDER BY observed_at DESC LIMIT 1""",
                (cycle_id, team_fingerprint, executed["finished_at"]),
            ).fetchone()
        if not verified_team_state:
            raise RuntimeError("sin team-state durable posterior que reproduzca la ejecución")
        team_state_path = Path(str(verified_team_state["artifact_path"]))
        manifest_path = team_state_path / "manifest.json"
        if (not team_state_path.resolve().is_relative_to(self.config.artifact_root.resolve())
                or not manifest_path.is_file()
                or hashlib.sha256(manifest_path.read_bytes()).hexdigest()
                != str(verified_team_state["manifest_sha256"])):
            raise RuntimeError("manifest del team-state posterior ausente, externo o alterado")
        normalized_team_state, private_manifest = load_private_state(
            team_state_path, expected_team_id=self.config.team_id,
        )
        private_quality = dict(private_manifest.get("quality") or {})
        if (private_quality.get("fingerprint") != team_fingerprint
                or [int(row["element"]) for row in normalized_team_state["picks"]]
                != [int(row["element"]) for row in executed_players]
                or int(private_quality.get("bank_tenths", -1))
                != int(verified_team_state["bank_tenths"])
                or int(private_quality.get("free_transfers", -1))
                != int(verified_team_state["free_transfers"])):
            raise RuntimeError("team-state posterior no reproduce su ledger durable")

        with self.db.connect(readonly=True) as con:
            candidates = con.execute(
                """SELECT de.*,dc.candidate_key,dc.label,dc.decision_json,dc.fingerprint
                FROM decision_envelopes de JOIN decision_candidates dc
                  ON dc.envelope_id=de.envelope_id
                WHERE de.cycle_id=? ORDER BY de.created_at DESC""", (cycle_id,),
            ).fetchall()
        matches = [row for row in candidates
                   if str(row["fingerprint"]) == executed_decision_fingerprint]
        if not matches:
            raise RuntimeError(
                "la ejecución verificada no corresponde inequívocamente a un candidato sellado"
            )
        matched = matches[0]
        latest_matches = [row for row in matches
                          if row["envelope_id"] == matched["envelope_id"]]
        if len(latest_matches) != 1:
            raise RuntimeError("fingerprint ambiguo dentro del DecisionEnvelope más reciente")
        envelope_path = Path(str(matched["artifact_path"]))
        if (not envelope_path.is_file()
                or not envelope_path.resolve().is_relative_to(self.config.artifact_root.resolve())
                or hashlib.sha256(envelope_path.read_bytes()).hexdigest()
                != str(matched["artifact_sha256"])):
            raise RuntimeError("DecisionEnvelope ausente, externo o alterado")
        envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
        body = dict(envelope)
        content_sha = str(body.pop("content_sha256", ""))
        envelope_id = str(body.pop("envelope_id", ""))
        if (envelope_id != str(matched["envelope_id"])
                or content_sha != str(matched["content_sha256"])
                or sha256_json(body) != content_sha):
            raise RuntimeError("contenido del DecisionEnvelope no reproduce su hash")
        by_key = {str(row["candidate_key"]): row for row in envelope["candidates"]}
        selected_row = by_key.get(str(matched["candidate_key"]))
        if not selected_row:
            raise RuntimeError("candidato ejecutado ausente del DecisionEnvelope físico")
        selected = dict(selected_row["decision"])
        stored_selected = json.loads(str(matched["decision_json"]))
        if sha256_json(selected) != sha256_json(stored_selected):
            raise RuntimeError("candidato persistido difiere del DecisionEnvelope físico")
        comparator_row = by_key.get("do_nothing")
        if not comparator_row:
            raise RuntimeError("DecisionEnvelope sin comparador do_nothing")
        comparator = dict(comparator_row["decision"])
        if (decision_fingerprint(selected) != executed_decision_fingerprint
                or decision_fingerprint(comparator) != str(comparator.get("fingerprint"))):
            raise RuntimeError("fingerprint de candidato no reproduce el envelope")

        deadline = str(cycle["deadline_at"])
        required = sorted({int(value) for value in selected["squad_15"]}
                          | {int(value) for value in comparator["squad_15"]})
        with connect(self.config, autocommit=True) as con:
            batches = con.execute(
                """select * from analytics.model_projection_batches
                where season=%s and target_gw=%s and status='approved' and cutoff_at<=%s
                order by generated_at desc""", (self.config.season, int(gw), deadline),
            ).fetchall()
            projection_rows = None
            batch = None
            for candidate_batch in batches:
                rows = con.execute(
                    """select p.*,o.now_cost from analytics.player_projections p
                    left join analytics.fpl_player_observations o
                      on o.artifact_id=%s and o.element=p.element
                    where p.batch_id=%s and p.element=any(%s) order by p.element""",
                    (candidate_batch["input_artifact_id"], candidate_batch["batch_id"], required),
                ).fetchall()
                if {int(row["element"]) for row in rows} == set(required) and all(
                    row["now_cost"] is not None for row in rows
                ):
                    batch, projection_rows = candidate_batch, rows
                    break
        if not batch or projection_rows is None:
            raise RuntimeError("sin batch approved predeadline que cubra ambos escenarios")
        projections = {int(row["element"]): row for row in projection_rows}

        def scenario(decision: dict, *, label: str) -> dict:
            starters = {int(value) for value in decision["starters"]}
            order = [int(value) for value in decision["starters"]] + [
                int(value) for value in decision["bench_order"]
            ]
            players = []
            for element in order:
                row = projections[element]
                players.append({
                    "element": element, "name": row["player_name"], "team": row["team"],
                    "position": row["position"], "price": float(row["now_cost"]) / 10,
                    "role": "starter" if element in starters else "bench",
                    "expected_points": float(row["xp"]),
                    "p60": float(row["p_60"]) if row["p_60"] is not None else None,
                })
            return {
                "label": label, "policy_version": str(decision.get("policy") or "unknown"),
                "expected_points": float(decision["expected_points"]),
                "total_cost": float(decision["total_cost"]),
                "bank_after": float(decision.get("bank_after", 0)),
                "captain": int(decision["captain"]),
                "vice_captain": int(decision["vice_captain"]),
                "bench_order": [int(value) for value in decision["bench_order"]],
                "transfers_in": [int(value) for value in decision.get("transfers_in", ())],
                "transfers_out": [int(value) for value in decision.get("transfers_out", ())],
                "hits": int(decision.get("hits", 0)), "chip": decision.get("chip"),
                "players": players,
            }

        verification = {
            str(row["check_name"]): {
                "expected": json.loads(row["expected_json"]),
                "observed": json.loads(row["observed_json"]),
            } for row in checks
        } if source_type == "web_execution" else {
            str(row["code"]): {"expected": row.get("expected"),
                               "observed": row.get("observed")}
            for row in checks
        }
        selected_spec = scenario(selected, label=str(selected_row["label"]))
        comparator_spec = scenario(comparator, label=str(comparator_row["label"]))
        package = {
            "schema": "mova-fpl-autonomous-closeout-v1",
            "season": self.config.season, "gw": int(gw), "entry_id": self.config.team_id,
            "deadline_at": deadline, "reviewed_at": utcnow(),
            "mounted_at": str(executed["finished_at"]),
            "trace_run_id": str(executed["execution_id"]),
            "decision_acta_path": str(envelope_path),
            "mount_evidence_path": str(evidence_path),
            "mount_evidence_sha256": str(executed["evidence_sha256"]),
            "verified_execution_source": source_type,
            "chip_inventory": json.loads(strategy["inventory_json"]) if strategy else [],
            "verified_team_state": dict(verified_team_state),
            "selected": selected_spec, "comparator": comparator_spec,
            "intervention": {
                "policy_version": "autonomous-closeout-1.0.0",
                "selected_fingerprint": decision_fingerprint(selected),
                "base_fingerprint": decision_fingerprint(comparator),
                "payload": {"envelope_id": matched["envelope_id"],
                            "execution_id": executed["execution_id"],
                            "projection_batch_id": batch["batch_id"]},
                "rationale": "atribución pareada desde decisión y ejecución selladas",
            },
            "mount_verification": {
                "squad": verification, "xi": verification,
                "captain": verification, "vice_captain": verification,
                "bench_order": verification, "budget": verification,
                "no_chip": {"expected": selected.get("chip"), "observed": selected.get("chip")},
            },
            "proposals": [],
        }
        package_bytes = canonical_bytes(package)
        package_sha = hashlib.sha256(package_bytes).hexdigest()
        target = (self.config.artifact_root / "reviews" / self.config.season
                  / f"gw{int(gw):02d}" / "inputs" / f"{package_sha}.json")
        write_atomic(target, package_bytes)
        return target

    def _build(self, package: dict, official: dict, package_path: Path, job_id: str,
               cycle_id: str, correlation_id: str, actor: str, reason: str,
               idempotency_key: str, strategy_shadow_source: dict | None = None) -> dict:
        gw = int(package["gw"])
        analysis = analyze_scenarios(package, official)
        rules = analysis["rules"]
        selected = analysis["selected_decision"]
        comparator = analysis["comparator_decision"]
        selected_score = analysis["selected_score"]
        comparator_score = analysis["comparator_score"]
        selected_rows = analysis["selected_rows"]
        comparator_rows = analysis["comparator_rows"]
        strategy_shadow = None
        if strategy_shadow_source:
            if strategy_shadow_source.get("status") != "ready":
                strategy_shadow = {
                    **strategy_shadow_source,
                    "season": package["season"], "gw": gw,
                }
            else:
                try:
                    strategy_shadow = settle_strategy_shadow(
                        strategy_shadow_source["shadow"],
                        season=package["season"], gw=gw,
                        live=official["live"], players=official["players"],
                        envelope_id=strategy_shadow_source["envelope_id"],
                        envelope_sha256=strategy_shadow_source["envelope_sha256"],
                        manual={
                            "fingerprint": selected.fingerprint(),
                            "expected_points": selected.expected_points,
                            "actual_points": selected_score["points"],
                        },
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    strategy_shadow = {
                        "status": "invalid",
                        "season": package["season"], "gw": gw,
                        "reason": (
                            f"shadow_settlement_invalid:{type(exc).__name__}:{exc}"
                        ),
                        "envelope_id": strategy_shadow_source.get("envelope_id"),
                    }
        live_points = {
            int(row["element"]): int(row["total_points"]) for row in official["live"]
        }
        official_picks = {int(row["element"]): int(row["multiplier"]) for row in official["picks"]}
        selected_ids = {int(row["element"]) for row in package["selected"]["players"]}
        if selected_ids != set(official_picks):
            raise RuntimeError("la decisión seleccionada no coincide con los 15 picks oficiales")
        official_points_before_hits = sum(
            int(row["total_points"]) * official_picks[int(row["element"])]
            for row in official["live"] if int(row["element"]) in official_picks
        )
        hit_cost = int(selected.hits) * 4
        official_points = official_points_before_hits - hit_cost
        if official_points != int(official["entry"]["event_points"]) or official_points != selected_score["points"]:
            raise RuntimeError(
                f"accounting oficial no cuadra: picks={official_points_before_hits} "
                f"hits={hit_cost} net={official_points} "
                f"entry={official['entry']['event_points']} engine={selected_score['points']}"
            )
        bench_points = sum(row["actual_points"] for row in selected_rows if row["role"] == "bench")
        oracle_fixed = analysis["oracle_fixed"]
        oracle_free = analysis["oracle_free"]
        low_p60_success = [
            {"element": row["element"], "name": row["player_name"], "p60": row["p60"],
             "minutes": row["minutes"]}
            for row in selected_rows if row["p60"] is not None and row["p60"] < .6
            and row["minutes"] >= 60
        ]
        projection_count = int(official["projection_count"])
        average_points = int(official["event"]["payload"]["average_entry_score"])
        metrics = {
            "schema": "mova-fpl-retrospective-review-v1",
            "causal_scorecard_created": False,
            "causality_reason": (
                "analytics_reconcile_required_for_predeadline_batches"
                if projection_count else "not_eligible_no_predeadline_batch"
            ),
            "predeadline_projection_batches": projection_count,
            "selected": selected_score,
            "comparator": comparator_score,
            "entry": {"points": official_points, "rank": official["entry"]["event_rank"],
                      "average_points": average_points},
            "bench_points": bench_points,
            "same_squad_oracle_fixed_captain": oracle_fixed,
            "same_squad_oracle_free_captain": oracle_free,
            "lineup_regret_fixed_captain": oracle_fixed - selected_score["points"],
            "total_hindsight_regret": oracle_free - selected_score["points"],
            "intervention": {
                "expected_delta": round(selected.expected_points - comparator.expected_points, 2),
                "realized_delta": selected_score["points"] - comparator_score["points"],
            },
            "low_p60_players_who_reached_60": low_p60_success,
        }
        if strategy_shadow:
            metrics["strategy_shadow"] = strategy_shadow
        average_delta = official_points - average_points
        paired_delta = selected_score["points"] - comparator_score["points"]
        selected_captain_points = live_points[selected.captain]
        comparator_captain_points = live_points[comparator.captain]
        captain_delta = selected_captain_points - comparator_captain_points
        result_relation = "ABOVE" if average_delta > 0 else "BELOW" if average_delta < 0 else "AT"
        intervention_relation = (
            "POSITIVE" if paired_delta > 0 else "NEGATIVE" if paired_delta < 0 else "TIED"
        )
        captain_relation = (
            "POSITIVE" if captain_delta > 0 else "NEGATIVE" if captain_delta < 0 else "TIED"
        )
        result_summary = (
            f"El equipo hizo {official_points}, {abs(average_delta)} puntos "
            f"{'por encima' if average_delta > 0 else 'por debajo'} del promedio oficial "
            f"de {average_points}."
            if average_delta else
            f"El equipo hizo {official_points}, igual al promedio oficial."
        )
        findings = [
            {"code": f"ENTRY_RESULT_{result_relation}_AVERAGE", "category": "outcome",
             "summary": result_summary,
             "actionable": False},
            {"code": f"INTERVENTION_PAIRED_{intervention_relation}_VALUE",
             "category": "strategy",
             "summary": (f"La decisión seleccionada produjo {selected_score['points']} puntos "
                         f"contra {comparator_score['points']} del comparador; delta pareado "
                         f"{paired_delta:+d}."),
             "actionable": paired_delta != 0},
            {"code": "EARLY_SEASON_MINUTES_UNDERCALIBRATED", "category": "model",
             "summary": f"{len(low_p60_success)} jugadores con P60 < 60% alcanzaron 60 minutos.",
             "actionable": bool(low_p60_success)},
            {"code": "BENCH_POINTS_NOT_CHIP_CAUSALITY", "category": "variance",
             "summary": f"La banca sumó {bench_points}; eso no demuestra ex ante que Bench Boost era correcto.",
             "actionable": False},
            {"code": f"CAPTAIN_CHOICE_{captain_relation}_COMPARATOR", "category": "strategy",
             "summary": (f"El capitán seleccionado ({selected.captain}) hizo "
                         f"{selected_captain_points} puntos base; el del comparador "
                         f"({comparator.captain}) hizo {comparator_captain_points}; "
                         f"delta base {captain_delta:+d}."),
             "actionable": captain_delta != 0},
        ]
        if strategy_shadow:
            if strategy_shadow.get("status") == "settled":
                shadow_delta = int(
                    strategy_shadow["comparison"]["realized_points_delta"]
                )
                shadow_relation = (
                    "POSITIVE" if shadow_delta > 0
                    else "NEGATIVE" if shadow_delta < 0 else "TIED"
                )
                findings.append({
                    "code": f"LONG_HORIZON_SHADOW_{shadow_relation}",
                    "category": "strategy",
                    "summary": (
                        f"season_fixture_h3 produjo {shadow_delta:+d} puntos contra su "
                        "control pareado; evidencia viva acumulable, no autorización "
                        "de promoción."
                    ),
                    "actionable": False,
                })
            else:
                findings.append({
                    "code": "LONG_HORIZON_SHADOW_NOT_SETTLED",
                    "category": "data",
                    "summary": (
                        f"No se pudo liquidar shadow: {strategy_shadow.get('reason')}"
                    ),
                    "actionable": True,
                })
        created_at = utcnow()
        ids = {name: _deterministic_id(prefix, idempotency_key, name) for name, prefix in {
            "snapshot": "snapshot", "team_state": "teamstate", "intervention": "intervention",
            "decision": "decision", "strategy": "strategy", "execution": "execution",
            "settlement": "settlement", "review": "review",
        }.items()}
        proposals = []
        for index, proposal in enumerate(package["proposals"]):
            evidence = dict(proposal.get("evidence") or {})
            evidence.update({
                "selected_points": selected_score["points"],
                "comparator_points": comparator_score["points"],
                "intervention_realized_delta": metrics["intervention"]["realized_delta"],
                "low_p60_players_who_reached_60": low_p60_success,
            })
            proposals.append({**proposal, "evidence": evidence,
                              "proposal_id": _deterministic_id(
                                  "proposal", idempotency_key, f"proposal-{index}"
                              )})
        review_artifact = {
            "schema": "mova-fpl-gameweek-review-artifact-v1", "created_at": created_at,
            "season": package["season"], "gw": gw, "entry_id": package["entry_id"],
            "source_artifact_id": official["source"]["artifact_id"],
            "decision_package": str(package_path), "metrics": metrics,
            "findings": findings, "proposals": proposals,
            "player_outcomes": [{**row, "scenario": "selected"} for row in selected_rows]
            + [{**row, "scenario": "comparator"} for row in comparator_rows],
        }
        artifact_bytes = canonical_bytes(review_artifact)
        artifact_sha = hashlib.sha256(artifact_bytes).hexdigest()
        artifact_path = (self.config.artifact_root / "reviews" / package["season"]
                         / f"gw{gw:02d}" / f"{artifact_sha}.json")
        write_atomic(artifact_path, artifact_bytes)
        source = official["source"]
        decision_players = []
        for position, row in enumerate(package["selected"]["players"], start=1):
            decision_players.append({
                "element": int(row["element"]), "squad_position": position,
                "role": row["role"], "is_captain": int(row["element"]) == selected.captain,
                "is_vice_captain": int(row["element"]) == selected.vice_captain,
                "expected_points": float(row["expected_points"]),
            })
        checks = []
        for index, name in enumerate(("squad", "xi", "captain", "vice_captain",
                                      "bench_order", "budget", "no_chip")):
            checks.append({
                "check_id": _deterministic_id("check", idempotency_key, f"check-{index}"),
                "check_name": name, "expected": package["mount_verification"][name],
                "observed": package["mount_verification"][name], "passed": True,
            })
        player_outcomes = ([{**row, "scenario": "selected"} for row in selected_rows]
                           + [{**row, "scenario": "comparator"} for row in comparator_rows])
        ledger = {
            "actor": actor, "reason": reason, "job_id": job_id,
            "correlation_id": correlation_id,
            "cycle": {"cycle_id": cycle_id, "season": package["season"], "gw": gw},
            "source_snapshot": {
                "snapshot_id": ids["snapshot"], "source_name": "fpl_official_settlement",
                "captured_at": str(source["observed_at"]), "artifact_path": source["artifact_path"],
                "manifest_sha256": source["manifest_sha256"].strip(),
                "payload_sha256": source["payload_sha256"].strip(),
                "quality": {"status": "final", "finished": True, "data_checked": True,
                            "artifact_id": source["artifact_id"]},
            },
            "team_state": {
                "team_state_id": (
                    package.get("verified_team_state", {}).get("team_state_id")
                    or ids["team_state"]
                ),
                "observed_at": package.get("verified_team_state", {}).get(
                    "observed_at", package["mounted_at"]
                ),
                "source_name": package.get("verified_team_state", {}).get(
                    "source_name", "manual_verified_mount"
                ),
                "squad": json.loads(package["verified_team_state"]["squad_json"])
                if package.get("verified_team_state") else package["selected"]["players"],
                "free_transfers": int(package.get("verified_team_state", {}).get(
                    "free_transfers", 0
                )),
                "bank_tenths": int(package.get("verified_team_state", {}).get(
                    "bank_tenths", 0
                )),
                "chips": json.loads(package["verified_team_state"]["chips_json"])
                if package.get("verified_team_state") else package["chip_inventory"],
                "fingerprint": selected.fingerprint(),
                "artifact_path": package.get("verified_team_state", {}).get(
                    "artifact_path", package["mount_evidence_path"]
                ),
                "manifest_sha256": package.get("verified_team_state", {}).get(
                    "manifest_sha256", package["mount_evidence_sha256"]
                ),
            },
            "research_signals": [{
                **signal,
                "signal_id": _deterministic_id("signal", idempotency_key, f"signal-{index}"),
                "observed_at": package["reviewed_at"], "expires_at": package["deadline_at"],
                "content_sha256": sha256_json({"claim": signal["claim_text"],
                                                "url": signal["source_url"]}),
            } for index, signal in enumerate(package.get("research_signals") or [])],
            "intervention": {
                "intervention_id": ids["intervention"],
                "policy_version": package["intervention"].get(
                    "policy_version", "manual-reviewed-v1"
                ),
                "payload": package["intervention"], "rationale": package["intervention"]["rationale"],
                "created_at": package["reviewed_at"],
            },
            "decision": {
                "decision_id": ids["decision"], "revision": 1, "mode": "manual",
                "policy_version": package["selected"]["policy_version"],
                "expected_points": selected.expected_points, "chip": selected.chip,
                "fingerprint": selected.fingerprint(), "manifest_sha256": sha256_json(package),
                "artifact_path": package["decision_acta_path"], "created_at": package["reviewed_at"],
                "players": decision_players,
            },
            "chip_strategy": {
                "strategy_id": ids["strategy"], "window_name": "H1_GW01_19",
                "policy_version": "manual-hold-v1", "inventory": package["chip_inventory"],
                "recommended_chip": selected.chip,
                "status": "played_verified" if selected.chip else "hold_verified",
                "manifest_sha256": sha256_json({"inventory": package["chip_inventory"],
                                                 "recommended_chip": selected.chip}),
                "created_at": package["reviewed_at"],
            },
            "execution": {
                "execution_id": ids["execution"], "envelope_sha256": sha256_json(package["selected"]),
                "source_type": package.get("verified_execution_source", "web_execution"),
                "source_execution_id": package.get("trace_run_id"),
                "started_at": package["mounted_at"], "finished_at": package["mounted_at"],
                "evidence_path": package["mount_evidence_path"],
                "evidence_sha256": package["mount_evidence_sha256"], "checks": checks,
            },
            "settlement": {
                "settlement_id": ids["settlement"], "idempotency_key": idempotency_key,
                "source_artifact_id": source["artifact_id"], "settled_at": created_at,
                "entry_points": official_points, "entry_rank": official["entry"]["event_rank"],
                "average_points": metrics["entry"]["average_points"], "bench_points": bench_points,
                "hit_cost": hit_cost,
                "captain_points": selected_score["captain_points"],
                "auto_subs": selected_score["auto_subs"],
                "official": {"finished": True, "data_checked": True,
                             "entry_points": official_points, "picks": len(official["picks"])},
            },
            "review": {
                "review_id": ids["review"], "expected_points": selected.expected_points,
                "actual_points": selected_score["points"],
                "comparator_label": package["comparator"]["label"],
                "comparator_expected_points": comparator.expected_points,
                "comparator_actual_points": comparator_score["points"],
                "realized_delta": selected_score["points"] - comparator_score["points"],
                "metrics": metrics, "findings": findings, "artifact_path": str(artifact_path),
                "artifact_sha256": artifact_sha, "created_at": created_at,
                "player_outcomes": player_outcomes, "proposals": proposals,
            },
        }
        return {"rules": rules, "selected_decision": selected,
                "comparator_decision": comparator, "selected_score": selected_score,
                "comparator_score": comparator_score, "ledger": ledger,
                "strategy_shadow": strategy_shadow}
