"""Persistencia y versionado de artefactos de modelo.

Guarda el joblib y devuelve el registro de version. La escritura a la traza la
hace la CLI: `models/` no conoce el almacenamiento de experimentos.
"""
from __future__ import annotations

import json
import hashlib
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import joblib

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = Path(os.environ.get("MOVA_MODEL_ROOT", ROOT / "models"))


def git_sha() -> str:
    explicit = os.environ.get("MOVA_GIT_SHA")
    if explicit:
        return explicit
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() or "unknown"
    except Exception:                                   # noqa: BLE001
        return "unknown"


def save(model, name: str, version: str, metrics: dict, *,
         artifact_root: Path | None = None, overwrite: bool = True) -> dict:
    root = Path(artifact_root) if artifact_root is not None else ARTIFACTS
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    ruta = d / f"{name}-{version}.joblib"
    sidecar = d / f"{name}-{version}.json"
    if not overwrite and (ruta.exists() or sidecar.exists()):
        raise FileExistsError(f"artefacto de modelo ya existe: {name} {version}")
    temporary = ruta.with_suffix(".joblib.tmp")
    sidecar_tmp = sidecar.with_suffix(".json.tmp")
    try:
        joblib.dump(model, temporary)
        os.replace(temporary, ruta)
    finally:
        temporary.unlink(missing_ok=True)
    artifact_sha256 = hashlib.sha256(ruta.read_bytes()).hexdigest()
    limpio = {k: v for k, v in metrics.items() if not hasattr(v, "to_dict")}
    try:
        artifact_ref = str(ruta.relative_to(ROOT))
    except ValueError:
        artifact_ref = str(ruta)
    registro = {
        "name": name, "version": version, "git_sha": git_sha(),
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "train_rows": int(model.metadata.get("filas_ajuste", 0)),
        "artifact": artifact_ref,
        "artifact_sha256": artifact_sha256,
        "metrics": limpio,
    }
    try:
        sidecar_tmp.write_text(
            json.dumps(registro, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        os.replace(sidecar_tmp, sidecar)
    finally:
        sidecar_tmp.unlink(missing_ok=True)
    return registro


def load(name: str, version: str):
    return joblib.load(ARTIFACTS / name / f"{name}-{version}.joblib")
