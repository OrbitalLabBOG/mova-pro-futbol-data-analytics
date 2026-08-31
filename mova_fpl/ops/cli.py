"""Punto de entrada único del control plane MOVA."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from mova_fpl.ops.api import serve
from mova_fpl.ops.backup import create_backup
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB, new_id, sha256_json
from mova_fpl.ops.logging import configure_logging
from mova_fpl.ops.operator import (
    build_doctor, build_safety, build_status, render_doctor, render_status,
)
from mova_fpl.ops.tick import LockBusy, TickRunner


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="mova")
    root.add_argument("--log-level", default="INFO")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate")
    tick = commands.add_parser("tick")
    tick.add_argument("--force", action="store_true",
                      help="omite sólo la cadencia; conserva locks, gates y auditoría")
    tick.add_argument("--actor")
    tick.add_argument("--reason")
    tick.add_argument("--idempotency-key")
    commands.add_parser("serve")
    commands.add_parser("check")
    collect = commands.add_parser("collect", help="servicio autónomo de datos")
    collect.add_argument("source", choices=("all", "fpl", "odds", "schedule", "events"),
                         default="all", nargs="?")
    collect.add_argument("--force", action="store_true")
    collect.add_argument("--actor")
    collect.add_argument("--reason")
    collect.add_argument("--idempotency-key")
    data = commands.add_parser("data", help="estado y cobertura del data plane")
    data_commands = data.add_subparsers(dest="data_command", required=True)
    data_commands.add_parser("status")
    data_commands.add_parser("coverage")
    analytics = commands.add_parser("analytics", help="proyección, scorecards y drift")
    analytics_commands = analytics.add_subparsers(dest="analytics_command", required=True)
    analytics_commands.add_parser("run", help="proyecta y reconcilia jornadas cerradas")
    analytics_commands.add_parser("project", help="sella proyección pre-deadline")
    analytics_commands.add_parser("reconcile", help="evalúa GWs con data_checked")
    analytics_status = analytics_commands.add_parser("status", help="estado y scorecards")
    analytics_status.add_argument("--limit", type=int, default=20)
    model = commands.add_parser("model", help="train, predict, explain y evaluate tipados")
    model_commands = model.add_subparsers(dest="model_command", required=True)
    model_commands.add_parser("status", help="bundle activo e interfaces disponibles")
    model_train = model_commands.add_parser(
        "train", help="entrena un bundle candidato sin activarlo"
    )
    model_train.add_argument("--version", required=True)
    model_train.add_argument("--holdout", default="2025-26")
    model_explain = model_commands.add_parser(
        "explain", help="explica una proyección sellada por jugador"
    )
    model_explain.add_argument("--batch-id", required=True)
    model_explain.add_argument("--element", type=int, required=True)
    audited_model_commands = []
    for operation, help_text in (
        ("predict", "crea o reutiliza una proyección inmutable"),
        ("evaluate", "reconcilia scorecards finales pendientes"),
    ):
        audited_model_commands.append(model_commands.add_parser(operation, help=help_text))
    for command in [model_train, *audited_model_commands]:
        command.add_argument("--actor", required=True)
        command.add_argument("--reason", required=True)
        command.add_argument("--idempotency-key", required=True)
    review = commands.add_parser("review", help="settlement y feedback por gameweek")
    review_commands = review.add_subparsers(dest="review_command", required=True)
    review_gw = review_commands.add_parser("gw", help="cierra una GW asentada")
    review_gw.add_argument("--package", required=True, help="package manual versionado")
    review_gw.add_argument("--actor", required=True)
    review_gw.add_argument("--reason", required=True)
    review_gw.add_argument("--idempotency-key", required=True)
    review_status = review_commands.add_parser(
        "status", help="consulta settlement, feedback y propuestas"
    )
    review_status.add_argument("--gw", type=int, required=True)
    review_status.add_argument("--season")
    review_auto = review_commands.add_parser(
        "auto", help="clasifica causas sobre settlement + scorecard final"
    )
    review_auto.add_argument("--gw", type=int, required=True)
    review_auto.add_argument("--actor", required=True)
    review_auto.add_argument("--reason", required=True)
    review_auto.add_argument("--idempotency-key", required=True)
    improve = commands.add_parser(
        "improve", help="memoria, costos y gate de mejora continua"
    )
    improve_commands = improve.add_subparsers(dest="improve_command", required=True)
    improve_status = improve_commands.add_parser(
        "status", help="consulta propuestas, lecciones y uso/costo"
    )
    improve_status.add_argument("--season")
    improve_status.add_argument("--gw", type=int)
    transition = improve_commands.add_parser(
        "transition", help="evalúa una propuesta sin aplicar cambios al runtime"
    )
    transition.add_argument("--proposal-id", required=True)
    transition.add_argument("--to", choices=("testing", "accepted", "rejected"), required=True)
    transition.add_argument("--evidence", required=True)
    transition.add_argument("--actor", required=True)
    transition.add_argument("--reason", required=True)
    transition.add_argument("--idempotency-key", required=True)
    release = improve_commands.add_parser(
        "release", help="promueve bundles de modelos con shadow y rollback"
    )
    release_commands = release.add_subparsers(dest="release_command", required=True)
    release_commands.add_parser("status", help="estado, eventos y puntero activo")
    release_prepare = release_commands.add_parser(
        "prepare", help="sella un candidato ligado a una propuesta aceptada"
    )
    release_prepare.add_argument("--proposal-id", required=True)
    release_prepare.add_argument("--manifest", required=True)
    for command in (release_prepare,):
        command.add_argument("--actor", required=True)
        command.add_argument("--reason", required=True)
        command.add_argument("--idempotency-key", required=True)
    for operation in ("shadow", "promote", "rollback"):
        command = release_commands.add_parser(operation)
        command.add_argument("--release-id", required=True)
        command.add_argument("--actor", required=True)
        command.add_argument("--reason", required=True)
        command.add_argument("--idempotency-key", required=True)
    cost = commands.add_parser("cost", help="presupuestos y uso de inferencia")
    cost_commands = cost.add_subparsers(dest="cost_command", required=True)
    cost_report = cost_commands.add_parser("report", help="uso por GW y mes")
    cost_report.add_argument("--season")
    cost_report.add_argument("--gw", type=int)
    cost_report.add_argument("--month", help="mes UTC YYYY-MM")
    strategy = commands.add_parser(
        "strategy", help="plan, manifiesto e investigación verificable"
    )
    strategy_commands = strategy.add_subparsers(dest="strategy_command", required=True)
    strategy_commands.add_parser("status", help="estado estratégico del ciclo vigente")
    strategy_commands.add_parser("prepare", help="sella el manifiesto del ciclo")
    plan = strategy_commands.add_parser("plan", help="activa un plan de temporada")
    plan.add_argument("--file", required=True)
    plan.add_argument("--actor", required=True)
    plan.add_argument("--reason", required=True)
    research = strategy_commands.add_parser("research", help="opera la cola de investigación")
    research.add_argument("operation", choices=("due", "coverage", "enqueue", "import"))
    research.add_argument("--force", action="store_true")
    research.add_argument("--actor")
    research.add_argument("--reason")
    research.add_argument("--idempotency-key")
    deliberate = strategy_commands.add_parser(
        "deliberate", help="opera Strategist + Critic sobre el último envelope"
    )
    deliberate.add_argument("operation", choices=("status", "enqueue", "import"))
    execute = commands.add_parser(
        "execute", help="plan de ejecución y preflight determinista"
    )
    execute_commands = execute.add_subparsers(dest="execute_command", required=True)
    execute_commands.add_parser("status", help="consulta planes y gates recientes")
    rehearsal = execute_commands.add_parser(
        "rehearsal", help="registra evidencia sellada de un ensayo browser read-only"
    )
    rehearsal.add_argument("--file", required=True)
    rehearsal.add_argument("--actor", required=True)
    rehearsal.add_argument("--reason", required=True)
    rehearsal.add_argument("--idempotency-key", required=True)
    captaincy_probe = execute_commands.add_parser(
        "rehearsal-captaincy-probe",
        help="sella e importa un probe vivo sanitizado de capitanía",
    )
    captaincy_probe.add_argument("--source", required=True)
    captaincy_probe.add_argument("--cycle-id", required=True)
    captaincy_probe.add_argument("--actor", required=True)
    captaincy_probe.add_argument("--reason", required=True)
    captaincy_probe.add_argument("--idempotency-key", required=True)
    capability_probe = execute_commands.add_parser(
        "rehearsal-capability-probe",
        help="sella e importa un probe vivo sanitizado de lineup o R3",
    )
    capability_probe.add_argument("--source", required=True)
    capability_probe.add_argument("--cycle-id", required=True)
    capability_probe.add_argument("--capability", choices=("lineup", "r3"), required=True)
    capability_probe.add_argument("--actor", required=True)
    capability_probe.add_argument("--reason", required=True)
    capability_probe.add_argument("--idempotency-key", required=True)
    preflight = execute_commands.add_parser(
        "preflight", help="sella el diff y evalúa autorización sin operar el browser"
    )
    preflight.add_argument("--actor", required=True)
    preflight.add_argument("--reason", required=True)
    preflight.add_argument("--idempotency-key", required=True)
    prepare_execution = execute_commands.add_parser(
        "prepare", help="reserva una ejecución apply-once autorizada"
    )
    prepare_execution.add_argument("--plan-id", required=True)
    prepare_execution.add_argument("--adapter", choices=("disabled", "browser"),
                                   default="disabled")
    prepare_execution.add_argument("--actor", required=True)
    prepare_execution.add_argument("--reason", required=True)
    prepare_execution.add_argument("--idempotency-key", required=True)
    claim_execution = execute_commands.add_parser(
        "claim", help="concede un lease único y emite el token sólo por stdout"
    )
    claim_execution.add_argument("--execution-id", required=True)
    claim_execution.add_argument("--actor", required=True)
    claim_execution.add_argument("--reason", required=True)
    claim_execution.add_argument("--lease-seconds", type=int, default=300)
    ui_plan = execute_commands.add_parser(
        "ui-plan", help="compila el plan DOM contra pre-state y probe sanitizado"
    )
    ui_plan.add_argument("--execution-id", required=True)
    ui_plan.add_argument("--pre-state", required=True)
    ui_plan.add_argument("--dom-probe", required=True)
    begin_execution = execute_commands.add_parser(
        "begin", help="marca el límite de write ambiguity después de validar pre-state"
    )
    begin_execution.add_argument("--execution-id", required=True)
    begin_execution.add_argument("--pre-state", required=True)
    begin_execution.add_argument("--actor", required=True)
    begin_execution.add_argument("--reason", required=True)
    begin_execution.add_argument("--claim-token-stdin", action="store_true", required=True)
    finalize_execution = execute_commands.add_parser(
        "finalize", help="verifica el GET post-reload y sella evidencia"
    )
    finalize_execution.add_argument("--execution-id", required=True)
    finalize_execution.add_argument("--post-state", required=True)
    finalize_execution.add_argument("--actor", required=True)
    finalize_execution.add_argument("--reason", required=True)
    finalize_execution.add_argument("--claim-token-stdin", action="store_true", required=True)
    fail_execution = execute_commands.add_parser(
        "fail", help="cierra fallo pre-write o write ambiguo sin reintento"
    )
    fail_execution.add_argument("--execution-id", required=True)
    fail_execution.add_argument("--classification", choices=("failed", "ambiguous"),
                                required=True)
    fail_execution.add_argument("--error-code", required=True)
    fail_execution.add_argument("--error-detail", required=True)
    fail_execution.add_argument("--actor", required=True)
    fail_execution.add_argument("--reason", required=True)
    fail_execution.add_argument("--claim-token-stdin", action="store_true", required=True)
    status = commands.add_parser("status", help="estado operativo consolidado")
    status.add_argument("--json", action="store_true", dest="as_json")
    commands.add_parser("safety", help="resumen read-only: ¿es seguro esperar?")
    alerts = commands.add_parser("alerts", help="entrega y reconocimiento de alertas")
    alert_commands = alerts.add_subparsers(dest="alerts_command", required=True)
    alert_commands.add_parser("status", help="estado sanitizado del outbox")
    alert_dispatch = alert_commands.add_parser("dispatch", help="entrega alertas vencidas")
    alert_dispatch.add_argument("--limit", type=int, default=20)
    alert_ack = alert_commands.add_parser("acknowledge", help="reconoce un incidente")
    alert_ack.add_argument("--incident-id", required=True)
    alert_ack.add_argument("--actor", required=True)
    alert_ack.add_argument("--reason", required=True)
    alert_retry = alert_commands.add_parser("retry", help="reabre un evento dead")
    alert_retry.add_argument("--outbox-id", required=True)
    alert_retry.add_argument("--actor", required=True)
    alert_retry.add_argument("--reason", required=True)
    maintenance = commands.add_parser("maintenance", help="mantenimiento seguro de artefactos")
    maintenance_commands = maintenance.add_subparsers(
        dest="maintenance_command", required=True
    )
    cleanup = maintenance_commands.add_parser(
        "cleanup", help="lista transitorios; sólo borra con --apply"
    )
    cleanup.add_argument("--older-than-seconds", type=int, default=86400)
    cleanup.add_argument("--apply", action="store_true")
    cleanup.add_argument("--actor")
    cleanup.add_argument("--reason")
    cleanup.add_argument("--idempotency-key")
    readiness = commands.add_parser(
        "readiness", help="gate consolidado de promoción de autonomía"
    )
    readiness.add_argument("--require-level", choices=("A0", "A1", "A2", "A3"))
    doctor = commands.add_parser("doctor", help="diagnóstico verificable del runtime")
    doctor.add_argument("--json", action="store_true", dest="as_json")
    doctor.add_argument("--no-network", action="store_true",
                        help="omite el GET de salud contra la API pública FPL")
    team_state = commands.add_parser("ingest-team-state")
    team_state.add_argument("--file", default="-", help="JSON sanitizado; '-' lee stdin")
    team_state.add_argument("--trigger", choices=("scheduled", "forced"),
                            default="scheduled")
    commands.add_parser("private-state-due")
    watchdog = commands.add_parser("watchdog")
    watchdog.add_argument("--max-age-seconds", type=int, default=1200)
    drill = commands.add_parser("drill", help="rehearsals herméticos de resiliencia")
    drill_commands = drill.add_subparsers(dest="drill_command", required=True)
    resilience = drill_commands.add_parser(
        "resilience", help="P0 scheduler, dedup, delivery y recovery"
    )
    resilience.add_argument("--actor", required=True)
    resilience.add_argument("--reason", required=True)
    resilience.add_argument("--idempotency-key", required=True)
    host_drill = drill_commands.add_parser(
        "import-host", help="valida e importa evidencia allowlisted del host"
    )
    host_drill.add_argument("--file", required=True)
    host_drill.add_argument("--actor", required=True)
    host_drill.add_argument("--reason", required=True)
    host_drill.add_argument("--idempotency-key", required=True)
    host_status = drill_commands.add_parser(
        "host-status", help="consulta idempotencia antes de mutar un servicio host"
    )
    host_status.add_argument("--idempotency-key", required=True)
    backup = commands.add_parser("backup")
    backup.add_argument("--retention-days", type=int, default=35)
    backup.add_argument("--force", action="store_true",
                        help="crea captura adicional aunque exista backup en la hora")
    backup.add_argument("--actor")
    backup.add_argument("--reason")
    backup.add_argument("--idempotency-key")
    control = commands.add_parser("control")
    control.add_argument("key")
    control.add_argument("value", help="valor JSON, por ejemplo false o \"shadow\"")
    control.add_argument("--actor", required=True)
    control.add_argument("--reason", required=True)
    postgres = commands.add_parser("postgres", help="store PostgreSQL shadow HV1-02")
    postgres_commands = postgres.add_subparsers(dest="postgres_command", required=True)
    postgres_commands.add_parser("migrate", help="aplica migraciones inmutables")
    pg_import = postgres_commands.add_parser("import", help="importa snapshots SQLite")
    pg_import.add_argument("--actor", required=True)
    pg_import.add_argument("--reason", required=True)
    pg_import.add_argument("--idempotency-key", required=True)
    postgres_commands.add_parser("status", help="estado del store shadow")
    postgres_commands.add_parser("verify", help="revalida artefactos y conteos")
    postgres_commands.add_parser(
        "sync", help="import idempotente semanal del ciclo vigente"
    )
    pg_drill = postgres_commands.add_parser(
        "drill", help="ensaya cutover/rollback del read-path sin cambiar el writer"
    )
    pg_drill.add_argument("--actor", required=True)
    pg_drill.add_argument("--reason", required=True)
    pg_drill.add_argument("--idempotency-key", required=True)
    pg_roles = postgres_commands.add_parser(
        "roles", help="provisiona LOGIN app/readonly y verifica mínimos privilegios"
    )
    pg_roles.add_argument("--actor", required=True)
    pg_roles.add_argument("--reason", required=True)
    pg_roles.add_argument("--idempotency-key", required=True)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    configure_logging(args.log_level)
    config = RuntimeConfig.from_env()
    if args.command != "doctor":
        config.validate()
    if args.command == "postgres":
        from mova_fpl.postgres.importer import import_shadow, sync_shadow, verify_shadow
        from mova_fpl.postgres.store import migrate as postgres_migrate
        from mova_fpl.postgres.store import status as postgres_status

        config.validate_postgres()
        if args.postgres_command == "migrate":
            payload = postgres_migrate(config)
        elif args.postgres_command == "import":
            payload = import_shadow(
                config, actor=args.actor, reason=args.reason,
                idempotency_key=args.idempotency_key,
            )
        elif args.postgres_command == "status":
            payload = postgres_status(config)
        elif args.postgres_command == "sync":
            payload = sync_shadow(config)
        elif args.postgres_command == "drill":
            from mova_fpl.ops.postgres_cutover import run_cutover_drill

            db = OpsDB(config.ops_db, minimum_version=config.sqlite_min_version)
            payload = run_cutover_drill(
                config, db, actor=args.actor, reason=args.reason,
                idempotency_key=args.idempotency_key,
            )
        elif args.postgres_command == "roles":
            from mova_fpl.ops.postgres_roles import run_role_provision

            db = OpsDB(config.ops_db, minimum_version=config.sqlite_min_version)
            payload = run_role_provision(
                config, db, actor=args.actor, reason=args.reason,
                idempotency_key=args.idempotency_key,
            )
        else:
            payload = verify_shadow(config)
        print(json.dumps(payload, ensure_ascii=False, default=str))
        return 1 if payload.get("status") in {"fail", "failed", "degraded"} else 0

    if args.command == "data":
        from mova_fpl.ops.collector.store import CollectorStore, publish_coverage

        config.validate_postgres()
        store = CollectorStore(config)
        payload = (store.coverage() if args.data_command == "coverage" else store.status())
        if args.data_command == "coverage":
            publish_coverage(config, payload)
        print(json.dumps(payload, ensure_ascii=False, default=str))
        return 2 if payload.get("status") in {"degraded", "incomplete"} else 0

    if args.command == "analytics":
        from mova_fpl.ops.analytics_service import AnalyticsService
        from mova_fpl.ops.analytics_store import AnalyticsStore, publish_status

        config.validate_postgres()
        if args.analytics_command == "status":
            full = AnalyticsStore(config).status(limit=100)
            publish_status(config, full)
            payload = {**full,
                       "latest_scorecards": full["latest_scorecards"][:max(1, min(args.limit, 100))],
                       "latest_projection_batches": full["latest_projection_batches"][
                           :max(1, min(args.limit, 100))]}
        else:
            db = OpsDB(config.ops_db, minimum_version=config.sqlite_min_version)
            payload = AnalyticsService(config, db).run(args.analytics_command)
        print(json.dumps(payload, ensure_ascii=False, default=str))
        return 2 if payload.get("status") in {"degraded", "alert"} else 0

    if args.command == "model":
        from mova_fpl.ops.model_service import ModelOpsService

        db = OpsDB(config.ops_db, minimum_version=config.sqlite_min_version)
        service = ModelOpsService(config, db)
        if args.model_command == "status":
            config.validate_postgres()
            payload = service.status()
        elif args.model_command == "train":
            payload = service.train(
                version=args.version, holdout=args.holdout, actor=args.actor,
                reason=args.reason, idempotency_key=args.idempotency_key,
            )
        elif args.model_command == "explain":
            config.validate_postgres()
            payload = service.explain(batch_id=args.batch_id, element=args.element)
        else:
            config.validate_postgres()
            payload = getattr(service, args.model_command)(
                actor=args.actor, reason=args.reason,
                idempotency_key=args.idempotency_key,
            )
        print(json.dumps(payload, ensure_ascii=False, default=str))
        return 2 if payload.get("status") in {"degraded", "alert"} else 0

    if args.command == "review":
        db = OpsDB(config.ops_db, minimum_version=config.sqlite_min_version)
        if args.review_command == "status":
            payload = db.gameweek_review_status(args.season or config.season, args.gw)
        elif args.review_command == "auto":
            from mova_fpl.ops.causal_review import CausalReviewerService

            config.validate_postgres()
            payload = CausalReviewerService(config, db).run(
                gw=args.gw, actor=args.actor, reason=args.reason,
                idempotency_key=args.idempotency_key,
            )
        else:
            from pathlib import Path
            from mova_fpl.ops.review import GameweekReviewService

            config.validate_postgres()
            payload = GameweekReviewService(config, db).run(
                package_path=Path(args.package), actor=args.actor, reason=args.reason,
                idempotency_key=args.idempotency_key,
            )
        print(json.dumps(payload, ensure_ascii=False, default=str))
        return 0

    if args.command == "improve":
        from pathlib import Path
        from mova_fpl.ops.improvement import ContinuousImprovementService

        db = OpsDB(config.ops_db, minimum_version=config.sqlite_min_version)
        service = ContinuousImprovementService(db)
        if args.improve_command == "status":
            payload = service.status(season=args.season, gw=args.gw)
        elif args.improve_command == "transition":
            payload = service.transition(
                proposal_id=args.proposal_id, to_status=args.to,
                evidence_path=Path(args.evidence), actor=args.actor,
                reason=args.reason, idempotency_key=args.idempotency_key,
            )
        else:
            from mova_fpl.ops.model_release import ModelReleaseService

            release = ModelReleaseService(config, db)
            if args.release_command == "status":
                payload = release.status()
            elif args.release_command == "prepare":
                payload = release.prepare(
                    proposal_id=args.proposal_id, manifest_path=Path(args.manifest),
                    actor=args.actor, reason=args.reason,
                    idempotency_key=args.idempotency_key,
                )
            else:
                payload = getattr(release, args.release_command)(
                    release_id=args.release_id, actor=args.actor, reason=args.reason,
                    idempotency_key=args.idempotency_key,
                )
        print(json.dumps(payload, ensure_ascii=False, default=str))
        return 0

    if args.command == "cost":
        db = OpsDB(config.ops_db, minimum_version=config.sqlite_min_version)
        db.migrate()
        payload = db.cost_report(
            config.agent_budget_policy(), season=args.season or config.season,
            gw=args.gw, month=args.month,
        )
        print(json.dumps(payload, ensure_ascii=False, default=str))
        return 2 if any(payload[key]["status"] == "exceeded"
                        for key in ("gameweek", "month")) else 0

    if args.command == "strategy":
        from pathlib import Path
        from mova_fpl.ops.strategy import StrategicContextService

        db = OpsDB(config.ops_db, minimum_version=config.sqlite_min_version)
        service = StrategicContextService(config, db)
        if args.strategy_command == "status":
            payload = db.strategic_status()
        elif args.strategy_command == "prepare":
            payload = service.prepare()
        elif args.strategy_command == "plan":
            payload = service.activate_plan(
                json.loads(Path(args.file).read_text(encoding="utf-8")),
                actor=args.actor, reason=args.reason,
            )
        elif args.strategy_command == "deliberate":
            from mova_fpl.ops.deliberation import DecisionDeliberationService

            deliberation = DecisionDeliberationService(config, db)
            if args.operation == "status":
                payload = db.deliberation_status()
            elif args.operation == "enqueue":
                payload = deliberation.enqueue()
                print(json.dumps(payload, ensure_ascii=False, default=str))
                return 75 if payload.get("status") in {
                    "skipped", "accepted", "review_required", "blocked", "rejected"
                } else 0
            else:
                payload = deliberation.import_ready()
        elif args.operation == "due":
            payload = service.due()
            print(json.dumps(payload, ensure_ascii=False, default=str))
            return 0 if payload["due"] else 75
        elif args.operation == "coverage":
            payload = db.research_coverage()
        elif args.operation == "enqueue":
            if args.force and not all((args.actor, args.reason, args.idempotency_key)):
                raise SystemExit(
                    "strategy research enqueue --force exige --actor, --reason "
                    "e --idempotency-key"
                )
            payload = service.enqueue(
                force=args.force, actor=args.actor or "mova-research",
                reason=args.reason, idempotency_key=args.idempotency_key,
            )
            print(json.dumps(payload, ensure_ascii=False, default=str))
            return 75 if payload.get("status") == "skipped" else 0
        else:
            payload = service.import_ready()
        print(json.dumps(payload, ensure_ascii=False, default=str))
        return 0

    if args.command == "execute":
        from pathlib import Path
        from mova_fpl.ops.execution import ExecutionService

        db = OpsDB(config.ops_db, minimum_version=config.sqlite_min_version)
        service = ExecutionService(config, db)
        if args.execute_command == "status":
            payload = service.status()
        elif args.execute_command == "rehearsal":
            payload = service.record_rehearsal(
                evidence_file=Path(args.file), actor=args.actor, reason=args.reason,
                idempotency_key=args.idempotency_key,
            )
        elif args.execute_command == "rehearsal-captaincy-probe":
            payload = service.record_captaincy_probe(
                source_file=Path(args.source), cycle_id=args.cycle_id, actor=args.actor,
                reason=args.reason, idempotency_key=args.idempotency_key,
            )
        elif args.execute_command == "rehearsal-capability-probe":
            payload = service.record_capability_probe(
                source_file=Path(args.source), cycle_id=args.cycle_id,
                capability=args.capability, actor=args.actor, reason=args.reason,
                idempotency_key=args.idempotency_key,
            )
        elif args.execute_command == "preflight":
            payload = service.preflight(
                actor=args.actor, reason=args.reason,
                idempotency_key=args.idempotency_key,
            )
        elif args.execute_command == "prepare":
            payload = service.prepare(
                plan_id=args.plan_id, adapter=args.adapter, actor=args.actor,
                reason=args.reason, idempotency_key=args.idempotency_key,
            )
        elif args.execute_command == "claim":
            payload = service.claim(
                execution_id=args.execution_id, actor=args.actor, reason=args.reason,
                lease_seconds=args.lease_seconds,
            )
        elif args.execute_command == "ui-plan":
            payload = service.compile_ui_plan(
                execution_id=args.execution_id,
                pre_state=json.loads(Path(args.pre_state).read_text(encoding="utf-8")),
                dom_probe=json.loads(Path(args.dom_probe).read_text(encoding="utf-8")),
            )
        else:
            claim_token = sys.stdin.read().strip()
            if not claim_token:
                raise SystemExit("claim token requerido exclusivamente por stdin")
            if args.execute_command == "begin":
                payload = service.begin(
                    execution_id=args.execution_id, claim_token=claim_token,
                    pre_state=json.loads(Path(args.pre_state).read_text(encoding="utf-8")),
                    actor=args.actor, reason=args.reason,
                )
            elif args.execute_command == "finalize":
                payload = service.finalize(
                    execution_id=args.execution_id, claim_token=claim_token,
                    post_state=json.loads(Path(args.post_state).read_text(encoding="utf-8")),
                    actor=args.actor, reason=args.reason,
                )
            else:
                payload = service.fail(
                    execution_id=args.execution_id, claim_token=claim_token,
                    ambiguous=args.classification == "ambiguous", actor=args.actor,
                    reason=args.reason, error_code=args.error_code,
                    error_detail=args.error_detail,
                )
        print(json.dumps(payload, ensure_ascii=False, default=str))
        return 2 if payload.get("status") in {"ambiguous", "failed", "blocked"} else 0

    db = OpsDB(config.ops_db, minimum_version=config.sqlite_min_version)
    if args.command == "migrate":
        print(json.dumps({"applied": db.migrate(), "sqlite_version": db.sqlite_version}))
    elif args.command == "tick":
        if args.force and not all((args.actor, args.reason, args.idempotency_key)):
            raise SystemExit(
                "tick --force exige --actor, --reason y --idempotency-key"
            )
        try:
            print(json.dumps(TickRunner(config, db).run(
                force=args.force, actor=args.actor or "mova-ops", reason=args.reason,
                idempotency_key=args.idempotency_key,
            ), ensure_ascii=False, default=str))
        except LockBusy as exc:
            print(json.dumps({"status": "skipped", "reason": str(exc)}))
            return 75
    elif args.command == "collect":
        from mova_fpl.ops.collector.service import CollectorService

        if args.force and not all((args.actor, args.reason, args.idempotency_key)):
            raise SystemExit(
                "collect --force exige --actor, --reason y --idempotency-key"
            )
        try:
            payload = CollectorService(config, db).run(
                args.source, force=args.force, actor=args.actor or "mova-collector",
                reason=args.reason, idempotency_key=args.idempotency_key,
            )
            print(json.dumps(payload, ensure_ascii=False, default=str))
            return 2 if payload.get("status") == "degraded" else 0
        except LockBusy as exc:
            print(json.dumps({"status": "skipped", "reason": str(exc)}))
            return 75
    elif args.command == "serve":
        serve(config, db)
    elif args.command == "check":
        print(json.dumps({"integrity": db.quick_check(), "status": db.status()},
                         ensure_ascii=False, default=str))
    elif args.command == "status":
        payload = build_status(config, db)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
              if args.as_json else render_status(payload))
    elif args.command == "safety":
        print(json.dumps(build_safety(config, db), ensure_ascii=False,
                         sort_keys=True, default=str))
    elif args.command == "alerts":
        db.migrate()
        if args.alerts_command == "status":
            payload = db.outbox_status()
        elif args.alerts_command == "dispatch":
            from mova_fpl.ops.alerts import dispatch
            payload = dispatch(db, limit=args.limit)
        elif args.alerts_command == "acknowledge":
            payload = db.acknowledge_incident(
                args.incident_id, actor=args.actor, reason=args.reason,
            )
        else:
            payload = db.retry_outbox(
                args.outbox_id, actor=args.actor, reason=args.reason,
            )
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
    elif args.command == "maintenance":
        from mova_fpl.ops.maintenance import cleanup

        if args.apply and not all((args.actor, args.reason, args.idempotency_key)):
            raise SystemExit(
                "maintenance cleanup --apply exige --actor, --reason y --idempotency-key"
            )
        if not args.apply:
            payload = cleanup(
                config.artifact_root, older_than_seconds=args.older_than_seconds,
            )
        else:
            correlation_id = new_id("corr")
            job_id, reused = db.start_job(
                "maintenance_cleanup", f"cleanup:{args.idempotency_key}", correlation_id,
            )
            if reused:
                payload = {"schema": "mova-maintenance-cleanup-v1", "status": "reused",
                           "job_id": job_id}
            else:
                try:
                    db.append_audit(
                        "maintenance_cleanup_requested", actor=args.actor, job_id=job_id,
                        subject_type="artifact_root", subject_id=str(config.artifact_root),
                        payload={"reason": args.reason,
                                 "older_than_seconds": args.older_than_seconds},
                    )
                    payload = cleanup(
                        config.artifact_root,
                        older_than_seconds=args.older_than_seconds, apply=True,
                    )
                except Exception as exc:
                    db.finish_job(job_id, "failed", error_code=type(exc).__name__,
                                  error_detail=str(exc)[:2000])
                    raise
                db.finish_job(job_id, "completed", output_sha256=sha256_json(payload),
                              metrics={key: payload[key] for key in (
                                  "candidate_count", "candidate_bytes", "removed_count",
                                  "removed_bytes",
                              )})
                payload["job_id"] = job_id
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
    elif args.command == "readiness":
        from mova_fpl.ops.readiness import LEVELS, build_readiness

        payload = build_readiness(config, db)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
        if args.require_level:
            observed = payload["activation"]["technical_eligible_level"]
            return 0 if LEVELS.index(observed) >= LEVELS.index(args.require_level) else 2
    elif args.command == "doctor":
        payload = build_doctor(config, db, network=not args.no_network)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
              if args.as_json else render_doctor(payload))
        return 1 if payload["summary"]["required_failures"] else 0
    elif args.command == "ingest-team-state":
        from pathlib import Path
        from mova_fpl.ops.team_state import ingest

        payload = json.loads(
            sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
        )
        db.migrate()
        print(json.dumps(ingest(config, db, payload, trigger=args.trigger),
                         ensure_ascii=False, default=str))
    elif args.command == "private-state-due":
        from mova_fpl.ops.private_schedule import assess

        db.migrate()
        result = assess(config, db)
        print(json.dumps(result, ensure_ascii=False, default=str))
        if not result["due"]:
            return 75
    elif args.command == "watchdog":
        from mova_fpl.ops.watchdog import run

        try:
            payload = run(db, max_age_seconds=args.max_age_seconds)
        except Exception as exc:  # DB rota puede impedir persistir; journald conserva el fallo
            payload = {"schema": "mova-watchdog-v2", "status": "down",
                       "reason": "control_plane_unavailable",
                       "error_code": type(exc).__name__}
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
        if payload["status"] != "ok":
            return 1
    elif args.command == "drill":
        if args.drill_command == "host-status":
            row = db.get_job_by_key(f"host_recovery_drill:{args.idempotency_key}")
            if not row:
                print(json.dumps({"schema": "mova-host-drill-status-v1", "status": "due"}))
                return 75
            print(json.dumps({
                "schema": "mova-host-drill-status-v1", "status": row["status"],
                "job_id": row["job_id"], "reused": row["status"] == "completed",
            }, sort_keys=True))
            return 0 if row["status"] == "completed" else 2
        correlation_id = new_id("corr")
        is_resilience = args.drill_command == "resilience"
        job_type = "resilience_drill" if is_resilience else "host_recovery_drill"
        schema = "mova-resilience-drill-v1" if is_resilience else "mova-host-drill-v1"
        job_id, reused = db.start_job(
            job_type, f"{job_type}:{args.idempotency_key}", correlation_id,
        )
        if reused:
            print(json.dumps({"schema": schema, "status": "reused",
                              "job_id": job_id}))
        else:
            db.append_audit(
                f"{job_type}_requested", actor=args.actor,
                correlation_id=correlation_id, job_id=job_id,
                subject_type="drill", subject_id=(
                    "scheduler_p0_recovery" if is_resilience else "api_recovery"
                ),
                payload={"reason": args.reason},
            )
            try:
                if is_resilience:
                    from mova_fpl.ops.watchdog import resilience_drill
                    payload = resilience_drill()
                else:
                    from pathlib import Path
                    from mova_fpl.ops.host_drill import import_evidence
                    payload = import_evidence(config, Path(args.file))
            except Exception as exc:
                db.finish_job(job_id, "failed", error_code=type(exc).__name__,
                              error_detail=str(exc)[:2000])
                raise
            result_status = "completed" if payload["status"] == "pass" else "failed"
            checks = payload["checks"]
            db.finish_job(
                job_id, result_status,
                output_sha256=payload.get("artifact_sha256") or sha256_json(payload),
                metrics={"scenario": payload.get("scenario") or "scheduler_p0_recovery",
                         "checks": len(checks), "passed": sum(checks.values()),
                         "downtime_seconds": payload.get("downtime_seconds")},
                error_code=None if result_status == "completed" else "DrillFailed",
            )
            print(json.dumps({"job_id": job_id, **payload}, ensure_ascii=False,
                             sort_keys=True, default=str))
            if result_status != "completed":
                return 1
    elif args.command == "backup":
        if args.force and not all((args.actor, args.reason, args.idempotency_key)):
            raise SystemExit(
                "backup --force exige --actor, --reason y --idempotency-key"
            )
        day = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
        correlation_id = new_id("corr")
        job_key = (f"backup:forced:{args.idempotency_key}" if args.force
                   else f"backup:{day}")
        job_id, reused = db.start_job("backup", job_key, correlation_id)
        if reused:
            print(json.dumps({"status": "reused", "job_id": job_id}))
        else:
            try:
                if args.force:
                    db.append_audit(
                        "forced_backup_requested", actor=args.actor,
                        job_id=job_id, subject_type="backup", subject_id=job_id,
                        payload={"reason": args.reason,
                                 "idempotency_key": args.idempotency_key},
                    )
                result = create_backup(config, db, retention_days=args.retention_days)
            except Exception as exc:
                db.finish_job(job_id, "failed", error_code=type(exc).__name__,
                              error_detail=str(exc)[:2000])
                raise
            db.finish_job(job_id, "completed", output_sha256=sha256_json(result), metrics=result)
            print(json.dumps({"job_id": job_id, **result}, ensure_ascii=False, default=str))
    elif args.command == "control":
        value = json.loads(args.value)
        control_id = db.set_control(args.key, value, actor=args.actor, reason=args.reason)
        print(json.dumps({"control_id": control_id, "key": args.key, "value": value}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
