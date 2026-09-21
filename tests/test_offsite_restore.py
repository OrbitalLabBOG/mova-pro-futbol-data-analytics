"""Untrusted remote snapshots must not become accepted recovery evidence."""

import hashlib
import json
from pathlib import Path

import pytest

from mova_fpl.ops.offsite_restore import select_snapshot, verify_restored_set


SQLITE_STAMP = "20260920T120000Z"
POSTGRES_STAMP = "20260920T120001Z"
SNAPSHOT = "a" * 64


def _write(path: Path, content: bytes) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return {"size": len(content), "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest()}


def _restored(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "restore"
    backups = root / "opt/orbital/backups/mova-fpl"
    sqlite = backups / SQLITE_STAMP
    postgres = backups / "postgres" / POSTGRES_STAMP
    info = _write(sqlite / "ops.db", b"sqlite fixture")
    (sqlite / "manifest.json").write_text(json.dumps({
        "schema": "mova-fpl-backup-v1", "files": [
            {"name": "ops.db", "size": info["size"], "sha256": info["sha256"]},
        ],
    }), encoding="utf-8")
    info = _write(postgres / "postgres-shadow.dump", b"postgres fixture")
    (postgres / "manifest.json").write_text(json.dumps({
        "schema": "mova-postgres-backup-v1",
        "dump": {"name": "postgres-shadow.dump", "bytes": info["bytes"],
                 "sha256": info["sha256"]},
    }), encoding="utf-8")
    return root, backups


def test_snapshot_selection_requires_exact_backup_paths():
    root = Path("/opt/orbital/backups/mova-fpl")
    row = {"id": SNAPSHOT, "time": "2026-09-20T12:01:00Z",
           "tags": ["mova-fpl", "operational-databases"],
           "paths": [str(root / SQLITE_STAMP),
                     str(root / "postgres" / POSTGRES_STAMP)]}
    assert select_snapshot([row], root) == (SNAPSHOT, SQLITE_STAMP, POSTGRES_STAMP)
    for malformed in (
        {**row, "tags": []},
        {**row, "paths": [str(root / SQLITE_STAMP)]},
        {**row, "paths": [str(root / SQLITE_STAMP), "/etc/mova-fpl"]},
    ):
        with pytest.raises(ValueError):
            select_snapshot([malformed], root)


def test_restored_set_verifies_both_manifests_and_rejects_extra_content(tmp_path):
    root, backups = _restored(tmp_path)
    expected = (backups / SQLITE_STAMP, backups / "postgres" / POSTGRES_STAMP)
    assert verify_restored_set(root, Path("/opt/orbital/backups/mova-fpl"),
                               SQLITE_STAMP, POSTGRES_STAMP) == expected
    (expected[0] / "ops.db").write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="hash or size"):
        verify_restored_set(root, Path("/opt/orbital/backups/mova-fpl"),
                            SQLITE_STAMP, POSTGRES_STAMP)


def test_restored_set_rejects_unexpected_secret_and_malformed_manifest(tmp_path):
    root, backups = _restored(tmp_path)
    extra = backups / "offsite-password"
    extra.write_text("bad", encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected"):
        verify_restored_set(root, Path("/opt/orbital/backups/mova-fpl"),
                            SQLITE_STAMP, POSTGRES_STAMP)
    extra.unlink()
    manifest = backups / SQLITE_STAMP / "manifest.json"
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["files"] = ["bad"]
    manifest.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="file list"):
        verify_restored_set(root, Path("/opt/orbital/backups/mova-fpl"),
                            SQLITE_STAMP, POSTGRES_STAMP)
