"""Configuración explícita del runtime VPS."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    season: str = "2026-27"
    team_id: int = 3609854
    mode: str = "shadow"
    action_level: str = "A0"
    compliance_gate: str = "pending"
    enable_shadow_decision: bool = True
    enable_browser_writes: bool = False
    ops_db: Path = Path("/var/lib/mova-fpl/db/ops.db")
    trace_db: Path = Path("/var/lib/mova-fpl/db/trace.db")
    canonical_db: Path = Path("/var/lib/mova-fpl/db/fpl_canonical.db")
    artifact_root: Path = Path("/var/lib/mova-fpl/artifacts")
    backup_root: Path = Path("/opt/orbital/backups/mova-fpl")
    host_probe_path: Path = Path("/var/lib/mova-fpl/runtime/host-probe.json")
    lock_path: Path = Path("/var/lib/mova-fpl/mova-fpl.lock")
    sqlite_min_version: str = "3.51.3"
    memory_gate_bytes: int = 2_684_354_560
    disk_gate_bytes: int = 21_474_836_480
    api_host: str = "0.0.0.0"
    api_port: int = 8787
    tick_bucket_seconds: int = 300
    decision_timeout_seconds: int = 600
    private_state_max_age_seconds: int = 21600
    git_sha: str = "unknown"

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        return cls(
            season=os.environ.get("MOVA_SEASON", "2026-27"),
            team_id=int(os.environ.get("MOVA_TEAM_ID", "3609854")),
            mode=os.environ.get("MOVA_MODE", "shadow"),
            action_level=os.environ.get("MOVA_ACTION_LEVEL", "A0"),
            compliance_gate=os.environ.get("MOVA_COMPLIANCE_GATE", "pending"),
            enable_shadow_decision=_bool("MOVA_ENABLE_SHADOW_DECISION", True),
            enable_browser_writes=_bool("MOVA_ENABLE_BROWSER_WRITES", False),
            ops_db=Path(os.environ.get("MOVA_OPS_DB", "/var/lib/mova-fpl/db/ops.db")),
            trace_db=Path(os.environ.get("MOVA_TRACE_DB", "/var/lib/mova-fpl/db/trace.db")),
            canonical_db=Path(os.environ.get("MOVA_CANONICAL_DB", "/var/lib/mova-fpl/db/fpl_canonical.db")),
            artifact_root=Path(os.environ.get("MOVA_ARTIFACT_ROOT", "/var/lib/mova-fpl/artifacts")),
            backup_root=Path(os.environ.get("MOVA_BACKUP_ROOT", "/opt/orbital/backups/mova-fpl")),
            host_probe_path=Path(os.environ.get(
                "MOVA_HOST_PROBE_PATH", "/var/lib/mova-fpl/runtime/host-probe.json"
            )),
            lock_path=Path(os.environ.get("MOVA_LOCK_PATH", "/var/lib/mova-fpl/mova-fpl.lock")),
            sqlite_min_version=os.environ.get("MOVA_SQLITE_MIN_VERSION", "3.51.3"),
            memory_gate_bytes=int(os.environ.get("MOVA_MEMORY_GATE_BYTES", "2684354560")),
            disk_gate_bytes=int(os.environ.get("MOVA_DISK_GATE_BYTES", "21474836480")),
            api_host=os.environ.get("MOVA_API_HOST", "0.0.0.0"),
            api_port=int(os.environ.get("MOVA_API_PORT", "8787")),
            tick_bucket_seconds=int(os.environ.get("MOVA_TICK_BUCKET_SECONDS", "300")),
            decision_timeout_seconds=int(os.environ.get("MOVA_DECISION_TIMEOUT_SECONDS", "600")),
            private_state_max_age_seconds=int(
                os.environ.get("MOVA_PRIVATE_STATE_MAX_AGE_SECONDS", "21600")
            ),
            git_sha=os.environ.get("MOVA_GIT_SHA", "unknown"),
        )

    def validate(self) -> None:
        if self.mode not in {"shadow", "supervised", "guarded", "autonomous", "paused"}:
            raise ValueError(f"MOVA_MODE inválido: {self.mode}")
        if self.action_level not in {"A0", "A1", "A2", "A3"}:
            raise ValueError(f"MOVA_ACTION_LEVEL inválido: {self.action_level}")
        if self.enable_browser_writes and (
            self.mode not in {"guarded", "autonomous"}
            or self.action_level == "A0"
            or self.compliance_gate != "approved"
        ):
            raise ValueError(
                "browser writes exige mode guarded/autonomous, action level A1+ y compliance approved"
            )
        for path in (self.ops_db.parent, self.artifact_root, self.host_probe_path):
            if not path.is_absolute():
                raise ValueError(f"path operativo debe ser absoluto: {path}")
        if self.private_state_max_age_seconds <= 0:
            raise ValueError("MOVA_PRIVATE_STATE_MAX_AGE_SECONDS debe ser positivo")
