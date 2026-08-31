"""Mantenimiento conservador de artefactos transitorios.

La evidencia canónica nunca entra al conjunto de candidatos. El modo por defecto
es dry-run y sólo considera sufijos explícitamente transitorios.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

TRANSIENT_SUFFIXES = (".tmp", ".partial")


def cleanup(root: Path, *, older_than_seconds: int = 86400, apply: bool = False) -> dict:
    current = datetime.now(timezone.utc).timestamp()
    root = root.resolve()
    candidates = []
    if root.is_dir():
        for path in sorted(root.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            if not (path.name.startswith(".tmp-") or path.suffix in TRANSIENT_SUFFIXES):
                continue
            stat = path.stat()
            age = int(current - stat.st_mtime)
            if age < max(0, older_than_seconds):
                continue
            candidates.append({
                "path": str(path.relative_to(root)), "size_bytes": stat.st_size,
                "age_seconds": age, "reason": "explicit_transient_suffix",
            })
    removed = 0
    removed_bytes = 0
    if apply:
        for item in candidates:
            target = (root / item["path"]).resolve()
            if root not in target.parents or target.is_symlink():
                raise ValueError("cleanup target escaped artifact root")
            target.unlink(missing_ok=True)
            removed += 1
            removed_bytes += item["size_bytes"]
    return {
        "schema": "mova-maintenance-cleanup-v1", "mode": "apply" if apply else "dry-run",
        "root": str(root), "older_than_seconds": max(0, older_than_seconds),
        "candidate_count": len(candidates), "candidate_bytes": sum(
            item["size_bytes"] for item in candidates
        ), "removed_count": removed, "removed_bytes": removed_bytes,
        "candidates": candidates,
    }
