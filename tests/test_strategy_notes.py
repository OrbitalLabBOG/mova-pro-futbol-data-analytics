"""Memoria append-only del copiloto: `strategy_notes` + `mova memory`."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from mova_fpl.ops.cli import main
from mova_fpl.ops.db import OpsDB
from mova_fpl.ops.memory import NOTE_KINDS, add_note, list_notes, read_memory, sanitize_text
from mova_fpl.ops.schema import MIGRATIONS
from mova_fpl.postgres.importer import TABLES
from mova_fpl.postgres.store import MIGRATIONS as PG_MIGRATIONS

ROOT = Path(__file__).resolve().parents[1]
DECISION = {"xi": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11], "bench": [12, 13, 14, 15],
            "captain": 5, "vice_captain": 10, "transfers_in": [], "transfers_out": [],
            "hits": 0, "chip": None}


def _db(tmp_path: Path) -> OpsDB:
    return OpsDB(tmp_path / "ops.db", enforce_version=False)


def _note(db, **overrides):
    values = dict(season="2026-27", gw=12, kind="decision", text="XI aprobado por Julián",
                  players=DECISION, source="owner", actor="assistant",
                  reason="OK en chat", idempotency_key="note:gw12:decision:1")
    values.update(overrides)
    return add_note(db, **values)


def test_migracion_25_y_espejo_postgres_registrado():
    assert MIGRATIONS[-1][:2] == (25, "copilot_strategy_notes")
    assert "decision" in NOTE_KINDS and len(NOTE_KINDS) == 6
    spec = next(item for item in TABLES if item.source_table == "strategy_notes")
    assert spec.target_table == "agent.strategy_notes"
    assert spec.renames == {"players_json": "players"}
    sql = (PG_MIGRATIONS / "028_strategy_notes.sql").read_text(encoding="utf-8").lower()
    for kind in NOTE_KINDS:
        assert f"'{kind}'" in sql
    assert "players jsonb not null" in sql and "idempotency_key text not null unique" in sql


def test_nota_decision_idempotente_y_append_only(tmp_path):
    db = _db(tmp_path)
    first = _note(db)
    assert first["status"] == "completed" and first["schema"] == "mova-strategy-note-v1"
    note = first["note"]
    assert note["cycle_id"] == "2026-27-gw12" and note["players"]["captain"] == 5
    assert _note(db)["status"] == "reused"
    with pytest.raises(ValueError, match="otro contenido"):
        _note(db, text="otro XI")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        with db.transaction() as con:
            con.execute("UPDATE strategy_notes SET text='x'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        with db.transaction() as con:
            con.execute("DELETE FROM strategy_notes")
    with db.connect(readonly=True) as con:
        assert con.execute("SELECT COUNT(*) FROM audit_events "
                           "WHERE event_type='strategy_note_recorded'").fetchone()[0] == 1


def test_supersede_y_listado(tmp_path):
    db = _db(tmp_path)
    original = _note(db)["note"]
    revised = dict(DECISION, captain=10, vice_captain=5)
    _note(db, players=revised, idempotency_key="note:gw12:decision:2",
          supersedes_note_id=original["note_id"], reason="cambio de capitán")
    _note(db, kind="owner_preference", text="No gastar hits antes de GW15", players=[],
          idempotency_key="note:gw11:pref", gw=11)
    notes = list_notes(db, season="2026-27", gw=12)["notes"]
    assert [item["superseded"] for item in notes] == [False, True]
    with pytest.raises(ValueError, match="inexistente"):
        _note(db, idempotency_key="note:bad", supersedes_note_id="note_missing")
    memory = read_memory(db, season="2026-27", gw=12)
    assert memory["schema"] == "mova-memory-v1"
    assert memory["sections"]["notes"]["status"] == "ok"
    previous = memory["sections"]["previous_notes"]["data"]
    assert [item["kind"] for item in previous] == ["owner_preference"]


@pytest.mark.parametrize("players, message", [
    ([1, 2], "objeto"),
    ({"captain": 5, "vice_captain": 5}, "distintos"),
    ({"xi": [1, 2, 3]}, "11 jugadores"),
    ({"xi": DECISION["xi"], "captain": 99}, "titular"),
    ({"transfers_in": [1], "transfers_out": []}, "desbalanceados"),
    ({"chip": "triple"}, "chip desconocido"),
    ({"notes": "solo texto"}, "al menos"),
])
def test_nota_decision_valida_players(tmp_path, players, message):
    with pytest.raises(ValueError, match=message):
        _note(_db(tmp_path), players=players)


def test_sanea_emails_tokens_y_query_strings(tmp_path):
    raw = ("Julián (owner@example.com) pegó https://x.test/a?apiKey=abcdefghijklmnop "
           "y Bearer abcdefghijklmnopqrstuvwxyz y token=abc123")
    clean, count = sanitize_text(raw)
    assert "@" not in clean and "apiKey" not in clean and "abc123" not in clean
    assert "abcdefghijklmnopqrstuvwxyz" not in clean and count >= 4
    result = _note(_db(tmp_path), kind="reason", text=raw, players={"src": raw},
                   idempotency_key="note:sanitized")
    assert result["redactions"] >= 8
    stored = json.dumps(result["note"])
    assert "example.com" not in stored and "abc123" not in stored


def test_requiere_actor_reason_y_key(tmp_path):
    for field in ("actor", "reason", "idempotency_key"):
        with pytest.raises(ValueError, match=field):
            _note(_db(tmp_path), **{field: " "})
    with pytest.raises(ValueError, match="text excede"):
        _note(_db(tmp_path), kind="reason", text="x" * 2001, players=[])


def test_lectura_sin_ops_db_no_crea_archivos(tmp_path):
    db = OpsDB(tmp_path / "nope" / "ops.db", enforce_version=False)
    assert list_notes(db, season="2026-27")["status"] == "missing"
    memory = read_memory(db, season="2026-27", gw=12)
    assert memory["status"] == "empty" and "notes" in memory["missing_on_vps"]
    assert not (tmp_path / "nope").exists()


def test_cli_memory_note_add_list_read(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MOVA_OPS_DB", str(tmp_path / "ops.db"))
    monkeypatch.setenv("MOVA_SQLITE_MIN_VERSION", "3.0.0")
    assert main(["memory", "note", "add", "--gw", "12", "--kind", "decision", "--text",
                 "XI y C aprobados", "--source", "owner", "--players-json",
                 json.dumps(DECISION), "--actor", "assistant", "--reason", "OK en chat",
                 "--idempotency-key", "note:cli:1"]) == 0
    added = json.loads(capsys.readouterr().out)
    assert added["status"] == "completed" and added["note"]["kind"] == "decision"
    assert main(["memory", "note", "list", "--gw", "12", "--kind", "decision"]) == 0
    assert len(json.loads(capsys.readouterr().out)["notes"]) == 1
    assert main(["memory", "read", "--gw", "12"]) == 0
    assert json.loads(capsys.readouterr().out)["sections"]["notes"]["status"] == "ok"
