"""Persistencia y versionado de artefactos de modelo.

Guarda el joblib y devuelve el registro de version. La escritura a la traza la
hace la CLI: `models/` no conoce el almacenamiento de experimentos.
"""
from __future__ import annotations

import json
import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import joblib

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "models"


def git_sha() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() or "unknown"
    except Exception:                                   # noqa: BLE001
        return "unknown"


def save(model, name: str, version: str, metrics: dict) -> dict:
    d = ARTIFACTS / name
    d.mkdir(parents=True, exist_ok=True)
    ruta = d / f"{name}-{version}.joblib"
    joblib.dump(model, ruta)
    artifact_sha256 = hashlib.sha256(ruta.read_bytes()).hexdigest()
    limpio = {k: v for k, v in metrics.items() if not hasattr(v, "to_dict")}
    registro = {
        "name": name, "version": version, "git_sha": git_sha(),
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "train_rows": int(model.metadata.get("filas_ajuste", 0)),
        "artifact": str(ruta.relative_to(ROOT)),
        "artifact_sha256": artifact_sha256,
        "metrics": limpio,
    }
    (d / f"{name}-{version}.json").write_text(
        json.dumps(registro, ensure_ascii=False, indent=2, default=str) + "\n")
    return registro


def load(name: str, version: str):
    return joblib.load(ARTIFACTS / name / f"{name}-{version}.joblib")
