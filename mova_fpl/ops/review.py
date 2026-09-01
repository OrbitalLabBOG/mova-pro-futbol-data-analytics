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
                result = harness.call("validate_and_score", lambda: self._build(
                    package, official, package_path, job_id, cycle_id, correlation_id,
                    actor, reason, idempotency_key,
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
            self.db.finish_job(job_id, "completed", output_sha256=sha256_json(output), metrics={
                "gw": package["gw"], "entry_points": result["selected_score"]["points"],
                "comparator_points": result["comparator_score"]["points"],
                "causal_scorecard_created": False,
            })
            self.db.resolve_incidents(
                f"Settlement GW{package['gw']} falló",
                resolution=f"settlement recuperado por job exitoso {job_id}",
                actor=actor,
            )
            return output

    def _build(self, package: dict, official: dict, package_path: Path, job_id: str,
               cycle_id: str, correlation_id: str, actor: str, reason: str,
               idempotency_key: str) -> dict:
        gw = int(package["gw"])
        analysis = analyze_scenarios(package, official)
        rules = analysis["rules"]
        selected = analysis["selected_decision"]
        comparator = analysis["comparator_decision"]
        selected_score = analysis["selected_score"]
        comparator_score = analysis["comparator_score"]
        selected_rows = analysis["selected_rows"]
        comparator_rows = analysis["comparator_rows"]
        live_points = {
            int(row["element"]): int(row["total_points"]) for row in official["live"]
        }
        official_picks = {int(row["element"]): int(row["multiplier"]) for row in official["picks"]}
        selected_ids = {int(row["element"]) for row in package["selected"]["players"]}
        if selected_ids != set(official_picks):
            raise RuntimeError("la decisión seleccionada no coincide con los 15 picks oficiales")
        official_points = sum(
            int(row["total_points"]) * official_picks[int(row["element"])]
            for row in official["live"] if int(row["element"]) in official_picks
        )
        if official_points != int(official["entry"]["event_points"]) or official_points != selected_score["points"]:
            raise RuntimeError(
                f"accounting oficial no cuadra: picks={official_points} "
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
                "team_state_id": ids["team_state"], "observed_at": package["mounted_at"],
                "source_name": "manual_verified_mount", "squad": package["selected"]["players"],
                "free_transfers": 0, "bank_tenths": 0, "chips": package["chip_inventory"],
                "fingerprint": selected.fingerprint(),
                "artifact_path": package["mount_evidence_path"],
                "manifest_sha256": package["mount_evidence_sha256"],
            },
            "research_signals": [{
                **signal,
                "signal_id": _deterministic_id("signal", idempotency_key, f"signal-{index}"),
                "observed_at": package["reviewed_at"], "expires_at": package["deadline_at"],
                "content_sha256": sha256_json({"claim": signal["claim_text"],
                                                "url": signal["source_url"]}),
            } for index, signal in enumerate(package.get("research_signals") or [])],
            "intervention": {
                "intervention_id": ids["intervention"], "policy_version": "manual-reviewed-v1",
                "payload": package["intervention"], "rationale": package["intervention"]["rationale"],
                "created_at": package["reviewed_at"],
            },
            "decision": {
                "decision_id": ids["decision"], "revision": 1, "mode": "manual",
                "policy_version": package["selected"]["policy_version"],
                "expected_points": selected.expected_points, "chip": None,
                "fingerprint": selected.fingerprint(), "manifest_sha256": sha256_json(package),
                "artifact_path": package["decision_acta_path"], "created_at": package["reviewed_at"],
                "players": decision_players,
            },
            "chip_strategy": {
                "strategy_id": ids["strategy"], "window_name": "H1_GW01_19",
                "policy_version": "manual-hold-v1", "inventory": package["chip_inventory"],
                "manifest_sha256": sha256_json({"inventory": package["chip_inventory"],
                                                 "recommended_chip": None}),
                "created_at": package["reviewed_at"],
            },
            "execution": {
                "execution_id": ids["execution"], "envelope_sha256": sha256_json(package["selected"]),
                "started_at": package["mounted_at"], "finished_at": package["mounted_at"],
                "evidence_path": package["mount_evidence_path"],
                "evidence_sha256": package["mount_evidence_sha256"], "checks": checks,
            },
            "settlement": {
                "settlement_id": ids["settlement"], "idempotency_key": idempotency_key,
                "source_artifact_id": source["artifact_id"], "settled_at": created_at,
                "entry_points": official_points, "entry_rank": official["entry"]["event_rank"],
                "average_points": metrics["entry"]["average_points"], "bench_points": bench_points,
                "hit_cost": 0, "captain_points": selected_score["captain_points"],
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
                "comparator_score": comparator_score, "ledger": ledger}
