#!/usr/bin/env python3
"""Produce un inventario sanitizado del host para el CLI aislado de MOVA."""

from __future__ import annotations

import argparse
import json
import os
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
)


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser-profile", type=Path, required=True)
    parser.add_argument("--api-port", type=int, default=8787)
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
