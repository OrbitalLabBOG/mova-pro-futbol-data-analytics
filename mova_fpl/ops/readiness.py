"""Gate consolidado, read-only, para promoción de autonomía.

La salud de un proceso no equivale a permiso para actuar. Este contrato junta
evidencia operativa, analítica, estratégica y de ejecución, pero nunca cambia
controles ni concede autoridad por sí mismo.
"""

from __future__ import annotations

from datetime import datetime, timezone

from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB
from mova_fpl.ops.execution import ExecutionService
from mova_fpl.ops.operator import build_status

SCHEMA = "mova-autonomy-readiness-v1"
LEVELS = ("A0", "A1", "A2", "A3")


def _gate(code: str, status: str, summary: str, *, levels: tuple[str, ...],
          observed=None, required=None, source: str, next_action: str) -> dict:
    if status not in {"pass", "pending", "blocked"}:
        raise ValueError(f"estado de gate inválido: {status}")
    return {
        "code": code,
        "status": status,
        "summary": summary,
        "required_for": list(levels),
        "observed": observed,
        "required": required,
        "source": source,
        "next_action": None if status == "pass" else next_action,
    }


def evaluate_readiness(*, operator_status: dict, research_coverage: dict,
                       execution_status: dict, resilience_evidence: dict | None = None,
                       host_recovery_evidence: dict | None = None,
                       snapshot_rejection_evidence: dict | None = None,
                       browser_failure_evidence: dict | None = None,
                       generated_at: str | None = None) -> dict:
    """Evalúa únicamente snapshots ya observados; no ejecuta IO ni mutaciones."""
    gameweek = operator_status.get("gameweek") or {}
    data = operator_status.get("data") or {}
    team = data.get("team_state") or {}
    analytics = operator_status.get("analytics") or {}
    storage = operator_status.get("storage") or {}
    postgres = storage.get("postgres") or {}
    strategy = operator_status.get("strategy") or {}
    operations = operator_status.get("operations") or {}
    runtime = operator_status.get("runtime") or {}
    controls = runtime.get("controls") or {}
    driver = execution_status.get("browser_driver") or {}
    captaincy = driver.get("captaincy") or {}
    lineup = driver.get("lineup") or {}
    r3 = driver.get("r3") or {}
    projections = analytics.get("latest_projection_batches") or []
    target_gw = gameweek.get("gw")
    approved_projection = next(
        (row for row in projections
         if row.get("status") == "approved"
         and (target_gw is None or int(row.get("target_gw", -1)) == int(target_gw))),
        None,
    )
    pg_history = postgres.get("import_history") or {}
    distinct_pg_cycles = int(pg_history.get("distinct_gameweek_cycles") or 0)
    required_research = int(
        (research_coverage.get("policy") or {}).get("minimum_measured_gameweeks") or 3
    )
    resilience = resilience_evidence or {"status": "missing", "checks": 0, "passed": 0}
    resilience_passed = (
        resilience.get("status") == "completed"
        and int(resilience.get("checks") or 0) >= 6
        and int(resilience.get("passed") or 0) == int(resilience.get("checks") or 0)
    )
    host_recovery = host_recovery_evidence or {
        "status": "incomplete", "completed": 0, "required": 2, "scenarios": {},
    }
    host_recovery_passed = (
        host_recovery.get("status") == "completed"
        and int(host_recovery.get("completed") or 0)
        == int(host_recovery.get("required") or 2)
    )
    snapshot_rejection = snapshot_rejection_evidence or {
        "status": "missing", "checks": 0, "passed": 0,
    }
    snapshot_rejection_passed = (
        snapshot_rejection.get("status") == "completed"
        and int(snapshot_rejection.get("checks") or 0) >= 10
        and int(snapshot_rejection.get("passed") or 0)
        == int(snapshot_rejection.get("checks") or 0)
    )
    browser_failure = browser_failure_evidence or {
        "status": "missing", "checks": 0, "passed": 0,
    }
    browser_failure_passed = (
        browser_failure.get("status") == "completed"
        and int(browser_failure.get("checks") or 0) >= 10
        and int(browser_failure.get("passed") or 0)
        == int(browser_failure.get("checks") or 0)
    )

    gates = [
        _gate(
            "RUNTIME_HEALTHY",
            "pass" if operator_status.get("overall_status") == "healthy" else "blocked",
            "runtime consolidado sano",
            levels=("A1", "A2", "A3"), observed=operator_status.get("overall_status"),
            required="healthy", source="mova status",
            next_action="resolver status_reasons e incidentes operativos",
        ),
        _gate(
            "GAMEWEEK_INPUTS_READY",
            "pass" if gameweek.get("cycle_id") and gameweek.get("readiness") == "ready"
            else "pending",
            "ciclo vigente con jornada previa asentada",
            levels=("A1", "A2", "A3"), observed=gameweek.get("readiness"),
            required="ready", source="FPL official event context",
            next_action="esperar settlement oficial y refrescar el ciclo",
        ),
        _gate(
            "PRIVATE_TEAM_STATE_FRESH",
            "pass" if team.get("quality") == "valid" and team.get("squad_size") == 15
            and team.get("age_seconds") is not None
            and team.get("max_age_seconds") is not None
            and int(team["age_seconds"]) <= int(team["max_age_seconds"]) else "blocked",
            "estado autenticado válido, fresco y con 15 jugadores",
            levels=("A1", "A2", "A3"),
            observed={key: team.get(key) for key in (
                "quality", "squad_size", "age_seconds", "max_age_seconds"
            )}, required={"quality": "valid", "squad_size": 15, "fresh": True},
            source="team_state_snapshots",
            next_action="refrescar el estado privado autenticado",
        ),
        _gate(
            "DATA_SERVICE_HEALTHY",
            "pass" if (data.get("service") or {}).get("status") == "healthy" else "blocked",
            "collector autónomo sin fuentes degradadas",
            levels=("A1", "A2", "A3"),
            observed=(data.get("service") or {}).get("status"), required="healthy",
            source="mova data status", next_action="reparar o refrescar fuentes degradadas",
        ),
        _gate(
            "ANALYTICS_SERVICE_HEALTHY",
            "pass" if analytics.get("status") == "healthy" else "blocked",
            "servicio analítico sin alerta de drift",
            levels=("A1", "A2", "A3"), observed=analytics.get("status"),
            required="healthy", source="mova analytics status",
            next_action="resolver drift o ausencia del servicio analítico",
        ),
        _gate(
            "APPROVED_CURRENT_PROJECTION",
            "pass" if approved_projection else "blocked",
            "proyección baseline aprobada para la jornada objetivo",
            levels=("A1", "A2", "A3"),
            observed=(approved_projection or {}).get("batch_id"), required=f"approved gw {target_gw}",
            source="analytics.projection_batches",
            next_action="ejecutar y validar la proyección de la jornada vigente",
        ),
        _gate(
            "STRATEGIC_MANIFEST_PRESENT",
            "pass" if (strategy.get("manifest") or {}).get("content_sha256") else "blocked",
            "manifest estratégico inmutable presente",
            levels=("A1", "A2", "A3"),
            observed=(strategy.get("manifest") or {}).get("manifest_id"), required="manifest",
            source="cycle_manifests", next_action="ejecutar mova strategy prepare",
        ),
        _gate(
            "RESEARCH_EVIDENCE_CALIBRATED",
            "pass" if research_coverage.get("status") == "passed"
            else "blocked" if research_coverage.get("status") == "failed" else "pending",
            "research v2 calibrado en jornadas independientes",
            levels=("A1", "A2", "A3"),
            observed={"status": research_coverage.get("status"),
                      "measured_gameweeks": research_coverage.get("measured_gameweeks"),
                      "passing_gameweeks": research_coverage.get("passing_gameweeks")},
            required={"status": "passed", "minimum_gameweeks": required_research},
            source="mova strategy research coverage",
            next_action="importar briefs v2 válidos hasta completar 3 jornadas medidas",
        ),
        _gate(
            "NO_OPEN_P0_P1",
            "pass" if not [row for row in operations.get("open_incidents") or []
                           if row.get("severity") in {"P0", "P1"}] else "blocked",
            "sin incidentes P0/P1 abiertos",
            levels=("A1", "A2", "A3"),
            observed=len(operations.get("open_incidents") or []), required=0,
            source="incidents", next_action="resolver incidentes críticos antes de promover",
        ),
        _gate(
            "RESILIENCE_DRILL_PROVEN",
            "pass" if resilience_passed else
            "blocked" if resilience.get("status") == "failed" else "pending",
            "scheduler P0, delivery, dedup y recovery ensayados",
            levels=("A1", "A2", "A3"),
            observed={key: resilience.get(key) for key in (
                "job_id", "status", "checks", "passed", "finished_at", "output_sha256"
            )},
            required={"status": "completed", "checks": ">=6", "all_passed": True},
            source="job_runs.resilience_drill",
            next_action="ejecutar mova drill resilience con una clave idempotente nueva",
        ),
        _gate(
            "HOST_RECOVERY_DRILLS_PROVEN",
            "pass" if host_recovery_passed else
            "blocked" if host_recovery.get("status") == "failed" else "pending",
            "caídas reales de API y PostgreSQL recuperadas sin mutar FPL",
            levels=("A1", "A2", "A3"),
            observed={
                "status": host_recovery.get("status"),
                "completed": host_recovery.get("completed"),
                "required": host_recovery.get("required"),
                "scenarios": host_recovery.get("scenarios") or {},
            },
            required={"status": "completed", "scenarios": [
                "api_recovery", "postgres_recovery",
            ]},
            source="job_runs.host_recovery_drill",
            next_action="ejecutar los drills host allowlisted de API y PostgreSQL",
        ),
        _gate(
            "SNAPSHOT_REJECTION_PROVEN",
            "pass" if snapshot_rejection_passed else
            "blocked" if snapshot_rejection.get("status") == "failed" else "pending",
            "snapshots alterados, corruptos y paths inseguros rechazados",
            levels=("A1", "A2", "A3"),
            observed={key: snapshot_rejection.get(key) for key in (
                "job_id", "status", "checks", "passed", "finished_at", "output_sha256"
            )},
            required={"status": "completed", "checks": ">=10", "all_passed": True},
            source="job_runs.snapshot_rejection_drill",
            next_action="ejecutar mova drill snapshot con una clave idempotente nueva",
        ),
        _gate(
            "BROWSER_FAILURE_DRILL_PROVEN",
            "pass" if browser_failure_passed else
            "blocked" if browser_failure.get("status") == "failed" else "pending",
            "deriva DOM y guardado post-commit ambiguo fallan cerrados",
            levels=("A1", "A2", "A3"),
            observed={key: browser_failure.get(key) for key in (
                "job_id", "status", "checks", "passed", "finished_at", "output_sha256"
            )},
            required={"status": "completed", "checks": ">=10", "all_passed": True},
            source="job_runs.browser_failure_drill",
            next_action="ejecutar mova drill browser-failure con clave idempotente nueva",
        ),
        _gate(
            "CAPTAINCY_DRIVER_PROVEN",
            "pass" if captaincy.get("contract") == "implemented"
            and captaincy.get("host_entrypoint_enabled") is True
            and int(captaincy.get("observed_rehearsals") or 0)
            >= int(captaincy.get("required_rehearsals") or 3) else "pending",
            "driver R2 de capitanía implementado y ensayado",
            levels=("A2", "A3"),
            observed={key: captaincy.get(key) for key in (
                "contract", "host_entrypoint_enabled", "observed_rehearsals"
            )}, required={"contract": "implemented", "host_entrypoint_enabled": True,
                         "rehearsals": int(captaincy.get("required_rehearsals") or 3)},
            source="browser driver capability ledger",
            next_action="completar tres rehearsals R2 verificables de capitanía",
        ),
        _gate(
            "LINEUP_DRIVER_PROVEN",
            "pass" if lineup.get("contract") == "implemented"
            and lineup.get("host_entrypoint_enabled") is True
            and int(lineup.get("observed_rehearsals") or 0)
            >= int(lineup.get("required_rehearsals") or 3) else "pending",
            "driver R2 de XI/banca implementado y ensayado",
            levels=("A2", "A3"),
            observed={key: lineup.get(key) for key in (
                "contract", "host_entrypoint_enabled", "observed_rehearsals"
            )}, required={"contract": "implemented", "host_entrypoint_enabled": True,
                         "rehearsals": int(lineup.get("required_rehearsals") or 3)},
            source="browser driver capability ledger",
            next_action="completar tres rehearsals R2 y promover el entrypoint de lineup",
        ),
        _gate(
            "R3_DRIVER_PROVEN",
            "pass" if r3.get("contract") == "implemented"
            and r3.get("host_entrypoint_enabled") is True
            and int(r3.get("observed_rehearsals") or 0)
            >= int(r3.get("required_rehearsals") or 3) else
            "pending" if r3.get("contract") == "implemented" else "blocked",
            "driver R3 para transferencias/chips implementado y ensayado",
            levels=("A3",), observed=r3,
            required={"contract": "implemented", "host_entrypoint_enabled": True,
                      "rehearsals": int(r3.get("required_rehearsals") or 3)},
            source="browser driver capability ledger",
            next_action="completar tres rehearsals R3 y habilitar el entrypoint de forma explícita",
        ),
        _gate(
            "POSTGRES_SHADOW_PARITY",
            "pass" if postgres.get("status") == "healthy"
            and (postgres.get("read_parity") or {}).get("status") == "pass"
            and postgres.get("import_fresh") is True else "blocked",
            "shadow PostgreSQL fresco y con paridad",
            levels=(), observed={"status": postgres.get("status"),
                                 "parity": (postgres.get("read_parity") or {}).get("status"),
                                 "fresh": postgres.get("import_fresh")},
            required={"status": "healthy", "parity": "pass", "fresh": True},
            source="mova postgres status", next_action="sincronizar y verificar PostgreSQL shadow",
        ),
        _gate(
            "POSTGRES_ROLE_SEPARATION",
            "pass" if (postgres.get("role_separation") or {}).get("status") == "pass"
            else "blocked",
            "identidades PostgreSQL runtime separadas y verificadas",
            levels=(),
            observed=(postgres.get("role_separation") or {}).get("status"),
            required="pass", source="mova postgres roles",
            next_action="provisionar y verificar identidades app/readonly separadas",
        ),
        _gate(
            "POSTGRES_THREE_GAMEWEEK_CYCLES",
            "pass" if distinct_pg_cycles >= 3 else "pending",
            "tres ciclos de gameweek importados al shadow",
            levels=(), observed=distinct_pg_cycles, required=3,
            source="mova_meta.import_runs",
            next_action="acumular imports completos de tres GWs; reintentos de una GW no cuentan",
        ),
    ]

    eligible = "A0"
    for candidate in LEVELS[1:]:
        required = [gate for gate in gates if candidate in gate["required_for"]]
        if all(gate["status"] == "pass" for gate in required):
            eligible = candidate
        else:
            break
    counts = {state: sum(gate["status"] == state for gate in gates)
              for state in ("pass", "pending", "blocked")}
    current_level = str(controls.get("action_level") or "A0")
    activation = {
        "current_action_level": current_level,
        "technical_eligible_level": eligible,
        "promotion_is_automatic": False,
        "writes_enabled": controls.get("browser_writes") is True,
        "kill_switch": controls.get("kill_switch"),
        "compliance_gate": controls.get("compliance_gate"),
        "mode": controls.get("mode"),
        "activation_blockers": [
            code for code, passed in (
                ("EXPLICIT_PROMOTION_REQUIRED", False),
                ("COMPLIANCE_NOT_APPROVED", controls.get("compliance_gate") == "approved"),
                ("KILL_SWITCH_ON", controls.get("kill_switch") is False),
                ("BROWSER_WRITES_DISABLED", controls.get("browser_writes") is True),
                ("MODE_NOT_AUTONOMOUS", controls.get("mode") == "autonomous"),
            ) if not passed
        ],
    }
    unmet = [gate for gate in gates if gate["status"] != "pass"]
    return {
        "schema": SCHEMA,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "season": runtime.get("season"),
        "cycle_id": gameweek.get("cycle_id"),
        "gw": target_gw,
        "overall_status": "ready" if eligible == "A3" and not unmet else "not_ready",
        "summary": {**counts, "total": len(gates)},
        "activation": activation,
        "gates": gates,
        "next_actions": [
            {"code": gate["code"], "status": gate["status"],
             "next_action": gate["next_action"]}
            for gate in unmet
        ],
    }


def build_readiness(config: RuntimeConfig, db: OpsDB, *,
                    now: datetime | None = None) -> dict:
    current = now or datetime.now(timezone.utc)
    status = build_status(config, db, now=current)
    return evaluate_readiness(
        operator_status=status,
        research_coverage=db.research_coverage(),
        execution_status=ExecutionService(config, db).status(),
        resilience_evidence=db.resilience_drill_status(),
        host_recovery_evidence=db.host_recovery_drill_status(),
        snapshot_rejection_evidence=db.snapshot_rejection_drill_status(),
        browser_failure_evidence=db.browser_failure_drill_status(),
        generated_at=current.astimezone(timezone.utc).isoformat(timespec="seconds"),
    )


def prometheus(report: dict) -> str:
    level = (report.get("activation") or {}).get("technical_eligible_level", "A0")
    summary = report.get("summary") or {}
    lines = [
        "# HELP mova_autonomy_readiness_up Consolidated readiness contract availability.",
        "# TYPE mova_autonomy_readiness_up gauge",
        "mova_autonomy_readiness_up 1",
        "# HELP mova_autonomy_technical_eligible_level Highest technically eligible autonomy level.",
        "# TYPE mova_autonomy_technical_eligible_level gauge",
        *[f'mova_autonomy_technical_eligible_level{{level="{name}"}} '
          f'{1 if name == level else 0}' for name in LEVELS],
        "# HELP mova_autonomy_readiness_gates Readiness gates by state.",
        "# TYPE mova_autonomy_readiness_gates gauge",
        *[f'mova_autonomy_readiness_gates{{status="{state}"}} '
          f'{int(summary.get(state) or 0)}' for state in ("pass", "pending", "blocked")],
        "",
    ]
    return "\n".join(lines)
