"""Backups consistentes y verificables para las bases SQLite operativas."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_backup(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    check = sqlite3.connect(f"file:{destination}?mode=ro", uri=True)
    try:
        result = check.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        check.close()
    if result != "ok":
        raise RuntimeError(f"backup inválido {destination}: {result}")


def create_backup(config: RuntimeConfig, db: OpsDB, *, retention_days: int = 35) -> dict:
    db.quick_check()
    checkpoint = db.checkpoint()
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    root = config.backup_root / stamp
    tmp = config.backup_root / f".{stamp}.{os.getpid()}.tmp"
    tmp.mkdir(parents=True, exist_ok=False)
    try:
        files: list[dict] = []
        for name, source in zip(("ops.db", "trace.db", "fpl_canonical.db"),
                                (config.ops_db, config.trace_db, config.canonical_db)):
            if source.is_symlink() or not source.is_file():
                raise FileNotFoundError(f"required backup database missing or unsafe: {source.name}")
            destination = tmp / name
            _sqlite_backup(source, destination)
            files.append({"name": name, "size": destination.stat().st_size,
                          "sha256": _sha256(destination)})
        # Resolve against the sealed ops snapshot, not a concurrently changing pointer.
        from mova_fpl.ops.model_release import resolve_active_model_bundle
        sealed_db = OpsDB(tmp / "ops.db", enforce_version=False)
        bundle = resolve_active_model_bundle(config, sealed_db)
        models = []
        for family in ("minutes", "points"):
            model = bundle["models"][family]
            source = Path(model["artifact_path"])
            if source.is_symlink():
                raise ValueError("unsafe active model artifact")
            relative = f"models/{family}/{family}-{model['version']}.joblib"
            destination = tmp / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            digest = _sha256(destination)
            if digest != model["artifact_sha256"]:
                raise ValueError("active model changed during backup")
            models.append({"name": relative, "family": family, "version": model["version"],
                           "size": destination.stat().st_size, "sha256": digest})
        manifest = {
            "schema": "mova-fpl-backup-v2", "created_at": now.isoformat(),
            "sqlite_version": sqlite3.sqlite_version, "git_sha": config.git_sha,
            "files": files, "ops_wal_checkpoint": checkpoint,
            "models": models,
            "recovery": {"season": config.season, "team_id": config.team_id,
                         "mode": "shadow", "action_level": "A0", "kill_switch": True,
                         "browser_writes": False, "release_id": bundle.get("release_id")},
        }
        (tmp / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp.replace(root)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise

    cutoff = now.timestamp() - retention_days * 86400
    removed: list[str] = []
    for candidate in config.backup_root.iterdir():
        if candidate == root or not candidate.is_dir() or candidate.name.startswith("."):
            continue
        try:
            parsed = datetime.strptime(candidate.name, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if parsed.timestamp() < cutoff:
            shutil.rmtree(candidate)
            removed.append(candidate.name)
    return {"status": "completed", "path": str(root), "files": files, "removed": removed}
