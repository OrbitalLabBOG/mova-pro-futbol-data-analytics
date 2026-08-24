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
from mova_fpl.ops.operator import build_doctor, build_status, render_doctor, render_status
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
    status = commands.add_parser("status", help="estado operativo consolidado")
    status.add_argument("--json", action="store_true", dest="as_json")
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
    backup = commands.add_parser("backup")
    backup.add_argument("--retention-days", type=int, default=35)
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
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    configure_logging(args.log_level)
    config = RuntimeConfig.from_env()
    if args.command != "doctor":
        config.validate()
    if args.command == "postgres":
        from mova_fpl.postgres.importer import import_shadow, verify_shadow
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
        db.quick_check()
        status = db.status()
        tick = status.get("latest_tick") or {}
        finished = tick.get("finished_at")
        if not finished:
            print(json.dumps({"status": "down", "reason": "no_finished_tick"}))
            return 1
        observed = datetime.fromisoformat(str(finished).replace("Z", "+00:00"))
        age = int((datetime.now(timezone.utc) - observed).total_seconds())
        healthy = age <= args.max_age_seconds and tick.get("status") in {"completed", "degraded"}
        print(json.dumps({"status": "ok" if healthy else "down", "tick_age_seconds": age,
                          "latest_tick_status": tick.get("status")}))
        if not healthy:
            return 1
    elif args.command == "backup":
        day = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
        correlation_id = new_id("corr")
        job_id, reused = db.start_job("backup", f"backup:{day}", correlation_id)
        if reused:
            print(json.dumps({"status": "reused", "job_id": job_id}))
        else:
            try:
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
