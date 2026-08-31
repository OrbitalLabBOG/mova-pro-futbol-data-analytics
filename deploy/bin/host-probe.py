#!/usr/bin/env python3
"""Produce un inventario sanitizado del host para el CLI aislado de MOVA."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

UNITS = (
    "mova-fpl-stack.service",
    "mova-fpl-tick.timer",
    "mova-fpl-private-state.timer",
    "mova-fpl-backup.timer",
    "mova-fpl-watchdog.timer",
    "mova-fpl-collector.timer",
    "mova-fpl-analytics.timer",
    "mova-fpl-research.timer",
    "mova-fpl-postgres-sync.timer",
)
OFFSITE_CONFIG_KEYS = {
    "schema", "enabled", "provider", "owner", "repository_file", "password_file",
}


def command(argv: list[str], *, cwd: Path | None = None) -> tuple[int, str]:
    try:
        result = subprocess.run(
            argv, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=15, check=False,
        )
        return result.returncode, result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""


def unit_state(name: str) -> dict:
    code, output = command([
        "systemctl", "show", name, "--no-pager",
        "--property=LoadState", "--property=ActiveState", "--property=SubState",
        "--property=UnitFileState",
    ])
    values = {}
    for line in output.splitlines():
        key, _, value = line.partition("=")
        if key:
            values[key] = value
    return {
        "observable": code == 0,
        "load_state": values.get("LoadState"),
        "active_state": values.get("ActiveState"),
        "sub_state": values.get("SubState"),
        "unit_file_state": values.get("UnitFileState"),
    }


def compose_services(repo: Path) -> dict:
    code, output = command(["docker", "compose", "--profile", "browser", "ps", "-a",
                            "--format", "json"], cwd=repo)
    if code != 0:
        return {}
    services = {}
    for line in output.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        name = item.get("Service")
        if name:
            services[str(name)] = {"state": item.get("State"), "health": item.get("Health")}
    return services


def api_ready(port: int) -> bool:
    try:
        request = urllib.request.Request(f"http://127.0.0.1:{port}/readyz", method="GET")
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def revision(repo: Path, service: str | None = None) -> str | None:
    if service is None:
        code, output = command(["git", "rev-parse", "--short", "HEAD"], cwd=repo)
    else:
        code, container = command(["docker", "compose", "ps", "-q", service], cwd=repo)
        if code != 0 or not container:
            return None
        code, output = command([
            "docker", "inspect", "--format",
            '{{ index .Config.Labels "org.opencontainers.image.revision" }}', container,
        ])
    return output or None if code == 0 else None


def offsite_backup_status(
    path: Path, *, credential_root: Path = Path("/etc/mova-fpl"), required_uid: int = 0,
) -> dict:
    """Expose only sanitized readiness for the optional encrypted off-host target."""
    base = {
        "schema": "mova-offsite-backup-status-v1", "configured": False,
        "encrypted": False, "external": False, "provider": None, "owner": None,
        "destination_fingerprint": None, "timer_active": False,
    }
    if not path.exists():
        return {**base, "status": "unconfigured", "reasons": ["config_missing"]}
    reasons: list[str] = []
    try:
        stat = path.lstat()
        if path.is_symlink() or not path.is_file() or stat.st_size > 16_384:
            raise ValueError("unsafe_config")
        if stat.st_uid != required_uid:
            reasons.append("config_owner_invalid")
        if stat.st_mode & 0o077:
            reasons.append("config_permissions_too_broad")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or set(payload) != OFFSITE_CONFIG_KEYS:
            raise ValueError("invalid_config_schema")
        if payload.get("schema") != "mova-offsite-backup-v1":
            reasons.append("invalid_config_schema")
        if payload.get("enabled") is not True:
            reasons.append("not_enabled")
        provider = str(payload.get("provider") or "")
        if provider != "restic":
            reasons.append("unsupported_provider")
        owner = str(payload.get("owner") or "")
        if not re.fullmatch(r"[A-Za-z0-9_.@-]{2,80}", owner):
            reasons.append("invalid_owner")

        repository_descriptor: bytes | None = None
        for name in ("repository_file", "password_file"):
            candidate = Path(str(payload.get(name) or ""))
            if (not candidate.is_absolute() or candidate.parent != credential_root
                    or candidate.is_symlink() or not candidate.is_file()):
                reasons.append(f"{name}_missing_or_unsafe")
                continue
            candidate_stat = candidate.stat()
            if (candidate_stat.st_uid != required_uid or candidate_stat.st_size > 4096
                    or candidate_stat.st_mode & 0o077):
                reasons.append(f"{name}_owner_permissions_or_size_invalid")
                continue
            if name == "repository_file":
                repository_descriptor = candidate.read_bytes().strip()

        remote_prefixes = (
            b"azure:", b"b2:", b"gs:", b"rclone:", b"rest:", b"s3:",
            b"sftp:", b"swift:",
        )
        external = bool(
            repository_descriptor
            and repository_descriptor.lower().startswith(remote_prefixes)
        )
        if repository_descriptor is not None and not external:
            reasons.append("repository_not_external")

        timer = unit_state("mova-fpl-offsite-backup.timer")
        timer_active = (
            timer.get("load_state") == "loaded"
            and timer.get("active_state") == "active"
            and timer.get("unit_file_state") == "enabled"
        )
        if not timer_active:
            reasons.append("timer_not_active")
        fingerprint = None
        if repository_descriptor is not None and external:
            fingerprint = hashlib.sha256(
                provider.encode() + b"\0" + repository_descriptor
            ).hexdigest()[:16]
        configured = not reasons
        return {
            **base, "status": "configured" if configured else "invalid",
            "configured": configured, "encrypted": provider == "restic",
            "external": external, "provider": provider or None, "owner": owner or None,
            "destination_fingerprint": fingerprint, "timer_active": timer_active,
            "reasons": reasons,
        }
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        code = str(exc) if str(exc) in {"unsafe_config", "invalid_config_schema"} else type(exc).__name__
        return {**base, "status": "invalid", "reasons": [code]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser-profile", type=Path, required=True)
    parser.add_argument("--api-port", type=int, default=8787)
    parser.add_argument(
        "--offsite-config", type=Path,
        default=Path("/etc/mova-fpl/offsite-backup.json"),
    )
    args = parser.parse_args()

    services = compose_services(args.repo)
    profile_present = args.browser_profile.is_dir() and any(args.browser_profile.iterdir())
    payload = {
        "schema": "mova-host-probe-v1",
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "systemd": {name: unit_state(name) for name in UNITS},
        "api": {
            "ready": api_ready(args.api_port),
            "container_state": (services.get("api") or {}).get("state"),
            "container_health": (services.get("api") or {}).get("health"),
        },
        "postgres": {
            "container_state": (services.get("postgres") or {}).get("state"),
            "container_health": (services.get("postgres") or {}).get("health"),
            "published_ports": False,
            "role": "shadow",
        },
        "browser": {
            "container_state": (services.get("browser") or {}).get("state", "stopped"),
            "container_health": (services.get("browser") or {}).get("health"),
            "profile_present": profile_present,
        },
        "research": {
            "auth_present": Path(
                os.environ.get("MOVA_CODEX_HOME", "/var/lib/mova-fpl/codex-home")
            ).joinpath("auth.json").is_file(),
            "queue_present": Path(
                os.environ.get(
                    "MOVA_RESEARCH_ROOT",
                    "/var/lib/mova-fpl/artifacts/research"
                )
            ).is_dir(),
        },
        "offsite_backup": offsite_backup_status(args.offsite_config),
        "revisions": {"checkout": revision(args.repo), "image": revision(args.repo, "api")},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".host-probe-", dir=args.output.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        try:
            os.chown(temporary, 10001, 10001)
        except PermissionError:
            pass
        os.replace(temporary, args.output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(json.dumps({"status": "ok", "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
