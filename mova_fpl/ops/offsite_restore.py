"""Validate a restic snapshot and its isolated operational-database restore."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

STAMP = re.compile(r"20\d{6}T\d{6}Z")
SNAPSHOT_ID = re.compile(r"[0-9a-f]{64}")
SHA256 = re.compile(r"[0-9a-f]{64}")


def select_snapshot(rows: list[dict], backup_root: Path) -> tuple[str, str, str]:
    """Select only a MOVA snapshot with exactly one SQLite and one PG backup."""
    root = str(backup_root).rstrip("/")
    candidates = []
    for row in rows:
        if "mova-fpl" not in row.get("tags", []):
            continue
        paths = row.get("paths") or []
        if len(paths) != 2 or len(set(paths)) != 2:
            continue
        sqlite = [p.removeprefix(root + "/") for p in paths
                  if isinstance(p, str) and p.startswith(root + "/")]
        if len(sqlite) != 2:
            continue
        sqlite_stamps = [p for p in sqlite if STAMP.fullmatch(p)]
        postgres_stamps = [p.removeprefix("postgres/") for p in sqlite
                           if p.startswith("postgres/") and
                           STAMP.fullmatch(p.removeprefix("postgres/"))]
        snapshot_id = str(row.get("id") or "")
        if (len(sqlite_stamps) == len(postgres_stamps) == 1
                and SNAPSHOT_ID.fullmatch(snapshot_id)):
            candidates.append((str(row.get("time") or ""), snapshot_id,
                               sqlite_stamps[0], postgres_stamps[0]))
    if not candidates:
        raise ValueError("no matching MOVA offsite snapshot")
    _, snapshot_id, sqlite_stamp, postgres_stamp = max(candidates)
    return snapshot_id, sqlite_stamp, postgres_stamp


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _checked_file(path: Path, *, size: int, sha256: str) -> None:
    if (path.is_symlink() or not path.is_file() or size < 0
            or not SHA256.fullmatch(sha256)):
        raise ValueError("unsafe or missing restored file")
    if path.stat().st_size != size or _sha256(path) != sha256:
        raise ValueError("restored file hash or size mismatch")


def verify_restored_set(restore_root: Path, backup_root: Path,
                        sqlite_stamp: str, postgres_stamp: str) -> tuple[Path, Path]:
    """Require the two sealed sets and reject extra files, links and secrets."""
    if not STAMP.fullmatch(sqlite_stamp) or not STAMP.fullmatch(postgres_stamp):
        raise ValueError("invalid backup timestamp")
    root = restore_root / str(backup_root).lstrip("/")
    sqlite_dir = root / sqlite_stamp
    postgres_dir = root / "postgres" / postgres_stamp
    for path in (restore_root, *sqlite_dir.parents, sqlite_dir,
                 *postgres_dir.parents, postgres_dir):
        if path == Path("/"):
            continue
        if path.is_symlink():
            raise ValueError("symlink in restored path")
    sqlite_manifest_path = sqlite_dir / "manifest.json"
    postgres_manifest_path = postgres_dir / "manifest.json"
    if any(p.is_symlink() or not p.is_file()
           for p in (sqlite_manifest_path, postgres_manifest_path)):
        raise ValueError("restored manifest missing or unsafe")
    sqlite_manifest = json.loads(sqlite_manifest_path.read_text(encoding="utf-8"))
    postgres_manifest = json.loads(postgres_manifest_path.read_text(encoding="utf-8"))
    if (sqlite_manifest.get("schema") != "mova-fpl-backup-v1"
            or postgres_manifest.get("schema") != "mova-postgres-backup-v1"):
        raise ValueError("restored manifest schema mismatch")
    files = sqlite_manifest.get("files")
    if not isinstance(files, list) or not all(isinstance(item, dict) for item in files):
        raise ValueError("restored SQLite file list invalid")
    names = [item.get("name") for item in files]
    if ("ops.db" not in names
            or len(names) != len(set(names))
            or any(name not in {"ops.db", "trace.db", "fpl_canonical.db"}
                   for name in names)):
        raise ValueError("restored SQLite file list invalid")
    allowed = {sqlite_manifest_path, postgres_manifest_path}
    for item in files:
        path = sqlite_dir / item["name"]
        if type(item.get("size")) is not int:
            raise ValueError("restored SQLite size invalid")
        _checked_file(path, size=item["size"], sha256=str(item.get("sha256")))
        allowed.add(path)
    dump = postgres_manifest.get("dump") or {}
    if dump.get("name") != "postgres-shadow.dump":
        raise ValueError("restored PostgreSQL dump name invalid")
    if type(dump.get("bytes")) is not int:
        raise ValueError("restored PostgreSQL size invalid")
    dump_path = postgres_dir / "postgres-shadow.dump"
    _checked_file(dump_path, size=dump["bytes"], sha256=str(dump.get("sha256")))
    allowed.add(dump_path)
    for path in restore_root.rglob("*"):
        if path.is_symlink() or (path.is_file() and path not in allowed):
            raise ValueError("restored snapshot contains unexpected file or link")
    return sqlite_dir, postgres_dir


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    select = sub.add_parser("select")
    select.add_argument("snapshot_list", type=Path)
    select.add_argument("backup_root", type=Path)
    verify = sub.add_parser("verify")
    verify.add_argument("restore_root", type=Path)
    verify.add_argument("backup_root", type=Path)
    verify.add_argument("sqlite_stamp")
    verify.add_argument("postgres_stamp")
    args = parser.parse_args()
    if args.command == "select":
        rows = json.loads(args.snapshot_list.read_text(encoding="utf-8"))
        print("\n".join(select_snapshot(rows, args.backup_root)))
    else:
        print("\n".join(str(p) for p in verify_restored_set(
            args.restore_root, args.backup_root,
            args.sqlite_stamp, args.postgres_stamp,
        )))


if __name__ == "__main__":
    main()
