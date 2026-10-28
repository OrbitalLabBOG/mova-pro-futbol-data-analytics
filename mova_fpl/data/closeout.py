"""Validated, versioned input contract for settlement consumers."""
from __future__ import annotations

import json
from pathlib import Path


def load_closeout_package(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    accepted = {
        "mova-fpl-manual-closeout-v1",
        "mova-fpl-manual-closeout-v2",
        "mova-fpl-autonomous-closeout-v1",
        "mova-fpl-autonomous-closeout-v2",
    }
    if payload.get("schema") not in accepted:
        raise ValueError("package de cierre no cumple un contrato soportado")
    for key in (
        "season", "gw", "deadline_at", "entry_id", "reviewed_at", "mounted_at",
        "trace_run_id", "decision_acta_path", "mount_evidence_path",
        "mount_evidence_sha256", "chip_inventory", "selected", "comparator",
        "intervention", "mount_verification", "proposals",
    ):
        if key not in payload:
            raise ValueError(f"package de cierre sin {key}")
    verification = payload["mount_verification"]
    if payload["schema"] in {"mova-fpl-autonomous-closeout-v2", "mova-fpl-manual-closeout-v2"}:
        for name in ("selected", "comparator"):
            if not payload[name].get("financing"):
                raise ValueError(f"{name} sin financiación sellada")
    if not isinstance(verification, dict):
        raise ValueError("mount_verification debe ser un objeto")
    for key in ("squad", "xi", "captain", "vice_captain", "bench_order", "budget", "no_chip"):
        if key not in verification:
            raise ValueError(f"mount_verification sin {key}")
    return payload

