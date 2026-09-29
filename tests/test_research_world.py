from __future__ import annotations

from datetime import datetime, timezone

from mova_fpl.ops.analytics_store import AnalyticsStore


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params=None):
        sql = " ".join(query.split())
        if "from raw.source_artifacts" in sql and "limit 2" in sql:
            return _Rows([
                {"artifact_id": "new", "observed_at": datetime(2026, 9, 20, tzinfo=timezone.utc)},
                {"artifact_id": "old", "observed_at": datetime(2026, 9, 19, tzinfo=timezone.utc)},
            ])
        if "from raw.source_artifacts" in sql:
            return _Rows([{"artifact_id": "new"}])
        if "from analytics.player_projections" in sql and "element=any" in sql:
            return _Rows([{"element": 1, "xp": 2.3, "p_play": 0.8, "p_60": 0.7}])
        if "from analytics.player_projections" in sql:
            return _Rows([{"element": 2, "xp": 6.1, "p_play": 0.95, "p_60": 0.9}])
        if "from analytics.fpl_fixture_observations" in sql:
            return _Rows([{"event": 6, "kickoff_time": None,
                           "home": "ABC", "away": "DEF"}])
        if "from analytics.fpl_player_observations p" in sql and "join" in sql:
            if "p.element=any" in sql:
                return _Rows([
                    {"element": element, "web_name": name, "team_id": team_id,
                     "element_type": 3, "status": "a", "chance_next": None,
                     "news": "", "team_name": team, "team_short": team,
                     "full_name": name}
                    for element, name, team_id, team in (
                        (1, "Owned", 1, "ABC"), (2, "Candidate", 2, "DEF"))
                ])
            return _Rows([
                {"element": 1, "web_name": "Owned", "team_id": 1,
                 "team": "ABC", "status": "a", "chance_next": None, "news": ""},
                {"element": 2, "web_name": "Candidate", "team_id": 2,
                 "team": "DEF", "status": "d", "chance_next": 75,
                 "news": "New injury"},
            ])
        if "from analytics.fpl_player_observations where artifact_id" in sql:
            return _Rows([
                {"element": 1, "status": "a", "chance_next": None, "news": ""},
                {"element": 2, "status": "a", "chance_next": None, "news": ""},
            ])
        raise AssertionError(sql)


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


def test_owned_projection_is_resolved_even_below_candidate_cutoff(monkeypatch):
    monkeypatch.setattr("mova_fpl.ops.analytics_store.connect", lambda *_a, **_k: _Connection())
    now = datetime(2026, 9, 20, tzinfo=timezone.utc)
    focus = AnalyticsStore(object()).research_focus(
        squad=[{"element": 1, "position": 1}], batch_id="baseline",
        candidate_limit=1, as_of=now,
    )
    assert {row["element"] for row in focus} == {1, 2}
    assert next(row for row in focus if row["element"] == 1)["xp"] == 2.3


def test_world_uses_official_ids_deltas_and_fixture_horizon(monkeypatch):
    monkeypatch.setattr("mova_fpl.ops.analytics_store.connect", lambda *_a, **_k: _Connection())
    world = AnalyticsStore(object()).research_world(
        as_of=datetime(2026, 9, 20, tzinfo=timezone.utc), target_gw=6,
    )
    assert world["catalog"] == [[1, "Owned", "ABC"], [2, "Candidate", "DEF"]]
    assert world["alerts"][0]["element"] == 2
    assert world["alerts"][0]["changed"] is True
    assert world["fixtures"] == [[6, "ABC", "DEF", None]]
