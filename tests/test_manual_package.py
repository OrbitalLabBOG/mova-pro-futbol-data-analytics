"""`mova execute manual-package` arma un paquete v2 que `record-manual` acepta."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mova_fpl.ops.cli import main
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB
from mova_fpl.ops.manual_package import build_manual_package
from mova_fpl.ops.supervised import SCHEMA, record
from tests.test_manual_verified import _state


def _write(root: Path, name: str, state: dict) -> Path:
    directory = root / "private" / name
    directory.mkdir(parents=True)
    (directory / "team-state.json").write_text(json.dumps(state, sort_keys=True) + "\n")
    return directory


def _inputs(root: Path, *, transfer=False):
    pre = _state(list(range(1, 16)), observed_at="2026-09-17T12:00:00Z", captain=1, vice=2)
    order = [*range(1, 11), 12, 11, 13, 14, 15]
    post = _state(order, observed_at="2026-09-17T12:03:00Z", captain=7, vice=8)
    if transfer:
        post["picks"][13]["element"] = 16
        post["picks"][13]["element_type"] = 4
    evidence = root / "manual" / "evidence.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("{}\n")
    return _write(root, "pre", pre), _write(root, "post", post), evidence


def _config(root: Path) -> RuntimeConfig:
    return RuntimeConfig(ops_db=root / "ops.db", artifact_root=root)


def _build(root: Path, **overrides):
    pre, post, evidence = _inputs(root, transfer=overrides.pop("transfer", False))
    values = dict(gw=5, season="2026-27", approved_by="julian",
                  approved_at="2026-09-17T11:55:00Z", operations=["lineup,captaincy"],
                  pre_state=pre, post_state=post / "team-state.json", evidence=evidence,
                  rationale="OK de Julián en chat")
    values.update(overrides)
    return build_manual_package(_config(root), **values)


def test_paquete_r2_valido_y_aceptado_por_record_manual(tmp_path, monkeypatch):
    result = _build(tmp_path)
    assert result["status"] == "ready" and result["risk_class"] == "R2"
    package = json.loads(Path(result["package_path"]).read_text())
    assert package["schema"] == SCHEMA
    assert package["authorization"]["allowed_operations"] == ["captaincy", "lineup"]
    assert package["execution"]["started_at"] == "2026-09-17T12:00:00Z"
    assert package["execution"]["finished_at"] == "2026-09-17T12:03:00Z"
    assert result["next_command"][:3] == ["mova", "execute", "record-manual"]
    # idempotente: misma entrada, mismos bytes
    assert _build_again(tmp_path)["package_sha256"] == result["package_sha256"]

    monkeypatch.setenv("MOVA_OPS_DB", str(tmp_path / "ops.db"))
    monkeypatch.setenv("MOVA_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("MOVA_SQLITE_MIN_VERSION", "3.0.0")
    db = OpsDB(tmp_path / "ops.db", enforce_version=False)
    db.migrate()
    db.upsert_cycle("2026-27", 5, "2026-09-18T17:30:00Z", phase="execution")
    recorded = record(Path(result["package_path"]), actor="assistant", reason="registro",
                      idempotency_key="manual:gw05:pkg")
    assert recorded["status"] == "completed" and recorded["risk_class"] == "R2"


def _build_again(root: Path):
    pre, post = root / "private" / "pre", root / "private" / "post"
    return build_manual_package(
        _config(root), gw=5, season="2026-27", approved_by="julian",
        approved_at="2026-09-17T11:55:00Z", operations=["lineup", "captaincy"],
        pre_state=pre, post_state=post, evidence=root / "manual" / "evidence.json",
        rationale="OK de Julián en chat")


def test_transferencia_exige_r3_y_operacion_autorizada(tmp_path):
    with pytest.raises(ValueError, match="no cubre transferencias"):
        _build(tmp_path, transfer=True)
    assert not (tmp_path / "manual" / "gw05-execution-v2.json").exists()
    assert not (tmp_path / "manual" / "gw05-execution-v2" / "decision.json").exists()


def test_transferencia_autorizada(tmp_path):
    result = _build(tmp_path, transfer=True, operations=["lineup,captaincy,transfers"])
    assert result["risk_class"] == "R3" and result["action_level"] == "A3"
    assert result["transfers_in"] == [16] and result["transfers_out"] == [14]


def test_rechaza_ventanas_y_rutas_invalidas(tmp_path):
    with pytest.raises(ValueError, match="ventana"):
        _build(tmp_path / "a", approved_at="2026-09-17T12:30:00Z",
               started_at="2026-09-17T12:01:00Z")
    with pytest.raises(ValueError, match="operations"):
        _build(tmp_path / "b", operations=["save"])
    with pytest.raises(ValueError, match="MOVA_ARTIFACT_ROOT"):
        _build(tmp_path / "c", out=tmp_path / "elsewhere" / "pkg.json")


def test_no_sobrescribe_contenido_distinto(tmp_path):
    _build(tmp_path)
    with pytest.raises(FileExistsError):
        build_manual_package(
            _config(tmp_path), gw=5, season="2026-27", approved_by="julian",
            approved_at="2026-09-17T11:55:00Z", operations=["lineup,captaincy"],
            pre_state=tmp_path / "private" / "pre", post_state=tmp_path / "private" / "post",
            evidence=tmp_path / "manual" / "evidence.json", rationale="otra razón")


def test_cli_manual_package(tmp_path, monkeypatch, capsys):
    pre, post, evidence = _inputs(tmp_path)
    monkeypatch.setenv("MOVA_OPS_DB", str(tmp_path / "missing" / "ops.db"))
    monkeypatch.setenv("MOVA_ARTIFACT_ROOT", str(tmp_path))
    assert main(["execute", "manual-package", "--gw", "5", "--approved-by", "julian",
                 "--approved-at", "2026-09-17T11:55:00Z", "--operations", "lineup",
                 "--operations", "captaincy", "--pre-state", str(pre), "--post-state", str(post),
                 "--evidence", str(evidence), "--rationale", "OK en chat"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "mova-manual-package-result-v1"
    assert not (tmp_path / "missing").exists()
