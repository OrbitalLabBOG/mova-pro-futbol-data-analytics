"""Logging JSON con correlación y redacción mínima."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

REDACT_KEYS = {"password", "token", "secret", "cookie", "authorization", "otp", "mfa"}


def _clean(value):
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if k.lower() in REDACT_KEYS else _clean(v))
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "severity": record.levelname.lower(),
            "service": os.environ.get("MOVA_SERVICE", "mova-ops"),
            "event": getattr(record, "event", record.getMessage()),
        }
        for key in ("correlation_id", "job_id", "cycle_id", "season", "gw", "phase",
                    "status", "duration_ms", "error_code"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        detail = getattr(record, "detail", None)
        if detail is not None:
            payload["detail"] = _clean(detail)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(_clean(payload), ensure_ascii=False, separators=(",", ":"))


def configure_logging(level: str | None = None) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel((level or os.environ.get("MOVA_LOG_LEVEL", "INFO")).upper())
