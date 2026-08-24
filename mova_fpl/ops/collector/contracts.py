"""Contratos pequeños compartidos por los adapters del collector."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class DataQualityError(ValueError):
    """El transporte respondió, pero el payload no cumple el contrato."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), default=str) + "\n").encode("utf-8")


def write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_bytes(payload)
    tmp.replace(path)


@dataclass(frozen=True, slots=True)
class SourceOutput:
    source: str
    status: str
    artifact_path: Path
    payload_sha256: str
    manifest_sha256: str
    quality: dict
    metrics: dict
    rows: dict

    def as_dict(self) -> dict:
        return {
            "source": self.source, "status": self.status,
            "artifact_path": str(self.artifact_path),
            "payload_sha256": self.payload_sha256,
            "manifest_sha256": self.manifest_sha256,
            "quality": self.quality, "metrics": self.metrics, "rows": self.rows,
        }


def seal_manifest(directory: Path, manifest: dict) -> tuple[Path, str]:
    path = directory / "manifest.json"
    payload = canonical_bytes(manifest)
    write_atomic(path, payload)
    return path, sha256_bytes(payload)
