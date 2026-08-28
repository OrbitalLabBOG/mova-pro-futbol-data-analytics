"""Harness auditable para pasos deterministas y comandos acotados."""

from __future__ import annotations

import hashlib
import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from mova_fpl.ops.db import OpsDB

LOG = logging.getLogger(__name__)

_SENSITIVE_KEY_PARTS = (
    "authorization", "cookie", "password", "secret", "token",
    "player_first_name", "player_last_name", "email", "phone",
)


def _sensitive_key(value: object) -> bool:
    normalized = str(value).strip().lower()
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _safe_detail(value, *, depth: int = 0):
    """Reduce resultados para el ledger sin persistir payloads ni secretos."""
    if isinstance(value, bytes):
        return {"type": "bytes", "size": len(value),
                "sha256": hashlib.sha256(value).hexdigest()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str):
        return value if len(value) <= 1000 else value[:1000] + "…"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if depth > 3:
        return {"type": type(value).__name__}
    if isinstance(value, dict):
        if depth >= 2:
            return {"type": "dict", "items": len(value)}
        return {
            str(key): ({"type": "redacted"} if _sensitive_key(key)
                       else _safe_detail(item, depth=depth + 1))
            for key, item in list(value.items())[:50]
        }
    if isinstance(value, (list, tuple)):
        if depth >= 2 or len(value) > 10:
            return {"type": type(value).__name__, "items": len(value)}
        return [_safe_detail(item, depth=depth + 1) for item in value[:50]]
    return {"type": type(value).__name__}


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    duration_ms: int

    @property
    def sha256(self) -> str:
        payload = (self.stdout + "\n--- stderr ---\n" + self.stderr).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


class Harness:
    def __init__(self, db: OpsDB, job_id: str, *, correlation_id: str,
                 cycle_id: str | None = None):
        self.db = db
        self.job_id = job_id
        self.correlation_id = correlation_id
        self.cycle_id = cycle_id

    def call(self, name: str, fn):
        step_id, started = self.db.start_step(self.job_id, name)
        LOG.info(name, extra={"event": "step_started", "job_id": self.job_id,
                              "cycle_id": self.cycle_id,
                              "correlation_id": self.correlation_id, "phase": name})
        try:
            value = fn()
        except Exception as exc:
            self.db.finish_step(
                step_id, started, "failed", error_code=type(exc).__name__,
                error_detail=str(exc)[:2000],
            )
            LOG.exception(name, extra={"event": "step_failed", "job_id": self.job_id,
                                       "cycle_id": self.cycle_id,
                                       "correlation_id": self.correlation_id,
                                       "phase": name, "error_code": type(exc).__name__})
            raise
        detail = _safe_detail(value)
        self.db.finish_step(step_id, started, "completed", detail=detail)
        LOG.info(name, extra={"event": "step_completed", "job_id": self.job_id,
                              "cycle_id": self.cycle_id,
                              "correlation_id": self.correlation_id, "phase": name,
                              "duration_ms": int((time.monotonic() - started) * 1000),
                              "detail": detail})
        return value

    def command(self, name: str, argv: list[str], *, timeout: int,
                env: dict[str, str], cwd: Path) -> CommandResult:
        step_id, started = self.db.start_step(self.job_id, name)
        LOG.info(name, extra={"event": "command_started", "job_id": self.job_id,
                              "cycle_id": self.cycle_id,
                              "correlation_id": self.correlation_id,
                              "phase": name, "detail": {"argv": argv[:4] + ["..."]}})
        try:
            result = subprocess.run(
                argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout,
            )
        except Exception as exc:
            self.db.finish_step(
                step_id, started, "failed", error_code=type(exc).__name__,
                error_detail=str(exc)[:2000],
            )
            raise
        command_result = CommandResult(
            returncode=result.returncode, stdout=result.stdout, stderr=result.stderr,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        status = "completed" if result.returncode == 0 else "failed"
        self.db.finish_step(
            step_id, started, status, output_sha256=command_result.sha256,
            detail={"returncode": result.returncode,
                    "stdout_tail": result.stdout[-2000:], "stderr_tail": result.stderr[-2000:]},
            error_code=None if result.returncode == 0 else "COMMAND_FAILED",
            error_detail=None if result.returncode == 0 else result.stderr[-2000:],
        )
        LOG.log(
            logging.INFO if result.returncode == 0 else logging.ERROR,
            name,
            extra={"event": f"command_{status}", "job_id": self.job_id,
                   "cycle_id": self.cycle_id, "correlation_id": self.correlation_id,
                   "phase": name, "duration_ms": command_result.duration_ms,
                   "status": status},
        )
        return command_result
