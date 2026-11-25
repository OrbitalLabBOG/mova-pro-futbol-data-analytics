"""ADR-022: alerta única, cierre de incidentes obsoletos y captura privada on-demand."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mova_fpl.ops import health_alert, incident_cleanup, private_capture
from mova_fpl.ops.cli import main
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB
from mova_fpl.ops.tools import TOOLS

GIB = 1024 ** 3






def _config(tmp_path: Path) -> RuntimeConfig:
    import tests.test_operator_contract as contract
    return contract._config(tmp_path)


def test_close_obsolete_is_audited_idempotent_and_keeps_storage_incident(tmp_path):
    config = _config(tmp_path)
    db = OpsDB(config.ops_db, enforce_version=False)
    db.migrate()
    for severity, title in (("P0", "Ejecución FPL ambigua"),
                            ("P1", "Backup recovery observation unhealthy"),
                            ("P2", "Shadow decision falló"),
                            ("P1", "Local storage headroom low"),
                            ("P1", "Servicio de datos MOVA falló")):
        db.open_incident_once(severity, title)
    kwargs = dict(actor="julian", reason="harness retirado", idempotency_key="k1")
    dry = incident_cleanup.close_obsolete(config, db, dry_run=True, disk_free=26 * GIB, **kwargs)
    assert dry["status"] == "dry_run" and len(dry["closed"]) == 3
    result = incident_cleanup.close_obsolete(config, db, disk_free=26 * GIB, **kwargs)
    assert result["status"] == "closed"
    assert set(result["closed"]) == {"Ejecución FPL ambigua",
                                     "Backup recovery observation unhealthy",
                                     "Shadow decision falló"}
    assert result["kept"][0]["title"] == "Local storage headroom low"
    open_titles = {i["title"] for i in _open(db)}
    assert open_titles == {"Local storage headroom low", "Servicio de datos MOVA falló"}
    assert incident_cleanup.close_obsolete(config, db, disk_free=26 * GIB, **kwargs)["status"] == "reused"
    # Con >=28 GiB libres el incidente de disco también cierra.
    later = incident_cleanup.close_obsolete(
        config, db, actor="julian", reason="podado", idempotency_key="k2", disk_free=30 * GIB)
    assert later["closed"] == ["Local storage headroom low"]
    with pytest.raises(ValueError):
        incident_cleanup.close_obsolete(config, db, actor="", reason="x", idempotency_key="k3")


def _open(db):
    con = db.connect(readonly=True)
    try:
        return [dict(r) for r in con.execute(
            "SELECT title FROM incidents WHERE status!='resolved'")]
    finally:
        con.close()


def test_health_alert_fires_once_for_stale_fpl_or_low_disk(tmp_path):
    config = _config(tmp_path)
    db = OpsDB(config.ops_db, enforce_version=False)
    db.migrate()
    now = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)
    events: list[dict] = []
    healthy = {"sources": [{"source_name": "fpl_official", "health": "healthy",
                            "age_seconds": 100}]}
    assert health_alert.run(config, db, now=now, collector_status=healthy,
                            disk_free=50 * GIB, sink=events.append)["healthy"] is True
    sick = {"sources": [{"source_name": "fpl_official", "health": "stale",
                         "age_seconds": 7 * 3600}]}
    first = health_alert.run(config, db, now=now, collector_status=sick,
                             disk_free=50 * GIB, sink=events.append)
    assert first["alerted"] and first["reasons"] == ["fpl_official_unhealthy_over_6h"]
    again = health_alert.run(config, db, now=now + timedelta(hours=1),
                             collector_status=sick, disk_free=50 * GIB, sink=events.append)
    assert again["suppressed"] == "cooldown" and len(events) == 1
    # FPL con 5 h sin éxito aún no alerta; disco bajo sí, tras el cooldown.
    mild = {"sources": [{"source_name": "fpl_official", "health": "stale",
                         "age_seconds": 5 * 3600}]}
    from dataclasses import replace
    low = health_alert.run(replace(config, disk_gate_bytes=20 * GIB), db, now=now + timedelta(hours=13), collector_status=mild,
                           disk_free=19 * GIB, sink=events.append)
    assert low["reasons"] == ["disk_below_20gib"] and len(events) == 2
    # No crea incidentes: no puede bloquear la autoridad.
    assert _open(db) == []


def test_private_capture_wraps_force_script_without_systemd(tmp_path):
    script = tmp_path / "collect-private-team-state.sh"
    script.write_text("#!/usr/bin/env bash\necho captured $@\n")
    script.chmod(0o755)
    calls = []

    def runner(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    ok = private_capture.capture(actor="julian", reason="GW12", idempotency_key="k",
                                 script=script, runner=runner)
    assert ok["status"] == "ok" and calls == [[str(script), "--force"]]
    refused = private_capture.capture(actor="julian", reason="GW12", idempotency_key="k",
                                      force=False, script=script, runner=runner)
    assert refused["status"] == "refused" and len(calls) == 1
    missing = private_capture.capture(actor="a", reason="r", idempotency_key="k",
                                      script=tmp_path / "nope.sh")
    assert missing["status"] == "unavailable" and "private-state capture" in missing["hint"]
    failed = private_capture.capture(
        actor="a", reason="r", idempotency_key="k", script=script,
        runner=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "cooldown"))
    assert failed["status"] == "failed" and failed["returncode"] == 1


def test_private_state_cli_and_week_flag_are_wired(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(private_capture, "capture",
                        lambda **kw: seen.append(kw) or {"status": "ok", "schema": "x"})
    rc = main(["private-state", "capture", "--force", "--actor", "julian",
               "--reason", "GW12", "--idempotency-key", "ps:1"])
    assert rc == 0 and seen[0]["force"] is True and seen[0]["idempotency_key"] == "ps:1"
    assert json.loads(capsys.readouterr().out)["status"] == "ok"
    with pytest.raises(SystemExit):
        main(["private-state", "capture", "--force"])  # exige actor/reason/key
    from mova_fpl.ops.cli import main as cli_main  # noqa: F401
    source = Path("mova_fpl/ops/cli.py").read_text()
    assert source.count("--capture-private-state") == 2


def test_tools_catalog_lists_new_write_memory_commands():
    names = {t.name: t for t in TOOLS}
    assert names["incidents.close_obsolete"].side_effect == "write-memory"
    assert names["private_state.capture"].side_effect == "write-memory"
