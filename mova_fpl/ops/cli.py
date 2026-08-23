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
from mova_fpl.ops.tick import LockBusy, TickRunner


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="mova")
    root.add_argument("--log-level", default="INFO")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate")
    commands.add_parser("tick")
    commands.add_parser("serve")
    commands.add_parser("check")
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
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    configure_logging(args.log_level)
    config = RuntimeConfig.from_env()
    config.validate()
    db = OpsDB(config.ops_db, minimum_version=config.sqlite_min_version)
    if args.command == "migrate":
        print(json.dumps({"applied": db.migrate(), "sqlite_version": db.sqlite_version}))
    elif args.command == "tick":
        try:
            print(json.dumps(TickRunner(config, db).run(), ensure_ascii=False, default=str))
        except LockBusy as exc:
            print(json.dumps({"status": "skipped", "reason": str(exc)}))
            return 75
    elif args.command == "serve":
        serve(config, db)
    elif args.command == "check":
        print(json.dumps({"integrity": db.quick_check(), "status": db.status()},
                         ensure_ascii=False, default=str))
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
