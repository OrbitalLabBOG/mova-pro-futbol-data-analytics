"""Plan de ejecución y preflight determinista para acciones FPL.

Este módulo prepara evidencia; no contiene primitivas browser ni escribe en FPL.
La autorización depende exclusivamente de policy, controles y estado observado.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mova_fpl.data.private_state import validate as validate_private_state
from mova_fpl.ops.browser_contract import (
    compile_browser_commands,
    compile_r2_ui_action_plan,
    compile_r3_ui_action_plan,
)
from mova_fpl.ops.browser_driver import (
    DRIVER_CONTRACT_VERSION,
    R3_DRIVER_CONTRACT_VERSION,
    driver_capabilities,
)
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB, sha256_json
from mova_fpl.ops.decision_envelope import decision_fingerprint
from mova_fpl.ops.schedule import phase_for, private_state_cadence_seconds

SCHEMA = "mova-execution-plan-v1"
POLICY_VERSION = "autonomy-policy-1.0.0"
MAX_ENVELOPE_BYTES = 5 * 1024 * 1024
MAX_REHEARSAL_BYTES = 1024 * 1024
REHEARSAL_SCHEMA = "mova-browser-rehearsal-evidence-v1"
CAPTAINCY_PROBE_SCHEMA = "mova-browser-dom-probe-v1"
CAPTAINCY_PROBE_CONTRACT = "fpl-pick-team-a11y-2026.08.2"
TRANSFER_PROBE_SCHEMA = "mova-browser-transfer-dom-probe-v1"
TRANSFER_PROBE_CONTRACT = "fpl-transfers-a11y-2026.08.1"
REHEARSAL_CONTRACTS = {
    "captaincy": DRIVER_CONTRACT_VERSION,
    "lineup": DRIVER_CONTRACT_VERSION,
    "r3": R3_DRIVER_CONTRACT_VERSION,
}
ACTION_LEVELS = {"A0": 0, "A1": 1, "A2": 2, "A3": 3}
RISK_REQUIREMENTS = {"R0": "A0", "R2": "A2", "R3": "A3"}
EXECUTION_PHASES = {"preflight", "freeze", "execution_window"}
TERMINAL_ATTEMPT_STATES = {"ambiguous", "verified", "failed", "blocked", "expired"}


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
    """Control plane apply-once; el adapter browser vive fuera del engine."""

    def __init__(self, config: RuntimeConfig, db: OpsDB, *, allow_fixture: bool = False):
        self.config = config
        self.db = db
        self.allow_fixture = allow_fixture

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
        rehearsals = self.db.browser_rehearsal_summary(REHEARSAL_CONTRACTS)
        return {
            "schema": "mova-execution-status-v1",
            "policy_version": POLICY_VERSION,
            "browser_driver": driver_capabilities(rehearsals),
            "plans": self.db.recent("execution_plans", limit),
            "attempts": self.db.recent("execution_attempts", limit),
            "rehearsals": self.db.recent("browser_rehearsals", limit),
        }

    def record_rehearsal(self, *, evidence_file: str | Path, actor: str,
                         reason: str, idempotency_key: str,
                         now: datetime | None = None) -> dict:
        """Validate and append a read-only browser rehearsal evidence artifact."""
        if not actor.strip() or not reason.strip() or not idempotency_key.strip():
            raise ValueError("actor, reason e idempotency_key son obligatorios")
        path = Path(evidence_file)
        if not path.is_file():
            raise FileNotFoundError(path)
        resolved = path.resolve()
        if not resolved.is_relative_to(self.config.artifact_root.resolve()):
            raise ValueError("evidencia de rehearsal fuera del artifact root autorizado")
        if path.stat().st_size > MAX_REHEARSAL_BYTES:
            raise ValueError("evidencia de rehearsal excede 1 MiB")
        evidence = json.loads(path.read_text(encoding="utf-8"))
        required = {
            "schema", "cycle_id", "capability", "contract_version", "observed_at",
            "mode", "status", "writes_attempted", "checks", "source_artifacts",
            "content_sha256",
        }
        if set(evidence) != required:
            raise ValueError("campos de evidencia de rehearsal no coinciden con el contrato")
        if evidence["schema"] != REHEARSAL_SCHEMA:
            raise ValueError("schema de rehearsal no soportado")
        capability = str(evidence["capability"])
        expected_contract = REHEARSAL_CONTRACTS.get(capability)
        if expected_contract is None or evidence["contract_version"] != expected_contract:
            raise ValueError("capability o contract_version de rehearsal inválido")
        if evidence["mode"] not in {"read_only_probe", "validate_only"}:
            raise ValueError("mode de rehearsal no es read-only")
        if evidence["writes_attempted"] is not False:
            raise ValueError("un rehearsal con intentos de escritura no es admisible")
        checks = evidence["checks"]
        if not isinstance(checks, list) or not checks:
            raise ValueError("rehearsal exige checks no vacíos")
        for check in checks:
            if (not isinstance(check, dict) or set(check) != {"code", "passed"}
                    or not isinstance(check["code"], str) or not check["code"].strip()
                    or type(check["passed"]) is not bool):
                raise ValueError("check de rehearsal inválido")
        expected_status = "passed" if all(row["passed"] for row in checks) else "failed"
        if evidence["status"] != expected_status:
            raise ValueError("status de rehearsal no coincide con sus checks")
        sources = evidence["source_artifacts"]
        if not isinstance(sources, list) or not sources:
            raise ValueError("rehearsal exige source_artifacts no vacíos")
        for source in sources:
            if (not isinstance(source, dict) or set(source) != {"path", "sha256"}
                    or not isinstance(source["path"], str) or not source["path"].strip()
                    or not isinstance(source["sha256"], str)
                    or len(source["sha256"]) != 64):
                raise ValueError("source_artifact de rehearsal inválido")
            source_path = (self.config.artifact_root / source["path"]).resolve()
            if not source_path.is_relative_to(self.config.artifact_root.resolve()):
                raise ValueError("source_artifact fuera del artifact root autorizado")
            if not source_path.is_file():
                raise ValueError("source_artifact de rehearsal no existe")
            if self._file_sha(source_path) != source["sha256"]:
                raise ValueError("sha256 de source_artifact no coincide")
        unsigned = {key: value for key, value in evidence.items() if key != "content_sha256"}
        content_sha = sha256_json(unsigned)
        if evidence["content_sha256"] != content_sha:
            raise ValueError("content_sha256 de rehearsal no reproduce su contenido")
        observed_at = _parse_time(evidence["observed_at"])
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if observed_at > current + timedelta(minutes=5):
            raise ValueError("observed_at de rehearsal está en el futuro")
        result = self.db.record_browser_rehearsal(
            cycle_id=str(evidence["cycle_id"]), capability=capability,
            contract_version=expected_contract, evidence_mode=str(evidence["mode"]),
            status=expected_status, checks=checks, evidence_path=str(resolved),
            evidence_sha256=self._file_sha(path), content_sha256=content_sha,
            idempotency_key=idempotency_key, actor=actor.strip(), reason=reason.strip(),
            observed_at=observed_at.isoformat(),
        )
        return {**result, "browser_writes_performed": False}

    def record_captaincy_probe(self, *, source_file: str | Path, cycle_id: str,
                                actor: str, reason: str, idempotency_key: str,
                                now: datetime | None = None) -> dict:
        """Seal a live sanitized pick-team probe and import it as captaincy evidence."""
        source = Path(source_file)
        if not source.is_file():
            raise FileNotFoundError(source)
        resolved = source.resolve()
        root = self.config.artifact_root.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError("probe de capitanía fuera del artifact root autorizado")
        if source.stat().st_size > MAX_REHEARSAL_BYTES:
            raise ValueError("probe de capitanía excede 1 MiB")
        probe = json.loads(source.read_text(encoding="utf-8"))
        if set(probe) != {
            "schema", "contract_version", "observed_at", "team_id", "status",
            "checks", "slots", "captain_controls",
        }:
            raise ValueError("campos del probe de capitanía no coinciden con la allowlist")
        if (probe.get("schema") != CAPTAINCY_PROBE_SCHEMA
                or probe.get("contract_version") != CAPTAINCY_PROBE_CONTRACT):
            raise ValueError("contrato del probe de capitanía no soportado")
        if int(probe.get("team_id") or 0) != self.config.team_id:
            raise ValueError("team_id del probe de capitanía no coincide")
        checks = probe.get("checks")
        captain = probe.get("captain_controls") or {}
        captain_checks = captain.get("checks")
        if (set(captain) != {"status", "selector_strategy", "checks", "starters"}
                or set(checks or {}) != {
                    "signed_in", "fifteen_api_picks", "fifteen_player_controls",
                    "fifteen_switch_controls", "positional_order_matches", "captain_controls",
                }
                or set(captain_checks or {}) != {
                    "eleven_starter_sheets", "semantic_checkboxes", "one_captain",
                    "one_vice_captain", "captain_matches_api", "vice_captain_matches_api",
                }
                or probe.get("status") != "pass" or not isinstance(checks, dict) or not checks
                or not all(type(value) is bool and value for value in checks.values())
                or captain.get("status") != "pass"
                or not isinstance(captain_checks, dict) or not captain_checks
                or not all(type(value) is bool and value for value in captain_checks.values())):
            raise ValueError("probe de capitanía no supera todos los checks read-only")
        starters = captain.get("starters")
        if (not isinstance(starters, list) or len(starters) != 11
                or any(set(row) != {
                    "position", "element", "player_button_index", "captain_checkbox",
                    "vice_captain_checkbox", "captain_checked", "vice_captain_checked",
                } for row in starters)
                or sum(row.get("captain_checked") is True for row in starters) != 1
                or sum(row.get("vice_captain_checked") is True for row in starters) != 1):
            raise ValueError("selecciones semánticas del probe de capitanía son inválidas")
        observed = _parse_time(probe.get("observed_at"))
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if observed > current + timedelta(minutes=5):
            raise ValueError("observed_at del probe de capitanía está en el futuro")
        sealed_checks = [
            {"code": f"pick_team:{code}", "passed": value}
            for code, value in sorted(checks.items())
        ] + [
            {"code": f"captaincy:{code}", "passed": value}
            for code, value in sorted(captain_checks.items())
        ]
        evidence = {
            "schema": REHEARSAL_SCHEMA,
            "cycle_id": cycle_id,
            "capability": "captaincy",
            "contract_version": DRIVER_CONTRACT_VERSION,
            "observed_at": observed.isoformat(),
            "mode": "read_only_probe",
            "status": "passed",
            "writes_attempted": False,
            "checks": sealed_checks,
            "source_artifacts": [{
                "path": str(resolved.relative_to(root)),
                "sha256": self._file_sha(source),
            }],
        }
        evidence["content_sha256"] = sha256_json(evidence)
        target = (self.config.artifact_root / "browser-rehearsals" / cycle_id
                  / f"captaincy-{evidence['content_sha256'][:16]}.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
        return self.record_rehearsal(
            evidence_file=target, actor=actor, reason=reason,
            idempotency_key=idempotency_key, now=current,
        )

    def record_capability_probe(self, *, source_file: str | Path, cycle_id: str,
                                capability: str, actor: str, reason: str,
                                idempotency_key: str,
                                now: datetime | None = None) -> dict:
        """Seal an allowlisted live DOM probe for lineup or R3 evidence.

        These probes prove authenticated selector/identity coverage without
        clicking a commit control. They never promote a capability or change
        browser controls; readiness still requires independent gameweeks and
        an explicitly enabled host entrypoint.
        """
        if capability not in {"lineup", "r3"}:
            raise ValueError("capability de probe debe ser lineup o r3")
        source = Path(source_file)
        if not source.is_file():
            raise FileNotFoundError(source)
        resolved = source.resolve()
        root = self.config.artifact_root.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError("probe browser fuera del artifact root autorizado")
        if source.stat().st_size > MAX_REHEARSAL_BYTES:
            raise ValueError("probe browser excede 1 MiB")
        probe = json.loads(source.read_text(encoding="utf-8"))
        if capability == "lineup":
            checks = self._validate_lineup_probe(probe)
            contract_version = DRIVER_CONTRACT_VERSION
        else:
            checks = self._validate_r3_probe(probe)
            contract_version = R3_DRIVER_CONTRACT_VERSION
        observed = _parse_time(probe.get("observed_at"))
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if observed > current + timedelta(minutes=5):
            raise ValueError("observed_at del probe browser está en el futuro")
        evidence = {
            "schema": REHEARSAL_SCHEMA,
            "cycle_id": cycle_id,
            "capability": capability,
            "contract_version": contract_version,
            "observed_at": observed.isoformat(),
            "mode": "read_only_probe",
            "status": "passed",
            "writes_attempted": False,
            "checks": checks,
            "source_artifacts": [{
                "path": str(resolved.relative_to(root)),
                "sha256": self._file_sha(source),
            }],
        }
        evidence["content_sha256"] = sha256_json(evidence)
        target = (root / "browser-rehearsals" / cycle_id
                  / f"{capability}-{evidence['content_sha256'][:16]}.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
        return self.record_rehearsal(
            evidence_file=target, actor=actor, reason=reason,
            idempotency_key=idempotency_key, now=current,
        )

    def _validate_lineup_probe(self, probe: dict) -> list[dict]:
        allowed = {
            "schema", "contract_version", "observed_at", "team_id", "status",
            "checks", "slots", "captain_controls",
        }
        if set(probe) != allowed:
            raise ValueError("campos del probe de lineup no coinciden con la allowlist")
        if (probe.get("schema") != CAPTAINCY_PROBE_SCHEMA
                or probe.get("contract_version") != CAPTAINCY_PROBE_CONTRACT):
            raise ValueError("contrato del probe de lineup no soportado")
        if int(probe.get("team_id") or 0) != self.config.team_id:
            raise ValueError("team_id del probe de lineup no coincide")
        checks = probe.get("checks")
        required_checks = {
            "signed_in", "fifteen_api_picks", "fifteen_player_controls",
            "fifteen_switch_controls", "positional_order_matches", "captain_controls",
        }
        slots = probe.get("slots")
        slot_fields = {
            "position", "element", "web_name", "player_button_index",
            "switch_button_index", "label_matches",
        }
        valid_slots = (
            isinstance(slots, list) and len(slots) == 15
            and all(isinstance(row, dict) and set(row) == slot_fields for row in slots)
            and [int(row["position"]) for row in slots] == list(range(1, 16))
            and [int(row["player_button_index"]) for row in slots] == list(range(15))
            and [int(row["switch_button_index"]) for row in slots] == list(range(15))
            and len({int(row["element"]) for row in slots}) == 15
            and all(str(row["web_name"] or "").strip() and row["label_matches"] is True
                    for row in slots)
        )
        if (set(checks or {}) != required_checks or probe.get("status") != "pass"
                or not all(type(value) is bool and value for value in checks.values())
                or not valid_slots):
            raise ValueError("probe de lineup no supera todos los checks read-only")
        return [
            {"code": f"lineup:{code}", "passed": value}
            for code, value in sorted(checks.items())
        ] + [{"code": "lineup:slot_identity_allowlist", "passed": True}]

    def _validate_r3_probe(self, probe: dict) -> list[dict]:
        allowed = {
            "schema", "contract_version", "observed_at", "team_id", "status",
            "checks", "squad", "targets", "controls",
        }
        if set(probe) != allowed:
            raise ValueError("campos del probe R3 no coinciden con la allowlist")
        if (probe.get("schema") != TRANSFER_PROBE_SCHEMA
                or probe.get("contract_version") != TRANSFER_PROBE_CONTRACT):
            raise ValueError("contrato del probe R3 no soportado")
        if int(probe.get("team_id") or 0) != self.config.team_id:
            raise ValueError("team_id del probe R3 no coincide")
        checks = probe.get("checks")
        required_checks = {
            "signed_in", "fifteen_api_picks", "squad_remove_controls_present",
            "squad_labels_complete", "targets_complete", "make_transfers",
            "player_search", "wildcard", "free_hit",
        }
        squad = probe.get("squad")
        targets = probe.get("targets")
        controls = probe.get("controls")
        valid_squad = (
            isinstance(squad, list) and len(squad) == 15
            and all(isinstance(row, dict)
                    and set(row) == {"element", "position", "web_name"} for row in squad)
            and [int(row["position"]) for row in squad] == list(range(1, 16))
            and len({int(row["element"]) for row in squad}) == 15
            and all(str(row["web_name"] or "").strip() for row in squad)
        )
        valid_targets = (
            isinstance(targets, list) and bool(targets)
            and all(isinstance(row, dict) and set(row) == {
                "element", "element_type", "web_name", "team", "price",
            } for row in targets)
            and len({int(row["element"]) for row in targets}) == len(targets)
            and all(int(row["element"]) > 0 and 1 <= int(row["element_type"]) <= 4
                    and int(row["price"]) > 0 and str(row["web_name"] or "").strip()
                    and str(row["team"] or "").strip() for row in targets)
        )
        valid_controls = (
            isinstance(controls, dict)
            and set(controls) == {"make_transfers", "player_search", "chip_buttons"}
            and controls["make_transfers"] == "Make Transfers"
            and controls["player_search"] == "Find a player"
            and set(controls["chip_buttons"] or ()) == {"Wildcard Play", "Free Hit Play"}
        )
        if (set(checks or {}) != required_checks or probe.get("status") != "pass"
                or not all(type(value) is bool and value for value in checks.values())
                or not valid_squad or not valid_targets or not valid_controls):
            raise ValueError("probe R3 no supera todos los checks read-only")
        return [
            {"code": f"r3:{code}", "passed": value}
            for code, value in sorted(checks.items())
        ] + [
            {"code": "r3:squad_identity_allowlist", "passed": True},
            {"code": "r3:target_identity_allowlist", "passed": True},
            {"code": "r3:commit_controls_observed_not_clicked", "passed": True},
        ]

    def _load_plan(self, row: dict) -> dict:
        artifact = Path(str(row["artifact_path"]))
        if not artifact.is_file():
            raise FileNotFoundError(artifact)
        resolved = artifact.resolve()
        if not resolved.is_relative_to(self.config.artifact_root.resolve()):
            raise ValueError("ExecutionPlan fuera del artifact root autorizado")
        if self._file_sha(artifact) != row["artifact_sha256"]:
            raise ValueError("hash físico del ExecutionPlan no coincide")
        plan = json.loads(artifact.read_text(encoding="utf-8"))
        unsigned = {key: value for key, value in plan.items()
                    if key not in {"plan_id", "content_sha256"}}
        if (
            plan.get("plan_id") != row["plan_id"]
            or plan.get("content_sha256") != row["content_sha256"]
            or sha256_json(unsigned) != row["content_sha256"]
        ):
            raise ValueError("identidad o contenido del ExecutionPlan no coincide")
        return plan

    @staticmethod
    def _effective_controls(source: dict) -> dict:
        return dict(source.get("controls") or {})

    def _runtime_blockers(self, source: dict, *, now: datetime) -> list[str]:
        row = source["plan"]
        controls = self._effective_controls(source)
        required = str(row["required_action_level"])
        observed = str(controls.get("action_level") or "A0")
        blockers = []
        if row["status"] != "authorized":
            blockers.append("PLAN_NOT_AUTHORIZED")
        if now >= _parse_time(row["deadline_at"]):
            blockers.append("DEADLINE_CLOSED")
        if controls.get("kill_switch") is not False:
            blockers.append("KILL_SWITCH_ON")
        if controls.get("browser_writes") is not True:
            blockers.append("BROWSER_WRITES_DISABLED")
        if controls.get("compliance_gate") != "approved":
            blockers.append("COMPLIANCE_NOT_APPROVED")
        if controls.get("mode") != "autonomous":
            blockers.append("MODE_NOT_AUTONOMOUS")
        if observed not in ACTION_LEVELS or ACTION_LEVELS[observed] < ACTION_LEVELS[required]:
            blockers.append("ACTION_LEVEL_INSUFFICIENT")
        if source.get("open_high_incidents"):
            blockers.append("OPEN_P0_P1")
        state = source.get("team_state")
        if not state or state.get("quality_status") != "valid":
            blockers.append("TEAM_STATE_INVALID")
        elif state.get("fingerprint") != row.get("expected_pre_fingerprint"):
            blockers.append("TEAM_STATE_CHANGED")
        else:
            age = max(0, int((now - _parse_time(state["observed_at"])).total_seconds()))
            limit = private_state_cadence_seconds(row["deadline_at"], now)
            if age > limit:
                blockers.append("TEAM_STATE_STALE")
        return blockers

    def prepare(self, *, plan_id: str, adapter: str, actor: str, reason: str,
                idempotency_key: str, now: datetime | None = None) -> dict:
        """Reserva un intento sólo después de revalidar todos los gates mutables."""
        if not all(value.strip() for value in (plan_id, adapter, actor, reason, idempotency_key)):
            raise ValueError("prepare exige plan_id, adapter, actor, reason e idempotency_key")
        if adapter not in {"disabled", "fixture", "browser"}:
            raise ValueError(f"adapter desconocido: {adapter}")
        if adapter == "disabled":
            raise RuntimeError("executor deshabilitado por configuración")
        if adapter == "fixture" and not self.allow_fixture:
            raise RuntimeError("fixture executor sólo está permitido en tests herméticos")
        self.db.migrate()
        job_id, reused = self.db.start_job(
            "execution_prepare", idempotency_key,
            f"corr_{sha256_json(idempotency_key)[:24]}",
        )
        if reused:
            existing = self.db.execution_attempt_for_job(job_id)
            if not existing:
                raise RuntimeError("job idempotente sin execution attempt persistido")
            return {**existing, "reused": True}
        try:
            current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
            source = self.db.execution_claim_source(plan_id)
            plan = self._load_plan(source["plan"])
            if source.get("attempt"):
                raise RuntimeError(
                    f"plan ya reservado por execution attempt {source['attempt']['execution_id']}"
                )
            if adapter == "browser" and plan["action"]["risk_class"] != "R2":
                raise RuntimeError(
                    "browser adapter sólo está promovido para R2; R3 permanece fail-closed"
                )
            blockers = self._runtime_blockers(source, now=current)
            if blockers:
                raise RuntimeError("runtime gates bloquearon prepare: " + ",".join(blockers))
            execution_id = "execution_" + hashlib.sha256(
                f"{plan_id}:{idempotency_key}".encode("utf-8")
            ).hexdigest()[:24]
            command_body = {
                **compile_browser_commands(plan),
                "execution_id": execution_id,
                "created_at": current.isoformat(timespec="milliseconds"),
            }
            command_sha = sha256_json(command_body)
            command_bundle = {**command_body, "content_sha256": command_sha}
            command_target = (
                self.config.artifact_root / "execution-commands" / plan["cycle_id"]
                / f"{execution_id}.json"
            )
            command_target.parent.mkdir(parents=True, exist_ok=True)
            command_tmp = command_target.with_suffix(".json.tmp")
            command_tmp.write_text(
                json.dumps(command_bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(command_tmp, command_target)
            result = self.db.prepare_execution_attempt(
                plan=source["plan"], job_id=job_id, execution_id=execution_id,
                idempotency_key=idempotency_key, adapter=adapter,
                command_path=str(command_target), command_sha256=self._file_sha(command_target),
                actor=actor,
                reason=reason, created_at=current.isoformat(timespec="milliseconds"),
            )
            self.db.bind_job_cycle(job_id, str(source["plan"]["cycle_id"]))
            return result
        except Exception as exc:
            self.db.finish_job(job_id, "failed", error_code=type(exc).__name__,
                               error_detail=str(exc)[:2000])
            raise

    def claim(self, *, execution_id: str, actor: str, reason: str,
              now: datetime | None = None, lease_seconds: int = 300) -> dict:
        """Entrega un secreto de uso único; nunca se persiste el valor en claro."""
        if not 30 <= int(lease_seconds) <= 600:
            raise ValueError("lease_seconds debe estar entre 30 y 600")
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        attempt = self.db.execution_attempt(execution_id)
        self._validate_command_artifact(attempt)
        source = self.db.execution_claim_source(str(attempt["plan_id"]))
        blockers = self._runtime_blockers(source, now=current)
        if blockers:
            result = self.db.block_prepared_execution(
                execution_id=execution_id, actor=actor, reason=reason,
                blocking_codes=blockers,
                finished_at=current.isoformat(timespec="milliseconds"),
            )
            self.db.finish_job(attempt["job_id"], "failed",
                               error_code="RUNTIME_GATES_CHANGED",
                               error_detail=",".join(blockers))
            return result
        token = secrets.token_urlsafe(32)
        expires = current + timedelta(seconds=int(lease_seconds))
        result = self.db.claim_execution_attempt(
            execution_id=execution_id,
            token_sha256=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            claimant=actor, reason=reason,
            claimed_at=current.isoformat(timespec="milliseconds"),
            lease_expires_at=expires.isoformat(timespec="milliseconds"),
        )
        return {**result, "claim_token": token}

    def compile_ui_plan(self, *, execution_id: str, pre_state: dict,
                        dom_probe: dict, now: datetime | None = None) -> dict:
        """Compila acciones DOM sólo para un lease vigente; todavía no escribe en FPL."""
        attempt = self.db.execution_attempt(execution_id)
        if attempt.get("status") != "claimed":
            raise RuntimeError("UI action plan exige un execution attempt claimed")
        lease_expires = _parse_time(attempt["lease_expires_at"])
        if (now or datetime.now(timezone.utc)).astimezone(timezone.utc) >= lease_expires:
            raise RuntimeError("lease expirado antes de compilar UI action plan")
        bundle = self._validate_command_artifact(attempt)
        compiler = (
            compile_r3_ui_action_plan
            if bundle.get("risk_class") == "R3" else compile_r2_ui_action_plan
        )
        return compiler(bundle=bundle, pre_state=pre_state, dom_probe=dom_probe,
                        expected_team_id=self.config.team_id)

    @staticmethod
    def _token_sha(token: str) -> str:
        if not token.strip():
            raise ValueError("claim token vacío")
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _assert_token(self, attempt: dict, claim_token: str, *, status: str) -> str:
        token_sha = self._token_sha(claim_token)
        stored = str(attempt.get("claim_token_sha256") or "")
        if not stored or not hmac.compare_digest(stored, token_sha):
            raise PermissionError("claim token inválido")
        if attempt.get("status") != status:
            raise RuntimeError(
                f"execution attempt esperaba {status}; observado {attempt.get('status')}"
            )
        return token_sha

    def _validate_command_artifact(self, attempt: dict) -> dict:
        path = Path(str(attempt["command_path"]))
        if not path.is_file() or not path.resolve().is_relative_to(
            self.config.artifact_root.resolve()
        ):
            raise ValueError("command bundle ausente o fuera del artifact root")
        if not hmac.compare_digest(self._file_sha(path), str(attempt["command_sha256"])):
            raise ValueError("hash físico del command bundle no coincide")
        bundle = json.loads(path.read_text(encoding="utf-8"))
        content_sha = str(bundle.pop("content_sha256", ""))
        if (
            bundle.get("execution_id") != attempt["execution_id"]
            or bundle.get("plan_id") != attempt["plan_id"]
            or not hmac.compare_digest(sha256_json(bundle), content_sha)
        ):
            raise ValueError("identidad o contenido del command bundle no coincide")
        return {**bundle, "content_sha256": content_sha}

    def begin(self, *, execution_id: str, claim_token: str, pre_state: dict,
              actor: str, reason: str, now: datetime | None = None) -> dict:
        normalized, quality = validate_private_state(
            pre_state, expected_team_id=self.config.team_id,
        )
        attempt = self.db.execution_attempt(execution_id)
        token_sha = self._assert_token(attempt, claim_token, status="claimed")
        self._validate_command_artifact(attempt)
        source = self.db.execution_claim_source(attempt["plan_id"])
        plan = self._load_plan(source["plan"])
        if int(normalized["event"]["id"]) != int(plan["gw"]):
            raise RuntimeError("pre-state pertenece a otra gameweek")
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        blockers = self._runtime_blockers(source, now=current)
        if quality["fingerprint"] != str(plan["action"]["expected_pre_team_fingerprint"]):
            blockers.append("OBSERVED_PRE_STATE_CHANGED")
        if blockers:
            result_sha = sha256_json({"status": "blocked", "blocking_codes": blockers})
            result = self.db.finish_execution_attempt(
                execution_id=execution_id, token_sha256=token_sha, status="blocked",
                actor=actor, reason=reason,
                finished_at=current.isoformat(timespec="milliseconds"),
                detail={"blocking_codes": blockers}, result_sha256=result_sha,
                error_code="RUNTIME_GATES_CHANGED", error_detail=",".join(blockers),
            )
            self.db.finish_job(attempt["job_id"], "failed",
                               error_code="RUNTIME_GATES_CHANGED",
                               error_detail=",".join(blockers))
            return {**result, "blocking_codes": blockers}
        return self.db.begin_execution_attempt(
            execution_id=execution_id, token_sha256=token_sha,
            observed_pre_fingerprint=quality["fingerprint"], actor=actor, reason=reason,
            started_at=current.isoformat(timespec="milliseconds"),
        )

    @staticmethod
    def _observed_decision_fingerprint(plan: dict, normalized: dict) -> str:
        picks = sorted(normalized["picks"], key=lambda row: int(row["position"]))
        selected = {
            "season": plan["season"], "gw": int(plan["gw"]),
            "squad_15": [int(row["element"]) for row in picks],
            "starters": [int(row["element"]) for row in picks if int(row["position"]) <= 11],
            "bench_order": [int(row["element"]) for row in picks if int(row["position"]) > 11],
            "captain": next(int(row["element"]) for row in picks if row["is_captain"]),
            "vice_captain": next(
                int(row["element"]) for row in picks if row["is_vice_captain"]
            ),
            "transfers_in": plan["action"]["exact_diff"]["transfers"]["in"],
            "transfers_out": plan["action"]["exact_diff"]["transfers"]["out"],
            "hits": plan["action"]["exact_diff"]["transfers"]["hits"],
            "chip": plan["action"]["exact_diff"]["chip"]["to"],
        }
        return decision_fingerprint(selected)

    def finalize(self, *, execution_id: str, claim_token: str, post_state: dict,
                 actor: str, reason: str, now: datetime | None = None) -> dict:
        """Verifica contra un GET post-reload; un mismatch queda ambiguo y abre P0."""
        normalized, quality = validate_private_state(
            post_state, expected_team_id=self.config.team_id,
        )
        attempt = self.db.execution_attempt(execution_id)
        token_sha = self._assert_token(attempt, claim_token, status="applying")
        self._validate_command_artifact(attempt)
        source = self.db.execution_claim_source(attempt["plan_id"])
        plan = self._load_plan(source["plan"])
        observed = self._observed_decision_fingerprint(plan, normalized)
        expected = str(attempt["expected_post_fingerprint"])
        checks = [
            {"code": "POST_GW_MATCH", "passed": int(normalized["event"]["id"]) == int(plan["gw"]),
             "expected": int(plan["gw"]), "observed": int(normalized["event"]["id"])},
            {"code": "POST_DECISION_FINGERPRINT_MATCH", "passed": observed == expected,
             "expected": expected, "observed": observed},
            {"code": "POST_STATE_VALID", "passed": quality["players"] == 15,
             "expected": 15, "observed": quality["players"]},
            {"code": "POST_OBSERVED_AFTER_APPLY",
             "passed": _parse_time(normalized["observed_at"]) > _parse_time(attempt["started_at"]),
             "expected": f"> {attempt['started_at']}",
             "observed": normalized["observed_at"]},
        ]
        verified = all(row["passed"] for row in checks)
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        evidence = {
            "schema": "mova-execution-evidence-v1", "execution_id": execution_id,
            "plan_id": plan["plan_id"], "observed_at": normalized["observed_at"],
            "verification_checks": checks,
            "private_state_fingerprint": quality["fingerprint"],
        }
        result_sha = sha256_json(evidence)
        target = self.config.artifact_root / "execution-evidence" / plan["cycle_id"] / f"{execution_id}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
        status = "verified" if verified else "ambiguous"
        result = self.db.finish_execution_attempt(
            execution_id=execution_id, token_sha256=token_sha,
            status=status, actor=actor, reason=reason,
            finished_at=current.isoformat(timespec="milliseconds"), detail={
                "checks": checks, "result_sha256": result_sha,
            }, observed_post_fingerprint=observed, evidence_path=str(target),
            evidence_sha256=self._file_sha(target), result_sha256=result_sha,
            error_code=None if verified else "POST_STATE_MISMATCH",
            error_detail=None if verified else "post-reload state no coincide con el plan",
        )
        if verified:
            self.db.finish_job(attempt["job_id"], "completed", output_sha256=result_sha,
                               metrics={"status": status, "verification_checks": len(checks)})
        else:
            self.db.open_incident_once(
                "P0", "Ejecución FPL ambigua", correlation_id=None,
                cycle_id=plan["cycle_id"], job_id=attempt["job_id"],
                detail={"execution_id": execution_id, "plan_id": plan["plan_id"],
                        "result_sha256": result_sha},
            )
            self.db.finish_job(attempt["job_id"], "failed",
                               error_code="POST_STATE_MISMATCH",
                               error_detail="estado post-reload no coincide")
        return {**result, "verification_checks": checks, "result_sha256": result_sha}

    def fail(self, *, execution_id: str, claim_token: str, ambiguous: bool,
             actor: str, reason: str, error_code: str, error_detail: str,
             now: datetime | None = None) -> dict:
        attempt = self.db.execution_attempt(execution_id)
        status = "ambiguous" if ambiguous else "failed"
        token_sha = self._assert_token(
            attempt, claim_token, status="applying" if ambiguous else "claimed"
        )
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        result_sha = sha256_json({"status": status, "error_code": error_code,
                                  "error_detail": error_detail})
        result = self.db.finish_execution_attempt(
            execution_id=execution_id, token_sha256=token_sha,
            status=status, actor=actor, reason=reason,
            finished_at=current.isoformat(timespec="milliseconds"),
            detail={"error_code": error_code}, result_sha256=result_sha,
            error_code=error_code, error_detail=error_detail[:2000],
        )
        if ambiguous:
            plan = self.db.execution_claim_source(attempt["plan_id"])["plan"]
            self.db.open_incident_once(
                "P0", "Ejecución FPL ambigua", cycle_id=plan["cycle_id"],
                job_id=attempt["job_id"], detail={"execution_id": execution_id,
                                                  "error_code": error_code},
            )
        self.db.finish_job(attempt["job_id"], "failed", error_code=error_code,
                           error_detail=error_detail[:2000])
        return result
