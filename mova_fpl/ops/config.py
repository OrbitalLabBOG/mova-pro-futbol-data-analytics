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
    enable_long_horizon_shadow: bool = False
    long_horizon_uncertainty_artifact: Path | None = None
    long_horizon_uncertainty_sha256: str | None = None
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
    collector_lock_path: Path = Path("/var/lib/mova-fpl/mova-fpl-collector.lock")
    collector_root: Path = Path("/var/lib/mova-fpl/artifacts/data-service")
    analytics_root: Path = Path("/var/lib/mova-fpl/artifacts/analytics-service")
    analytics_lock_path: Path = Path("/var/lib/mova-fpl/mova-fpl-analytics.lock")
    analytics_minutes_version: str = "1.1.0"
    analytics_points_version: str = "1.1.0"
    analytics_reference_gameweeks: int = 6
    strategic_root: Path = Path("/var/lib/mova-fpl/artifacts/strategic-context")
    research_root: Path = Path("/var/lib/mova-fpl/artifacts/research")
    research_provider: str = "codex_subscription"
    research_min_interval_seconds: int = 6 * 3600
    research_deadline_window_seconds: int = 30 * 3600
    research_final_window_seconds: int = 2 * 3600
    research_final_cutoff_seconds: int = 70 * 60
    agent_budget_reservation_tokens: int = 120_000
    agent_budget_job_tokens: int = 160_000
    agent_budget_gw_tokens: int = 900_000
    agent_budget_month_tokens: int = 3_000_000
    agent_budget_gw_uses: int = 20
    agent_budget_month_uses: int = 60
    collector_fpl_cadence_seconds: int = 6 * 3600
    # Máxima edad operativa de odds. La cadencia efectiva la decide el
    # deadline FPL y la cuota observada del proveedor.
    collector_odds_cadence_seconds: int = 24 * 3600
    collector_events_cadence_seconds: int = 30 * 60
    collector_schedule_cadence_seconds: int = 24 * 3600
    collector_event_batch_size: int = 10
    collector_browser_path: Path = Path("/usr/bin/chromium")
    odds_api_credential_file: Path = Path("/run/secrets/odds_api_key")
    odds_api_regions: str = "uk,eu"
    odds_api_regular_regions: str = "uk"
    odds_api_markets: str = "h2h,totals"
    odds_api_reserve_credits: int = 150
    odds_api_hard_reserve_credits: int = 75
    alert_webhook_config_file: Path = Path("/run/secrets/alert_webhook_config")
    alert_webhook_timeout_seconds: int = 5
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "mova"
    postgres_user: str = "mova_owner"
    postgres_credential_file: Path = Path("/run/secrets/postgres_password")
    postgres_app_user: str = "mova_app_runtime"
    postgres_app_credential_file: Path = Path("/run/secrets/postgres_app_password")
    postgres_readonly_user: str = "mova_readonly_runtime"
    postgres_readonly_credential_file: Path = Path(
        "/run/secrets/postgres_readonly_password"
    )
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
            enable_long_horizon_shadow=_bool("MOVA_ENABLE_LONG_HORIZON_SHADOW", False),
            long_horizon_uncertainty_artifact=(
                Path(os.environ["MOVA_LONG_HORIZON_UNCERTAINTY_ARTIFACT"])
                if os.environ.get("MOVA_LONG_HORIZON_UNCERTAINTY_ARTIFACT") else None
            ),
            long_horizon_uncertainty_sha256=(
                os.environ.get("MOVA_LONG_HORIZON_UNCERTAINTY_SHA256") or None
            ),
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
            collector_lock_path=Path(os.environ.get(
                "MOVA_COLLECTOR_LOCK_PATH", "/var/lib/mova-fpl/mova-fpl-collector.lock"
            )),
            collector_root=Path(os.environ.get(
                "MOVA_COLLECTOR_ROOT", "/var/lib/mova-fpl/artifacts/data-service"
            )),
            analytics_root=Path(os.environ.get(
                "MOVA_ANALYTICS_ROOT", "/var/lib/mova-fpl/artifacts/analytics-service"
            )),
            analytics_lock_path=Path(os.environ.get(
                "MOVA_ANALYTICS_LOCK_PATH", "/var/lib/mova-fpl/mova-fpl-analytics.lock"
            )),
            analytics_minutes_version=os.environ.get("MOVA_MINUTES_MODEL_VERSION", "1.1.0"),
            analytics_points_version=os.environ.get("MOVA_POINTS_MODEL_VERSION", "1.1.0"),
            analytics_reference_gameweeks=int(os.environ.get(
                "MOVA_ANALYTICS_REFERENCE_GAMEWEEKS", "6"
            )),
            strategic_root=Path(os.environ.get(
                "MOVA_STRATEGIC_ROOT",
                "/var/lib/mova-fpl/artifacts/strategic-context"
            )),
            research_root=Path(os.environ.get(
                "MOVA_RESEARCH_ROOT", "/var/lib/mova-fpl/artifacts/research"
            )),
            research_provider=os.environ.get(
                "MOVA_RESEARCH_PROVIDER", "codex_subscription"
            ),
            research_min_interval_seconds=int(os.environ.get(
                "MOVA_RESEARCH_MIN_INTERVAL_SECONDS", str(6 * 3600)
            )),
            research_deadline_window_seconds=int(os.environ.get(
                "MOVA_RESEARCH_DEADLINE_WINDOW_SECONDS", str(30 * 3600)
            )),
            research_final_window_seconds=int(os.environ.get(
                "MOVA_RESEARCH_FINAL_WINDOW_SECONDS", str(2 * 3600)
            )),
            research_final_cutoff_seconds=int(os.environ.get(
                "MOVA_RESEARCH_FINAL_CUTOFF_SECONDS", str(70 * 60)
            )),
            agent_budget_reservation_tokens=int(os.environ.get(
                "MOVA_AGENT_BUDGET_RESERVATION_UNITS", "120000"
            )),
            agent_budget_job_tokens=int(os.environ.get(
                "MOVA_AGENT_BUDGET_JOB_UNITS", "160000"
            )),
            agent_budget_gw_tokens=int(os.environ.get(
                "MOVA_AGENT_BUDGET_GW_UNITS", "900000"
            )),
            agent_budget_month_tokens=int(os.environ.get(
                "MOVA_AGENT_BUDGET_MONTH_UNITS", "3000000"
            )),
            agent_budget_gw_uses=int(os.environ.get(
                "MOVA_AGENT_BUDGET_GW_USES", "20"
            )),
            agent_budget_month_uses=int(os.environ.get(
                "MOVA_AGENT_BUDGET_MONTH_USES", "60"
            )),
            collector_fpl_cadence_seconds=int(os.environ.get(
                "MOVA_COLLECTOR_FPL_CADENCE_SECONDS", str(6 * 3600)
            )),
            collector_odds_cadence_seconds=int(os.environ.get(
                "MOVA_COLLECTOR_ODDS_CADENCE_SECONDS", str(24 * 3600)
            )),
            collector_events_cadence_seconds=int(os.environ.get(
                "MOVA_COLLECTOR_EVENTS_CADENCE_SECONDS", str(30 * 60)
            )),
            collector_schedule_cadence_seconds=int(os.environ.get(
                "MOVA_COLLECTOR_SCHEDULE_CADENCE_SECONDS", str(24 * 3600)
            )),
            collector_event_batch_size=int(os.environ.get(
                "MOVA_COLLECTOR_EVENT_BATCH_SIZE", "10"
            )),
            collector_browser_path=Path(os.environ.get(
                "MOVA_COLLECTOR_BROWSER_PATH", "/usr/bin/chromium"
            )),
            odds_api_credential_file=Path(os.environ.get(
                "MOVA_ODDS_API_CREDENTIAL_FILE", "/run/secrets/odds_api_key"
            )),
            odds_api_regions=os.environ.get("MOVA_ODDS_API_REGIONS", "uk,eu"),
            odds_api_regular_regions=os.environ.get(
                "MOVA_ODDS_API_REGULAR_REGIONS", "uk"
            ),
            odds_api_markets=os.environ.get("MOVA_ODDS_API_MARKETS", "h2h,totals"),
            odds_api_reserve_credits=int(os.environ.get(
                "MOVA_ODDS_API_RESERVE_CREDITS", "150"
            )),
            odds_api_hard_reserve_credits=int(os.environ.get(
                "MOVA_ODDS_API_HARD_RESERVE_CREDITS", "75"
            )),
            alert_webhook_config_file=Path(os.environ.get(
                "MOVA_ALERT_WEBHOOK_CONFIG_FILE",
                "/run/secrets/alert_webhook_config",
            )),
            alert_webhook_timeout_seconds=int(os.environ.get(
                "MOVA_ALERT_WEBHOOK_TIMEOUT_SECONDS", "5"
            )),
            postgres_host=os.environ.get("MOVA_POSTGRES_HOST", "postgres"),
            postgres_port=int(os.environ.get("MOVA_POSTGRES_PORT", "5432")),
            postgres_db=os.environ.get("MOVA_POSTGRES_DB", "mova"),
            postgres_user=os.environ.get("MOVA_POSTGRES_USER", "mova_owner"),
            postgres_credential_file=Path(os.environ.get(
                "MOVA_POSTGRES_CREDENTIAL_FILE", "/run/secrets/postgres_password"
            )),
            postgres_app_user=os.environ.get(
                "MOVA_POSTGRES_APP_USER", "mova_app_runtime"
            ),
            postgres_app_credential_file=Path(os.environ.get(
                "MOVA_POSTGRES_APP_CREDENTIAL_FILE",
                "/run/secrets/postgres_app_password"
            )),
            postgres_readonly_user=os.environ.get(
                "MOVA_POSTGRES_READONLY_USER", "mova_readonly_runtime"
            ),
            postgres_readonly_credential_file=Path(os.environ.get(
                "MOVA_POSTGRES_READONLY_CREDENTIAL_FILE",
                "/run/secrets/postgres_readonly_password"
            )),
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
        for path in (self.ops_db.parent, self.artifact_root, self.analytics_root,
                     self.analytics_lock_path,
                     self.strategic_root, self.research_root,
                     self.host_probe_path,
                     self.collector_lock_path, self.collector_root,
                     self.collector_browser_path):
            if not path.is_absolute():
                raise ValueError(f"path operativo debe ser absoluto: {path}")
        if self.private_state_max_age_seconds <= 0:
            raise ValueError("MOVA_PRIVATE_STATE_MAX_AGE_SECONDS debe ser positivo")
        if not 3 <= self.analytics_reference_gameweeks <= 20:
            raise ValueError("MOVA_ANALYTICS_REFERENCE_GAMEWEEKS debe estar entre 3 y 20")
        if self.research_provider not in {"codex_subscription", "fixture"}:
            raise ValueError("MOVA_RESEARCH_PROVIDER inválido")
        if self.research_min_interval_seconds <= 0:
            raise ValueError("MOVA_RESEARCH_MIN_INTERVAL_SECONDS debe ser positivo")
        if not 3600 <= self.research_deadline_window_seconds <= 7 * 86400:
            raise ValueError("MOVA_RESEARCH_DEADLINE_WINDOW_SECONDS fuera de rango")
        if not (
            15 * 60 <= self.research_final_cutoff_seconds
            < self.research_final_window_seconds
            < self.research_deadline_window_seconds
        ):
            raise ValueError("ventanas finales de research inválidas")
        token_limits = (
            self.agent_budget_reservation_tokens, self.agent_budget_job_tokens,
            self.agent_budget_gw_tokens, self.agent_budget_month_tokens,
        )
        if any(value <= 0 for value in token_limits) or not (
            self.agent_budget_reservation_tokens <= self.agent_budget_job_tokens
            <= self.agent_budget_gw_tokens <= self.agent_budget_month_tokens
        ):
            raise ValueError("presupuestos de tokens del agente inválidos")
        if not 1 <= self.agent_budget_gw_uses <= self.agent_budget_month_uses:
            raise ValueError("presupuestos de usos del agente inválidos")
        cadences = (
            self.collector_fpl_cadence_seconds, self.collector_odds_cadence_seconds,
            self.collector_events_cadence_seconds, self.collector_schedule_cadence_seconds,
        )
        if any(value <= 0 for value in cadences):
            raise ValueError("cadencias del collector deben ser positivas")
        if not 1 <= self.collector_event_batch_size <= 50:
            raise ValueError("MOVA_COLLECTOR_EVENT_BATCH_SIZE debe estar entre 1 y 50")
        if not self.odds_api_credential_file.is_absolute():
            raise ValueError("MOVA_ODDS_API_CREDENTIAL_FILE debe ser absoluto")
        regions = tuple(filter(None, (item.strip() for item in self.odds_api_regions.split(","))))
        regular_regions = tuple(filter(None, (
            item.strip() for item in self.odds_api_regular_regions.split(",")
        )))
        markets = tuple(filter(None, (item.strip() for item in self.odds_api_markets.split(","))))
        if (not regions or not regular_regions or not markets
                or not set(regular_regions) <= set(regions)
                or not set(markets) <= {"h2h", "totals"}):
            raise ValueError("configuración de mercados The Odds API inválida")
        if len(set(regions)) * len(set(markets)) > 4:
            raise ValueError("consulta The Odds API excede el guardrail de 4 créditos")
        if not 0 < self.odds_api_hard_reserve_credits < self.odds_api_reserve_credits:
            raise ValueError("reservas de cuota The Odds API inválidas")
        if not self.alert_webhook_config_file.is_absolute():
            raise ValueError("MOVA_ALERT_WEBHOOK_CONFIG_FILE debe ser absoluto")
        if not 1 <= self.alert_webhook_timeout_seconds <= 15:
            raise ValueError("MOVA_ALERT_WEBHOOK_TIMEOUT_SECONDS debe estar entre 1 y 15")

    def validate_postgres(self) -> None:
        """Valida solo la configuración del store shadow, sin abrir red."""
        if not self.postgres_host or not self.postgres_db or not self.postgres_user:
            raise ValueError("configuración PostgreSQL incompleta")
        if not 1 <= self.postgres_port <= 65535:
            raise ValueError("MOVA_POSTGRES_PORT fuera de rango")
        if not self.postgres_credential_file.is_absolute():
            raise ValueError("MOVA_POSTGRES_CREDENTIAL_FILE debe ser absoluto")

    def validate_postgres_roles(self) -> None:
        """Valida identidades separadas sin leer ni exponer sus secretos."""
        self.validate_postgres()
        users = {
            self.postgres_user,
            self.postgres_app_user,
            self.postgres_readonly_user,
        }
        if len(users) != 3 or any(not item.strip() for item in users):
            raise ValueError("roles PostgreSQL owner/app/readonly deben ser distintos")
        credential_paths = (
            self.postgres_credential_file,
            self.postgres_app_credential_file,
            self.postgres_readonly_credential_file,
        )
        if len({str(path) for path in credential_paths}) != 3:
            raise ValueError("secretos PostgreSQL owner/app/readonly deben ser distintos")
        for path in credential_paths:
            if not path.is_absolute():
                raise ValueError("credenciales PostgreSQL de app/readonly deben ser absolutas")

    def agent_budget_policy(self) -> dict[str, int]:
        """Política versionable que acompaña cada reserva de inferencia."""
        return {
            "reservation_tokens": self.agent_budget_reservation_tokens,
            "job_tokens": self.agent_budget_job_tokens,
            "gw_tokens": self.agent_budget_gw_tokens,
            "month_tokens": self.agent_budget_month_tokens,
            "gw_uses": self.agent_budget_gw_uses,
            "month_uses": self.agent_budget_month_uses,
        }
