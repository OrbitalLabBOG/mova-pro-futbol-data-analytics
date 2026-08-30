"""Plan de ejecución y preflight determinista para acciones FPL.

Este módulo prepara evidencia; no contiene primitivas browser ni escribe en FPL.
La autorización depende exclusivamente de policy, controles y estado observado.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB, canonical_json, sha256_json
from mova_fpl.ops.decision_envelope import decision_fingerprint
from mova_fpl.ops.schedule import phase_for, private_state_cadence_seconds

SCHEMA = "mova-execution-plan-v1"
POLICY_VERSION = "autonomy-policy-1.0.0"
MAX_ENVELOPE_BYTES = 5 * 1024 * 1024
ACTION_LEVELS = {"A0": 0, "A1": 1, "A2": 2, "A3": 3}
RISK_REQUIREMENTS = {"R0": "A0", "R2": "A2", "R3": "A3"}
EXECUTION_PHASES = {"preflight", "freeze", "execution_window"}


def _parse_time(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp sin zona horaria")
    return parsed.astimezone(timezone.utc)


def _check(code: str, passed: bool, summary: str, **detail) -> dict:
    return {
        "code": code,
        "passed": bool(passed),
        "severity": "block",
        "summary": summary,
        "detail": detail,
    }


def _candidate(envelope: dict, key: str) -> dict:
    for row in envelope.get("candidates") or ():
        if row.get("candidate_key") == key:
            return dict(row["decision"])
    raise ValueError(f"candidato ausente: {key}")


def _risk_and_diff(envelope: dict) -> tuple[str, dict]:
    selected = _candidate(envelope, str(envelope["selected_candidate_key"]))
    current = _candidate(envelope, "do_nothing")
    selected_starters = {int(value) for value in selected["starters"]}
    current_starters = {int(value) for value in current["starters"]}
    diff = {
        "transfers": {
            "out": [int(value) for value in selected.get("transfers_out") or ()],
            "in": [int(value) for value in selected.get("transfers_in") or ()],
            "hits": int(selected.get("hits") or 0),
        },
        "lineup": {
            "to_bench": sorted(current_starters - selected_starters),
            "to_start": sorted(selected_starters - current_starters),
            "starters": [int(value) for value in selected["starters"]],
            "bench_order": [int(value) for value in selected["bench_order"]],
        },
        "captain": {
            "from": int(current["captain"]), "to": int(selected["captain"]),
        },
        "vice_captain": {
            "from": int(current["vice_captain"]),
            "to": int(selected["vice_captain"]),
        },
        "chip": {"from": current.get("chip"), "to": selected.get("chip")},
    }
    irreversible = bool(
        diff["transfers"]["in"] or diff["transfers"]["out"]
        or diff["transfers"]["hits"] or diff["chip"]["to"]
    )
    reversible = bool(
        diff["lineup"]["to_bench"] or diff["lineup"]["to_start"]
        or diff["captain"]["from"] != diff["captain"]["to"]
        or diff["vice_captain"]["from"] != diff["vice_captain"]["to"]
        or current.get("bench_order") != selected.get("bench_order")
    )
    return ("R3" if irreversible else "R2" if reversible else "R0"), diff


def build_execution_plan(*, envelope: dict, envelope_row: dict, manifest_row: dict,
                         team_state: dict | None, controls: dict,
                         open_high_incidents: list[dict], prior_execution: dict | None,
                         now: datetime, idempotency_key: str, actor: str,
                         reason: str) -> dict:
    """Construye un plan inmutable y fail-closed sin realizar IO."""
    now = now.astimezone(timezone.utc)
    risk_class, exact_diff = _risk_and_diff(envelope)
    required_level = RISK_REQUIREMENTS[risk_class]
    selected = _candidate(envelope, str(envelope["selected_candidate_key"]))
    deadline = _parse_time(manifest_row["deadline_at"])
    effective_phase = phase_for(deadline.isoformat(), now)
    observed_at = None
    age_seconds = None
    freshness_limit = private_state_cadence_seconds(deadline.isoformat(), now)
    if team_state and team_state.get("observed_at"):
        observed_at = _parse_time(team_state["observed_at"])
        age_seconds = max(0, int((now - observed_at).total_seconds()))

    expected_team_fingerprint = (envelope.get("team_state") or {}).get("fingerprint")
    action_level = str(controls.get("action_level") or "A0")
    controls_authorize = (
        action_level in ACTION_LEVELS
        and ACTION_LEVELS[action_level] >= ACTION_LEVELS[required_level]
    )
    no_action = risk_class == "R0"
    checks = [
        _check("ENVELOPE_ARTIFACT_VERIFIED", True,
               "el artifact coincide con el registro y su hash de contenido",
               envelope_sha256=envelope_row["content_sha256"]),
        _check("ENVELOPE_STAGED", envelope_row["status"] == "staged",
               "el envelope vigente superó sus hard gates",
               observed_status=envelope_row["status"]),
        _check("MANIFEST_BOUND",
               envelope_row["manifest_id"] == manifest_row["manifest_id"]
               and envelope["manifest"]["content_sha256"] == manifest_row["content_sha256"],
               "el plan está ligado al manifest inmutable vigente",
               manifest_id=manifest_row["manifest_id"]),
        _check("TEAM_STATE_PRESENT", team_state is not None,
               "existe un estado autenticado para el ciclo"),
        _check("TEAM_STATE_VALID", bool(team_state)
               and team_state.get("quality_status") == "valid",
               "el estado autenticado conserva calidad válida",
               quality_status=(team_state or {}).get("quality_status")),
        _check("TEAM_STATE_FINGERPRINT_MATCH", bool(team_state)
               and team_state.get("fingerprint") == expected_team_fingerprint,
               "el estado no cambió desde el solve",
               expected=expected_team_fingerprint,
               observed=(team_state or {}).get("fingerprint")),
        _check("TEAM_STATE_FRESH", age_seconds is not None
               and age_seconds <= freshness_limit,
               "el estado autenticado cumple la cadencia de la fase",
               age_seconds=age_seconds, max_age_seconds=freshness_limit),
        _check("EXECUTION_WINDOW", effective_phase in EXECUTION_PHASES,
               "la acción ocurre dentro de preflight, freeze o execution_window",
               phase=effective_phase, allowed=sorted(EXECUTION_PHASES)),
        _check("DEADLINE_OPEN", now < deadline,
               "el deadline oficial sigue abierto", deadline_at=deadline.isoformat()),
        _check("NO_OPEN_P0_P1", not open_high_incidents,
               "no existen incidentes P0/P1 abiertos",
               incidents=[row.get("incident_id") for row in open_high_incidents]),
        _check("KILL_SWITCH_OFF", controls.get("kill_switch") is False,
               "el kill switch permite ejecución"),
        _check("BROWSER_WRITES_ENABLED", controls.get("browser_writes") is True,
               "las escrituras browser están habilitadas"),
        _check("COMPLIANCE_APPROVED", controls.get("compliance_gate") == "approved",
               "el gate de cumplimiento está aprobado",
               observed=controls.get("compliance_gate")),
        _check("AUTONOMY_LEVEL_SUFFICIENT", controls_authorize,
               "el nivel de autonomía cubre la clase de riesgo",
               observed=action_level, required=required_level, risk_class=risk_class),
        _check("AUTONOMOUS_MODE", controls.get("mode") == "autonomous",
               "la ejecución sin aprobación humana exige modo autonomous",
               observed=controls.get("mode")),
        _check("NOT_ALREADY_EXECUTED", prior_execution is None,
               "la decisión no tiene una ejecución previa",
               execution_id=(prior_execution or {}).get("execution_id"),
               status=(prior_execution or {}).get("status")),
    ]
    blocking = [] if no_action else [row["code"] for row in checks if not row["passed"]]
    status = "noop" if no_action else "authorized" if not blocking else "blocked"
    body = {
        "schema": SCHEMA,
        "policy_version": POLICY_VERSION,
        "cycle_id": envelope["cycle_id"],
        "season": envelope["season"],
        "gw": int(envelope["gw"]),
        "created_at": now.isoformat(timespec="seconds"),
        "deadline_at": deadline.isoformat(timespec="seconds"),
        "effective_phase": effective_phase,
        "actor": actor,
        "reason": reason,
        "idempotency_key": idempotency_key,
        "envelope": {
            "envelope_id": envelope_row["envelope_id"],
            "decision_id": envelope_row["decision_id"],
            "content_sha256": envelope_row["content_sha256"],
            "manifest_id": envelope_row["manifest_id"],
            "manifest_sha256": manifest_row["content_sha256"],
            "selected_candidate_key": envelope["selected_candidate_key"],
        },
        "action": {
            "risk_class": risk_class,
            "required_action_level": required_level,
            "exact_diff": exact_diff,
            "expected_pre_team_fingerprint": expected_team_fingerprint,
            "expected_pre_decision_fingerprint": decision_fingerprint(
                _candidate(envelope, "do_nothing")
            ),
            "expected_post_decision_fingerprint": decision_fingerprint(selected),
        },
        "controls": controls,
        "authorization": {
            "status": status,
            "authorized": status == "authorized",
            "requires_human_approval": controls.get("mode") != "autonomous"
            and not no_action,
            "blocking_codes": blocking,
            "checks": checks,
        },
        "execution_contract": {
            "apply_once": True,
            "post_read_required": True,
            "success_requires_post_state_match": True,
            "on_mismatch": "stop_and_open_incident",
            "rollback": "no_automatic_rollback_for_irreversible_actions",
        },
    }
    content_sha = sha256_json(body)
    return {**body, "plan_id": f"execplan_{content_sha[:24]}",
            "content_sha256": content_sha}


class ExecutionService:
    """Fachada de preflight persistido. No implementa ``apply``."""

    def __init__(self, config: RuntimeConfig, db: OpsDB):
        self.config = config
        self.db = db

    @staticmethod
    def _file_sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def preflight(self, *, actor: str, reason: str, idempotency_key: str,
                  now: datetime | None = None) -> dict:
        if not actor.strip() or not reason.strip() or not idempotency_key.strip():
            raise ValueError("preflight exige actor, reason e idempotency_key")
        self.db.migrate()
        job_id, reused = self.db.start_job(
            "execution_preflight", idempotency_key, f"corr_{sha256_json(idempotency_key)[:24]}"
        )
        if reused:
            existing = self.db.execution_plan_for_job(job_id)
            if not existing:
                raise RuntimeError("job idempotente sin execution plan persistido")
            return {**existing, "reused": True, "job_id": job_id}
        try:
            source = self.db.execution_preflight_source()
            if not source.get("envelope"):
                raise ValueError("no existe DecisionEnvelope para preparar")
            envelope_row = source["envelope"]
            self.db.bind_job_cycle(job_id, str(envelope_row["cycle_id"]))
            artifact = Path(envelope_row["artifact_path"])
            if not artifact.is_file():
                raise FileNotFoundError(artifact)
            artifact_resolved = artifact.resolve()
            if not artifact_resolved.is_relative_to(self.config.artifact_root.resolve()):
                raise ValueError("DecisionEnvelope fuera del artifact root autorizado")
            if artifact_resolved.stat().st_size > MAX_ENVELOPE_BYTES:
                raise ValueError("DecisionEnvelope excede tamaño máximo")
            if self._file_sha(artifact) != envelope_row["artifact_sha256"]:
                raise ValueError("hash físico del DecisionEnvelope no coincide")
            envelope = json.loads(artifact.read_text(encoding="utf-8"))
            if envelope.get("content_sha256") != envelope_row["content_sha256"]:
                raise ValueError("hash de contenido del DecisionEnvelope no coincide")
            unsigned = {
                key: value for key, value in envelope.items()
                if key not in {"envelope_id", "content_sha256"}
            }
            if sha256_json(unsigned) != envelope_row["content_sha256"]:
                raise ValueError("contenido del DecisionEnvelope no reproduce su hash")
            expected_envelope_id = f"envelope_{envelope_row['content_sha256'][:24]}"
            if (
                envelope.get("envelope_id") != envelope_row["envelope_id"]
                or envelope_row["envelope_id"] != expected_envelope_id
                or envelope.get("cycle_id") != envelope_row["cycle_id"]
                or envelope.get("manifest", {}).get("manifest_id")
                != envelope_row["manifest_id"]
            ):
                raise ValueError("identidad del DecisionEnvelope no coincide con el ledger")
            controls = {key: row["value"] for key, row in self.db.controls().items()}
            plan = build_execution_plan(
                envelope=envelope, envelope_row=envelope_row,
                manifest_row=source["manifest"], team_state=source["team_state"],
                controls=controls, open_high_incidents=source["open_high_incidents"],
                prior_execution=source["prior_execution"],
                now=now or datetime.now(timezone.utc), idempotency_key=idempotency_key,
                actor=actor, reason=reason,
            )
            target = (self.config.artifact_root / "execution-plans" / plan["cycle_id"]
                      / f"{plan['plan_id']}.json")
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            temporary = target.with_suffix(".json.tmp")
            temporary.write_text(payload, encoding="utf-8")
            os.replace(temporary, target)
            result = self.db.record_execution_plan(
                job_id=job_id, plan=plan, artifact_path=str(target),
                artifact_sha256=self._file_sha(target),
            )
            self.db.finish_job(job_id, "completed", output_sha256=plan["content_sha256"],
                               metrics={"status": plan["authorization"]["status"],
                                        "risk_class": plan["action"]["risk_class"],
                                        "blocking_checks": len(
                                            plan["authorization"]["blocking_codes"]
                                        )})
            return {**result, "reused": False, "job_id": job_id}
        except Exception as exc:
            self.db.finish_job(job_id, "failed", error_code=type(exc).__name__,
                               error_detail=str(exc)[:2000])
            raise

    def status(self, *, limit: int = 20) -> dict:
        return {
            "schema": "mova-execution-status-v1",
            "policy_version": POLICY_VERSION,
            "plans": self.db.recent("execution_plans", limit),
        }
