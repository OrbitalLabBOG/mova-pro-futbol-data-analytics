"""Cierre auditado de incidentes obsoletos del harness retirado (ADR-022)."""

from __future__ import annotations

import shutil

from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB

GIB = 1024 ** 3
STORAGE_TITLE = "Local storage headroom low"
STORAGE_WARNING_MARGIN_BYTES = 28 * GIB
EVENT_TYPE = "obsolete_incidents_closed"
# Título -> severidad esperada; solo ruido del camino autónomo/DR ya retirado.
OBSOLETE_TITLES = {
    "Ejecución FPL ambigua": "P0",
    "Backup recovery observation unhealthy": "P1",
    "Shadow decision falló": "P2",
}


def close_obsolete(config: RuntimeConfig, db: OpsDB, *, actor: str, reason: str,
                   idempotency_key: str, dry_run: bool = False,
                   disk_free: int | None = None) -> dict:
    if not (actor and reason and idempotency_key):
        raise ValueError("incidents close-obsolete exige actor, reason e idempotency_key")
    con = db.connect(readonly=True)
    try:
        prior = con.execute(
            "SELECT payload_json FROM audit_events WHERE event_type=? AND "
            "json_extract(payload_json,'$.idempotency_key')=? LIMIT 1",
            (EVENT_TYPE, idempotency_key),
        ).fetchone()
        open_rows = [dict(row) for row in con.execute(
            "SELECT incident_id,severity,title FROM incidents WHERE status!='resolved'"
        )]
    finally:
        con.close()
    if prior:
        return {"schema": "mova-incident-cleanup-v1", "status": "reused",
                "idempotency_key": idempotency_key}
    if disk_free is None:
        root = config.artifact_root if config.artifact_root.exists() else config.artifact_root.parent
        disk_free = shutil.disk_usage(root).free
    open_titles = {row["title"] for row in open_rows}
    closed: list[str] = []
    kept: list[dict] = []
    for title in [*OBSOLETE_TITLES, STORAGE_TITLE]:
        if title not in open_titles:
            continue
        if title == STORAGE_TITLE and disk_free < STORAGE_WARNING_MARGIN_BYTES:
            kept.append({"title": title, "reason": "disk_below_28gib_prune_backups_first",
                         "disk_free_bytes": disk_free})
            continue
        if not dry_run:
            db.resolve_incidents(title, resolution=f"obsoleto ADR-022: {reason}", actor=actor)
        closed.append(title)
    if not dry_run:
        db.append_audit(EVENT_TYPE, actor=actor, severity="info", payload={
            "idempotency_key": idempotency_key, "reason": reason, "closed": closed,
            "kept": kept,
        })
    return {"schema": "mova-incident-cleanup-v1", "status": "dry_run" if dry_run else "closed",
            "closed": closed, "kept": kept, "disk_free_bytes": disk_free,
            "note": "Local storage headroom low se cierra solo con >=28 GiB libres "
                    "(tras podar backups)."}
