"""Captura on-demand del estado privado del equipo (ADR-022).

El timer de 5 min se retiró: el estado privado (plantilla, banco, FT, chips) se
captura cuando el copiloto prepara la GW. Este módulo envuelve el script de host
``deploy/bin/collect-private-team-state.sh --force`` (que conserva lock, cooldown
y el ingest sanitizado). Solo stdlib: corre igual en el host o en tests.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

SCHEMA = "mova-private-capture-v1"
SCRIPT_ENV = "MOVA_PRIVATE_CAPTURE_SCRIPT"
DEFAULT_TIMEOUT_SECONDS = 300
HINT = ("Si falta sesión FPL: iniciar sesión en el browser del VPS (script de browser del host) y "
        "repetir `mova private-state capture --force`.")


def script_path(repo_dir: str | os.PathLike | None = None) -> Path:
    override = os.environ.get(SCRIPT_ENV)
    if override:
        return Path(override)
    repo = Path(repo_dir or os.environ.get("MOVA_REPO_DIR") or Path.cwd())
    return repo / "deploy" / "bin" / "collect-private-team-state.sh"


def capture(*, actor: str, reason: str, idempotency_key: str, force: bool = True,
            script: Path | None = None, timeout: int = DEFAULT_TIMEOUT_SECONDS,
            runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> dict:
    """Ejecuta el script con ``--force``; nunca lanza: devuelve el resultado."""
    base = {"schema": SCHEMA, "actor": actor, "reason": reason,
            "idempotency_key": idempotency_key, "hint": HINT}
    if not force:
        return {**base, "status": "refused",
                "detail": "private-state capture exige --force (cooldown y cadencia se saltan)"}
    path = script or script_path()
    if not path.is_file():
        return {**base, "status": "unavailable", "script": str(path),
                "detail": "script de host no disponible aquí; correr `mova private-state "
                          "capture --force` desde el host del VPS"}
    try:
        done = runner([str(path), "--force"], capture_output=True, text=True,
                      timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return {**base, "status": "timeout", "script": str(path), "timeout_seconds": timeout}
    except OSError as exc:
        return {**base, "status": "error", "script": str(path), "detail": type(exc).__name__}
    return {**base, "status": "ok" if done.returncode == 0 else "failed",
            "returncode": done.returncode, "script": str(path),
            "stdout_tail": (done.stdout or "")[-500:],
            "stderr_tail": (done.stderr or "")[-500:]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="private-state capture")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--actor", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--idempotency-key", required=True)
    args = parser.parse_args(argv)
    result = capture(actor=args.actor, reason=args.reason,
                     idempotency_key=args.idempotency_key, force=args.force)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "ok" else (result.get("returncode") or 2)


if __name__ == "__main__":
    sys.exit(main())
