"""Rehearsal hermético del boundary de snapshots PostgreSQL."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

from mova_fpl.postgres.importer import _verify_manifest

SCHEMA = "mova-snapshot-rejection-drill-v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _database(path: Path, label: str) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "create table evidence(id integer primary key,label text not null)"
        )
        connection.execute("insert into evidence(label) values(?)", (label,))


def _seal(root: Path) -> str:
    names = {"ops": "ops.db", "canonical": "canonical.db", "trace": "trace.db"}
    files = {}
    for source, name in names.items():
        path = root / name
        _database(path, source)
        files[source] = {
            "name": name, "bytes": path.stat().st_size, "sha256": _sha256(path),
        }
    manifest = {
        "schema": "mova-postgres-import-source-v1",
        "import_run_id": "snapshot_rejection_fixture",
        "created_at": "2026-08-31T00:00:00+00:00",
        "git_sha": "hermetic",
        "files": files,
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return _sha256(manifest_path)


def _clone(source: Path, destination: Path) -> tuple[Path, str]:
    shutil.copytree(source, destination)
    manifest = destination / "manifest.json"
    return destination, _sha256(manifest)


def run() -> dict:
    """Corrompe sólo fixtures temporales y exige rechazo determinista."""
    checks: dict[str, bool] = {}
    reasons: dict[str, str | None] = {}
    workspace_path: Path | None = None
    with tempfile.TemporaryDirectory(prefix="mova-snapshot-drill-") as temporary:
        workspace = Path(temporary)
        workspace_path = workspace
        valid = workspace / "valid"
        valid.mkdir()
        valid_sha = _seal(valid)
        baseline = _verify_manifest(valid, valid_sha)
        checks["valid_baseline_accepted"] = baseline.get("status") == "pass"

        manifest_case, manifest_sha = _clone(valid, workspace / "manifest-tamper")
        with (manifest_case / "manifest.json").open("a", encoding="utf-8") as handle:
            handle.write(" ")
        observed = _verify_manifest(manifest_case, manifest_sha)
        checks["manifest_checksum_rejected"] = observed.get("status") == "fail"
        reasons["manifest_checksum_rejected"] = observed.get("reason")

        contract_case, _ = _clone(valid, workspace / "manifest-contract")
        contract_manifest_path = contract_case / "manifest.json"
        contract_manifest = json.loads(contract_manifest_path.read_text(encoding="utf-8"))
        contract_manifest["schema"] = "untrusted-snapshot-v1"
        contract_manifest_path.write_text(
            json.dumps(contract_manifest, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n", encoding="utf-8",
        )
        observed = _verify_manifest(contract_case, _sha256(contract_manifest_path))
        checks["manifest_contract_rejected"] = (
            observed.get("status") == "fail"
            and observed.get("reason") == "manifest_contract_invalid"
        )

        database_case, database_sha = _clone(valid, workspace / "database-tamper")
        with (database_case / "ops.db").open("ab") as handle:
            handle.write(b"tamper")
        observed = _verify_manifest(database_case, database_sha)
        checks["database_checksum_rejected"] = (
            observed.get("status") == "fail"
            and (observed.get("files") or {}).get("ops", {}).get("status") == "fail"
        )

        corrupt_case, corrupt_sha = _clone(valid, workspace / "database-corrupt")
        (corrupt_case / "canonical.db").write_bytes(b"not-a-sqlite-database")
        observed = _verify_manifest(corrupt_case, corrupt_sha)
        canonical = (observed.get("files") or {}).get("canonical", {})
        checks["corrupt_database_rejected"] = (
            observed.get("status") == "fail" and canonical.get("integrity") == "error"
        )

        size_case, _ = _clone(valid, workspace / "size-mismatch")
        size_manifest_path = size_case / "manifest.json"
        size_manifest = json.loads(size_manifest_path.read_text(encoding="utf-8"))
        size_manifest["files"]["ops"]["bytes"] += 1
        size_manifest_path.write_text(
            json.dumps(size_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        observed = _verify_manifest(size_case, _sha256(size_manifest_path))
        checks["size_mismatch_rejected"] = (
            observed.get("status") == "fail"
            and (observed.get("files") or {}).get("ops", {}).get("status") == "fail"
        )

        duplicate_case, _ = _clone(valid, workspace / "duplicate-name")
        duplicate_manifest_path = duplicate_case / "manifest.json"
        duplicate_manifest = json.loads(
            duplicate_manifest_path.read_text(encoding="utf-8")
        )
        duplicate_manifest["files"]["trace"] = dict(
            duplicate_manifest["files"]["ops"]
        )
        duplicate_manifest_path.write_text(
            json.dumps(duplicate_manifest, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n", encoding="utf-8",
        )
        observed = _verify_manifest(duplicate_case, _sha256(duplicate_manifest_path))
        checks["duplicate_name_rejected"] = (
            observed.get("status") == "fail"
            and (observed.get("files") or {}).get("trace", {}).get("reason")
            == "unsafe_path"
        )

        traversal_case, _ = _clone(valid, workspace / "path-traversal")
        outside = workspace / "outside.db"
        shutil.copy2(valid / "ops.db", outside)
        traversal_manifest_path = traversal_case / "manifest.json"
        traversal_manifest = json.loads(
            traversal_manifest_path.read_text(encoding="utf-8")
        )
        traversal_manifest["files"]["ops"] = {
            "name": "../outside.db", "bytes": outside.stat().st_size,
            "sha256": _sha256(outside),
        }
        traversal_manifest_path.write_text(
            json.dumps(traversal_manifest, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n", encoding="utf-8",
        )
        observed = _verify_manifest(traversal_case, _sha256(traversal_manifest_path))
        checks["path_traversal_rejected"] = (
            observed.get("status") == "fail"
            and (observed.get("files") or {}).get("ops", {}).get("reason") == "unsafe_path"
        )

        symlink_case, symlink_sha = _clone(valid, workspace / "symlink")
        trace = symlink_case / "trace.db"
        trace.unlink()
        os.symlink(valid / "trace.db", trace)
        observed = _verify_manifest(symlink_case, symlink_sha)
        checks["symlink_rejected"] = (
            observed.get("status") == "fail"
            and (observed.get("files") or {}).get("trace", {}).get("reason")
            == "symlink_rejected"
        )

    checks["temporary_workspace_removed"] = (
        workspace_path is not None and not workspace_path.exists()
    )
    return {
        "schema": SCHEMA,
        "scenario": "snapshot_rejection",
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "reasons": reasons,
        "runtime_mutated": False,
        "fixture_only": True,
    }
