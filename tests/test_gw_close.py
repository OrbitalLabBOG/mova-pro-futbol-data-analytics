"""`mova gw close`: cierre con picks públicos + nota decision, sin settle-auto."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mova_fpl.ops import gw as gw_mod
from mova_fpl.ops.cli import main
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB
from mova_fpl.ops.memory import add_note

TEAM = 424242  # sintético
GW = 11
POINTS = {1: 2, 2: 0, 3: 6, 4: 1, 5: 8, 6: 2, 7: 3, 8: 12, 9: 1, 10: 5, 11: 2,
          12: 1, 13: 0, 14: 3, 15: 2}


def boot(finished=True, checked=True):
    return {"events": [{"id": GW, "finished": finished, "data_checked": checked}],
            "elements": [{"id": i, "web_name": f"Jug{i}", "second_name": f"Ap{i}"}
                         for i in POINTS]}


class FakeFPL:
    def __init__(self, **kw):
        self.kw, self.calls = kw, []

    def bootstrap(self):
        return boot(**self.kw)

    def picks(self, team_id, gw):
        self.calls.append(("picks", team_id, gw))
        return {"active_chip": None,
                "entry_history": {"points": 50, "event_transfers_cost": 4,
                                  "event_transfers": 1, "points_on_bench": 7},
                "picks": [{"element": i, "position": i, "is_captain": i == 5,
                           "is_vice_captain": i == 10,
                           "multiplier": 2 if i == 5 else 1 if i <= 11 else 0}
                          for i in range(1, 16)]}

    def event_live(self, gw):
        return {"elements": [{"id": i, "stats": {"total_points": p}}
                             for i, p in POINTS.items()]}


def config(tmp_path):
    return RuntimeConfig(ops_db=tmp_path / "ops.db", artifact_root=tmp_path / "art",
                         analytics_root=tmp_path / "an", canonical_db=tmp_path / "c.db",
                         postgres_credential_file=tmp_path / "none", team_id=TEAM)


def seeded(tmp_path, with_decision=True):
    cfg = config(tmp_path)
    db = OpsDB(cfg.ops_db, enforce_version=False)
    db.migrate()
    if with_decision:
        add_note(db, season=cfg.season, gw=GW, kind="decision", text="XI aprobado",
                 players={"xi": [1, 2, 3, 4, 5, 6, 7, "Jug8", 9, 10, 12],
                          "bench": [11, 13, 14, 15], "captain": "Jug8", "vice_captain": 5,
                          "hits": 0},
                 source="owner", actor="julian", reason="OK en chat",
                 idempotency_key="decision:gw11")
    return cfg, db


def test_close_exact_metrics_without_verified_execution(tmp_path):
    cfg, db = seeded(tmp_path)
    fake = FakeFPL()
    out = gw_mod.close_gw(cfg, db, gw=GW, fetcher=fake, actor="bot", reason="cierre",
                          idempotency_key="close:gw11")
    assert out["status"] == "settled" and out["settle_auto_used"] is False
    assert out["official_points"] == 50 and out["transfers_cost"] == 4
    assert out["official_net_points"] == 46
    assert out["actual_xi_points_recomputed"] == 50 and out["reconciled"] is True
    d = out["decision"]
    assert d["decided_xi_points"] == 53 and d["delta_decided_minus_actual"] == 3
    assert d["xi_overlap"] == 10 and d["xi_missing_from_actual"] == [12]
    assert d["decided_captain"] == 8 and out["actual_captain"] == 5
    assert d["captain_match"] is False and d["decided_captain_points"] == 12
    assert d["chip_match"] is True and d["unresolved_players"] == []
    assert fake.calls == [("picks", TEAM, GW)]
    # el post_mortem quedó en memoria, y sin ninguna fila de ejecución web
    notes = db.strategy_notes(season=cfg.season, gw=GW, kinds=("post_mortem",))
    assert len(notes) == 1 and notes[0]["players"]["official_points"] == 50
    with db.connect(readonly=True) as con:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master")}
        if "web_executions" in tables:
            assert con.execute("SELECT count(*) FROM web_executions").fetchone()[0] == 0


def test_close_is_idempotent(tmp_path):
    cfg, db = seeded(tmp_path)
    for _ in range(2):
        gw_mod.close_gw(cfg, db, gw=GW, fetcher=FakeFPL(), actor="bot", reason="cierre",
                        idempotency_key="close:gw11")
    assert len(db.strategy_notes(season=cfg.season, gw=GW, kinds=("post_mortem",))) == 1


def test_close_without_decision_note_still_settles(tmp_path):
    cfg, db = seeded(tmp_path, with_decision=False)
    out = gw_mod.close_gw(cfg, db, gw=GW, fetcher=FakeFPL(), actor="bot", reason="cierre",
                          idempotency_key="close:gw11")
    assert out["decision_note_found"] is False and out["decision"] is None


def test_unsettled_gw_raises(tmp_path):
    cfg, db = seeded(tmp_path)
    for kw in ({"finished": False}, {"checked": False}):
        with pytest.raises(gw_mod.GWNotSettled):
            gw_mod.close_gw(cfg, db, gw=GW, fetcher=FakeFPL(**kw), actor="b", reason="r",
                            idempotency_key="k")
    assert not db.strategy_notes(season=cfg.season, gw=GW, kinds=("post_mortem",))


def test_cli_exit_codes(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MOVA_SQLITE_MIN_VERSION", "3.0.0")
    monkeypatch.setenv("MOVA_OPS_DB", str(tmp_path / "ops.db"))
    monkeypatch.setenv("MOVA_ARTIFACT_ROOT", str(tmp_path / "art"))
    monkeypatch.setenv("MOVA_TEAM_ID", str(TEAM))
    cfg, db = seeded(tmp_path)
    import mova_fpl.ops.week_brief as wb
    argv = ["gw", "close", "--gw", str(GW), "--actor", "bot", "--reason", "cierre",
            "--idempotency-key", "close:cli"]
    monkeypatch.setattr(wb, "PublicFPL", lambda: FakeFPL(finished=False))
    assert main(argv) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "unsettled"
    monkeypatch.setattr(wb, "PublicFPL", lambda: FakeFPL())
    assert main(argv + ["--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["official_points"] == 50
    assert not db.strategy_notes(season=cfg.season, gw=GW, kinds=("post_mortem",))


def test_close_does_not_depend_on_settle_auto():
    source = Path(gw_mod.__file__).read_text()
    assert "ops.review" not in source and "settle_auto" not in source.replace(
        "settle_auto_used", "")
