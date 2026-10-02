"""Verify the complete sealed SQLite set without runtime mounts or migrations."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import re
from pathlib import Path

REQUIRED_DATABASES = {"ops.db", "trace.db", "fpl_canonical.db"}


def verify(directory: Path) -> dict:
    manifest_path = directory / "manifest.json"
    if directory.is_symlink() or manifest_path.is_symlink():
        raise ValueError("unsafe SQLite restore directory")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files")
    if manifest.get("schema") != "mova-fpl-backup-v2" or not isinstance(files, list):
        raise ValueError("invalid SQLite backup manifest")
    if (not all(isinstance(item, dict) for item in files)
            or len(files) != 3
            or {item.get("name") for item in files} != REQUIRED_DATABASES):
        raise ValueError("complete SQLite backup set required")
    results = []
    for item in files:
        path = directory / item["name"]
        if path.is_symlink() or not path.is_file():
            raise ValueError("missing or unsafe restored database")
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if path.stat().st_size != item.get("size") or digest != item.get("sha256"):
            raise ValueError("restored SQLite checksum or size mismatch")
        with sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True) as con:
            if con.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError(f"restored database integrity failed: {path.name}")
            tables = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            if not tables:
                raise ValueError(f"restored database has no application tables: {path.name}")
            for (name,) in tables:
                identifier = '"' + name.replace('"', '""') + '"'
                con.execute(f"SELECT count(*) FROM {identifier}").fetchone()
        results.append({"name": path.name, "integrity": "ok", "tables": len(tables)})
    models = manifest.get("models")
    if (not isinstance(models, list) or len(models) != 2
            or not all(isinstance(item, dict) for item in models)
            or {item.get("family") for item in models} != {"minutes", "points"}):
        raise ValueError("complete active model set required")
    import joblib
    for item in models:
        family = item["family"]
        version = str(item.get("version") or "")
        name = f"models/{family}/{family}-{version}.joblib"
        path = directory / name
        if (not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) or item.get("name") != name
                or path.is_symlink() or any(parent.is_symlink() for parent in path.parents)):
            raise ValueError("unsafe model restore path")
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if digest != item.get("sha256") or path.stat().st_size != item.get("size"):
            raise ValueError("restored model checksum mismatch")
        joblib.load(path)
    return {"status": "pass", "databases": results, "models_loaded": 2,
            "runtime_mutated": False, "scope": "databases_and_active_models"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.directory), sort_keys=True))


if __name__ == "__main__":
    main()
