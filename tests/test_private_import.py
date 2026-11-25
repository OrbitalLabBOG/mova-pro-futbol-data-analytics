"""`private-state import`: normalización, seguridad y uso inmediato por el acta."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone

import pytest

from mova_fpl.data.private_state import load, normalize_import, validate
from mova_fpl.ops.cli import main
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB
from mova_fpl.ops.team_state import import_snapshot

TEAM = 424242  # id sintético
DEADLINE = "2026-11-27T18:30:00Z"
NOW = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)
TYPES = [1, 1] + [2] * 5 + [3] * 5 + [4] * 3


def raw_my_team() -> dict:
    """Forma my-team/sanitizada que ya aceptaba validate()."""
    return {
        "schema": "mova-fpl-private-team-state-v1", "observed_at": "2026-11-26T11:59:00Z",
        "team_id": TEAM, "event": {"id": 12, "deadline_time": DEADLINE},
        "picks_last_updated": None,
        "picks": [{"element": i, "element_type": t, "position": i,
                   "multiplier": 2 if i == 5 else 1 if i <= 11 else 0,
                   "is_captain": i == 5, "is_vice_captain": i == 10,
                   "purchase_price": 50 + i, "selling_price": 50 + i}
                  for i, t in enumerate(TYPES, start=1)],
        "transfers": {"bank": 14, "value": 1000, "limit": 1, "made": 0, "cost": 0,
                      "status": "cost"},
        "chips": [{"name": "wildcard", "number": 1, "status_for_entry": "available",
                   "is_pending": False, "start_event": 2, "stop_event": 19}],
    }


def simplified() -> dict:
    return {
        "team_id": TEAM, "gw": 12, "deadline_time": DEADLINE,
        "observed_at": "2026-11-26T11:59:00Z",
        "picks": [{"element": i, "position": i, "pos": ["GKP", "DEF", "MID", "FWD"][t - 1],
                   "selling_price": 50 + i, "purchase_price": 50 + i,
                   "is_captain": i == 5, "is_vice_captain": i == 10,
                   "ui_junk": "x"}
                  for i, t in enumerate(TYPES, start=1)],
        "bank": 14, "free_transfers": 2, "chips": ["wildcard", "freehit"],
        "cookie": "NO-DEBE-PASAR",
    }


def test_raw_my_team_normalizes():
    payload = normalize_import(raw_my_team(), expected_team_id=TEAM)
    normalized, quality = validate(payload, expected_team_id=TEAM)
    assert quality["free_transfers"] == 1 and quality["bank_tenths"] == 14
    assert normalized["transfers"]["limit"] == 1


def test_simplified_snapshot_normalizes_and_drops_unknown_keys():
    payload = normalize_import(simplified(), expected_team_id=TEAM)
    assert "cookie" not in payload and all("ui_junk" not in p for p in payload["picks"])
    normalized, quality = validate(payload, expected_team_id=TEAM)
    assert quality["free_transfers"] == 2 and quality["bank_tenths"] == 14
    assert quality["available_chips"] == ["freehit", "wildcard"]
    captain = [p for p in normalized["picks"] if p["is_captain"]]
    assert [p["element"] for p in captain] == [5] and captain[0]["multiplier"] == 2


def test_unknown_keys_are_dropped_from_raw_shape_too():
    doc = raw_my_team()
    doc["picks"][0]["cookies"] = "x"
    doc["transfers"]["secret"] = "x"
    payload = normalize_import(doc, expected_team_id=TEAM)
    validate(payload, expected_team_id=TEAM)


def test_wrong_team_id_rejected():
    doc = simplified()
    doc["team_id"] = TEAM + 1
    with pytest.raises(ValueError, match="team_id"):
        normalize_import(doc, expected_team_id=TEAM)


def test_null_transfer_limit_handled():
    """limit=null (chip activo / sin tope): no crashea; FT = supuesto conservador."""
    doc = raw_my_team()
    doc["transfers"]["limit"] = None
    normalized, quality = validate(normalize_import(doc, expected_team_id=TEAM),
                                   expected_team_id=TEAM)
    assert normalized["transfers"]["limit"] is None
    assert quality["free_transfers"] == 1 and quality["free_transfers_assumed"] is True
    doc["transfers"]["made"] = 2
    _, quality = validate(normalize_import(doc, expected_team_id=TEAM), expected_team_id=TEAM)
    assert quality["free_transfers"] == 0
    # llave ausente: se normaliza igual que null
    del doc["transfers"]["limit"]
    _, quality = validate(normalize_import(doc, expected_team_id=TEAM), expected_team_id=TEAM)
    assert quality["free_transfers_assumed"] is True


def test_millions_instead_of_tenths_rejected():
    doc = simplified()
    doc["picks"][0]["selling_price"] = 5.5
    with pytest.raises(ValueError, match="fuera de rango"):
        validate(normalize_import(doc, expected_team_id=TEAM), expected_team_id=TEAM)


def _config(tmp_path) -> RuntimeConfig:
    return RuntimeConfig(ops_db=tmp_path / "ops.db", artifact_root=tmp_path / "art",
                         analytics_root=tmp_path / "an", canonical_db=tmp_path / "c.db",
                         postgres_credential_file=tmp_path / "none", team_id=TEAM)


def test_import_seals_with_operator_label_and_is_idempotent(tmp_path):
    config = _config(tmp_path)
    db = OpsDB(config.ops_db, enforce_version=False)
    db.migrate()
    first = import_snapshot(config, db, simplified(), now=NOW, actor="bot", reason="t",
                            idempotency_key="k1")
    assert first["status"] == "completed" and first["source_name"] == "operator_import"
    normalized, manifest = load(__import__("pathlib").Path(first["artifact_path"]),
                                expected_team_id=TEAM)
    assert manifest["source_label"] == "operator_import"
    state = db.latest_team_state(first["cycle_id"])
    assert state["source_name"] == "operator_import"
    again = import_snapshot(config, db, simplified(), now=NOW)
    assert again["status"] == "reused" and again["artifact_path"] == first["artifact_path"]


def test_cli_private_state_import(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MOVA_SQLITE_MIN_VERSION", "3.0.0")
    monkeypatch.setenv("MOVA_OPS_DB", str(tmp_path / "ops.db"))
    monkeypatch.setenv("MOVA_ARTIFACT_ROOT", str(tmp_path / "art"))
    monkeypatch.setenv("MOVA_TEAM_ID", str(TEAM))
    f = tmp_path / "snap.json"
    f.write_text(json.dumps(simplified()))
    code = main(["private-state", "import", "--file", str(f), "--actor", "bot",
                 "--reason", "test", "--idempotency-key", "k"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["source_name"] == "operator_import"
