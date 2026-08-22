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
        for source in (config.ops_db, config.trace_db, config.canonical_db):
            if not source.is_file():
                if source == config.ops_db:
                    raise FileNotFoundError(source)
                continue
            destination = tmp / source.name
            _sqlite_backup(source, destination)
            files.append({"name": source.name, "size": destination.stat().st_size,
                          "sha256": _sha256(destination)})
        manifest = {
            "schema": "mova-fpl-backup-v1", "created_at": now.isoformat(),
            "sqlite_version": sqlite3.sqlite_version, "git_sha": config.git_sha,
            "files": files, "ops_wal_checkpoint": checkpoint,
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
