"""Persistencia PostgreSQL del servicio de datos."""

from __future__ import annotations

import uuid
import json
from datetime import datetime, timezone

from psycopg.types.json import Jsonb

from mova_fpl.postgres.store import connect
from mova_fpl.ops.collector.contracts import canonical_bytes, write_atomic


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _number(value, cast=float):
    if value in (None, ""):
        return None
    try:
        return cast(value)
    except (TypeError, ValueError):
        return None


def cursor_is_due(row: dict | None, cadence_seconds: int, *, now: datetime,
                  force: bool = False) -> bool:
    """Respeta cadencia desde el último intento fallido o último éxito."""
    if force or not row:
        return True
    observed = (row.get("last_attempt_at") if row.get("last_status") == "failed"
                else row.get("last_success_at"))
    if observed is None:
        return True
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return (now - observed).total_seconds() >= cadence_seconds


class CollectorStore:
    def __init__(self, config):
        self.config = config

    def is_due(self, source: str, cadence_seconds: int, *, now: datetime,
               force: bool = False) -> tuple[bool, dict | None]:
        with connect(self.config, autocommit=True) as con:
            row = con.execute(
                "select * from raw.source_cursors where source_name=%s", (source,)
            ).fetchone()
        return cursor_is_due(row, cadence_seconds, now=now, force=force), row

    def start(self, source: str, job_id: str) -> str:
        run_id = _id("ingest")
        with connect(self.config, autocommit=True) as con:
            con.execute(
                "insert into raw.ingestion_runs(run_id,job_id,source_name,status,started_at) "
                "values(%s,%s,%s,'running',now())", (run_id, job_id, source),
            )
        return run_id

    def finish(self, run_id: str, *, source: str, cadence_seconds: int, status: str,
               output: dict | None = None, error: Exception | None = None) -> None:
        result = output or {}
        payload_sha = result.get("payload_sha256")
        detail = {"quality": result.get("quality", {}), "rows": result.get("rows", {})}
        with connect(self.config) as con:
            con.execute(
                "update raw.ingestion_runs set status=%s,finished_at=now(),artifact_path=%s,"
                "payload_sha256=%s,manifest_sha256=%s,quality=%s,metrics=%s,error_code=%s,"
                "error_detail=%s where run_id=%s",
                (status, result.get("artifact_path"), payload_sha,
                 result.get("manifest_sha256"), Jsonb(result.get("quality", {})),
                 Jsonb(result.get("metrics", {})), type(error).__name__ if error else None,
                 str(error)[:2000] if error else None, run_id),
            )
            success = status in {"completed", "degraded"} and output is not None
            con.execute(
                """
                insert into raw.source_cursors(source_name,last_attempt_at,last_success_at,
                  last_payload_sha256,last_status,consecutive_failures,cadence_seconds,detail)
                values(%s,now(),case when %s then now() end,%s,%s,
                  case when %s then 0 else 1 end,%s,%s)
                on conflict(source_name) do update set
                  last_attempt_at=excluded.last_attempt_at,
                  last_success_at=case when %s then now() else raw.source_cursors.last_success_at end,
                  last_payload_sha256=coalesce(excluded.last_payload_sha256,
                    raw.source_cursors.last_payload_sha256),
                  last_status=excluded.last_status,
                  consecutive_failures=case when %s then 0
                    else raw.source_cursors.consecutive_failures+1 end,
                  cadence_seconds=excluded.cadence_seconds,detail=excluded.detail
                """,
                (source, success, payload_sha, status if status != "skipped" else "completed",
                 success, cadence_seconds, Jsonb(detail), success, success),
            )

    def register_artifact(self, *, run_id: str, source: str, season: str,
                          observed_at: str, artifact_path: str, payload_sha256: str,
                          manifest_sha256: str, byte_count: int, row_count: int,
                          quality_status: str, quality: dict) -> tuple[str, bool]:
        artifact_id = _id("artifact")
        with connect(self.config) as con:
            row = con.execute(
                "select artifact_id from raw.source_artifacts "
                "where source_name=%s and payload_sha256=%s", (source, payload_sha256),
            ).fetchone()
            if row:
                return row["artifact_id"], True
            con.execute(
                """
                insert into raw.source_artifacts(artifact_id,run_id,source_name,season,
                  observed_at,artifact_path,payload_sha256,manifest_sha256,byte_count,row_count,
                  quality_status,quality) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (artifact_id, run_id, source, season, observed_at, artifact_path,
                 payload_sha256, manifest_sha256, byte_count, row_count,
                 quality_status, Jsonb(quality)),
            )
        return artifact_id, False

    def record_checks(self, run_id: str, source: str, checks: list[dict]) -> None:
        if not checks:
            return
        rows = [(_id("check"), run_id, source, item["name"], item["passed"],
                 Jsonb(item.get("expected", {})), Jsonb(item.get("observed", {})))
                for item in checks]
        with connect(self.config) as con:
            with con.cursor() as cur:
                cur.executemany(
                    "insert into raw.quality_checks(check_id,run_id,source_name,check_name,"
                    "passed,expected,observed) values(%s,%s,%s,%s,%s,%s,%s)", rows,
                )

    def load_fpl_surface(self, artifact_id: str, season: str, observed_at: str,
                         boot: dict) -> dict:
        """Backfill idempotente de clubes/GWs, incluso para un artifact ya visto."""
        teams = [(
            artifact_id, season, observed_at, int(item["id"]),
            str(item.get("name") or ""), str(item.get("short_name") or ""),
            _number(item.get("strength"), int), Jsonb(item),
        ) for item in boot["teams"]]
        events = [(
            artifact_id, season, observed_at, int(item["id"]),
            str(item.get("name") or ""), item["deadline_time"],
            bool(item.get("finished")), bool(item.get("data_checked")),
            bool(item.get("is_previous")), bool(item.get("is_current")),
            bool(item.get("is_next")), Jsonb(item),
        ) for item in boot["events"]]
        with connect(self.config) as con:
            with con.cursor() as cur:
                cur.executemany(
                    """insert into analytics.fpl_team_observations values(
                    %s,%s,%s,%s,%s,%s,%s,%s) on conflict do nothing""", teams,
                )
                cur.executemany(
                    """insert into analytics.fpl_event_observations values(
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict do nothing""", events,
                )
        return {"teams": len(teams), "events": len(events)}

    def load_fpl(self, artifact_id: str, season: str, observed_at: str,
                 boot: dict, fixtures: list, entry: dict, history: dict,
                 picks: dict | None) -> dict:
        surface = self.load_fpl_surface(artifact_id, season, observed_at, boot)
        players = []
        for item in boot["elements"]:
            players.append((
                artifact_id, season, observed_at, int(item["id"]), _number(item.get("code"), int),
                int(item["team"]), int(item["element_type"]), str(item.get("web_name") or ""),
                int(item["now_cost"]), item.get("status"),
                _number(item.get("chance_of_playing_next_round"), int),
                _number(item.get("selected_by_percent")), _number(item.get("total_points"), int),
                _number(item.get("minutes"), int), _number(item.get("starts"), int),
                _number(item.get("form")), _number(item.get("points_per_game")),
                _number(item.get("expected_goals")), _number(item.get("expected_assists")),
                _number(item.get("expected_goal_involvements")),
                _number(item.get("expected_goals_conceded")), item.get("news") or "", Jsonb(item),
            ))
        fixture_rows = [(
            artifact_id, season, observed_at, int(item["id"]), item.get("event"),
            item.get("kickoff_time"), int(item["team_h"]), int(item["team_a"]),
            item.get("team_h_score"), item.get("team_a_score"), item.get("started"),
            item.get("finished"), item.get("finished_provisional"), item.get("minutes"),
            Jsonb(item.get("stats") or []), Jsonb(item),
        ) for item in fixtures]
        current = list(history.get("current") or [])
        latest = max(current, key=lambda item: int(item.get("event") or 0), default={})
        entry_row = (
            artifact_id, season, observed_at, int(entry["id"]),
            entry.get("summary_overall_points"), entry.get("summary_overall_rank"),
            latest.get("points"), latest.get("overall_rank"), latest.get("event"),
            Jsonb(entry), Jsonb(history),
        )
        pick_rows = []
        pick_event = int((picks or {}).get("entry_history", {}).get("event") or 0)
        for item in (picks or {}).get("picks", []):
            pick_rows.append((
                artifact_id, season, observed_at, int(entry["id"]), pick_event,
                int(item["element"]), int(item["position"]), int(item["multiplier"]),
                bool(item.get("is_captain")), bool(item.get("is_vice_captain")),
                item.get("selling_price"), item.get("purchase_price"), Jsonb(item),
            ))
        with connect(self.config) as con:
            with con.cursor() as cur:
                cur.executemany(
                    """insert into analytics.fpl_player_observations values(
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    players,
                )
                cur.executemany(
                    """insert into analytics.fpl_fixture_observations values(
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", fixture_rows,
                )
                cur.execute(
                    "insert into game.fpl_entry_observations values("
                    "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", entry_row,
                )
                if pick_rows:
                    cur.executemany(
                        """insert into game.fpl_pick_observations values(
                        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", pick_rows,
                    )
        return {**surface,
                "players": len(players), "fixtures": len(fixture_rows),
                "history": len(current), "picks": len(pick_rows)}

    def odds_context(self, *, now: datetime) -> tuple[dict | None, dict | None]:
        """Cursor de cuota y primer deadline futuro del último snapshot FPL."""
        with connect(self.config, autocommit=True) as con:
            cursor = con.execute(
                "select * from raw.source_cursors where source_name='market_odds'"
            ).fetchone()
            deadline = con.execute(
                """
                with latest as (
                  select artifact_id from raw.source_artifacts
                  where source_name='fpl_official' order by observed_at desc limit 1
                )
                select event_id,deadline_time from analytics.fpl_event_observations
                where artifact_id=(select artifact_id from latest) and deadline_time>%s
                order by deadline_time limit 1
                """, (now,),
            ).fetchone()
        return cursor, deadline

    def load_odds(self, artifact_id: str, season: str, observed_at: str,
                  rows: list[dict]) -> dict:
        def i(row, key): return _number(row.get(key), int)
        def f(row, key): return _number(row.get(key))
        values = []
        for row in rows:
            key = "|".join((season, row.get("Date", ""), row.get("Time", ""),
                            row.get("HomeTeam", ""), row.get("AwayTeam", "")))
            values.append((
                artifact_id, season, observed_at, key, row.get("Date") or None,
                row.get("Time") or None, row.get("HomeTeam") or "",
                row.get("AwayTeam") or "", i(row, "FTHG"), i(row, "FTAG"),
                row.get("FTR") or None, f(row, "B365H"), f(row, "B365D"), f(row, "B365A"),
                f(row, "B365CH"), f(row, "B365CD"), f(row, "B365CA"),
                f(row, "AvgH"), f(row, "AvgD"), f(row, "AvgA"),
                f(row, "AvgCH"), f(row, "AvgCD"), f(row, "AvgCA"), Jsonb(row),
            ))
        with connect(self.config) as con:
            with con.cursor() as cur:
                cur.executemany(
                    """insert into analytics.match_odds_observations values(
                    %s,%s,%s,%s,to_date(%s,'DD/MM/YYYY'),%s::time,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", values,
                )
        return {"matches": len(values)}

    def load_market_odds(self, artifact_id: str, season: str, observed_at: str,
                         rows: list[dict]) -> dict:
        values = [(
            artifact_id, row["observation_key"], "the_odds_api",
            row["provider_event_id"], season, observed_at, row["sport_key"],
            row["commence_time"], row["home_team"], row["away_team"],
            row["bookmaker_key"], row["bookmaker_title"],
            row.get("bookmaker_last_update"), row["market_key"],
            row.get("market_last_update"), row["outcome_name"],
            row.get("outcome_description"), row["price"], row.get("point"), Jsonb(row),
        ) for row in rows]
        with connect(self.config) as con:
            with con.cursor() as cur:
                cur.executemany(
                    """insert into analytics.market_odds_observations values(
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    values,
                )
        return {"events": len({row["provider_event_id"] for row in rows}),
                "market_rows": len(values)}

    def load_schedule(self, artifact_id: str, season: str, observed_at: str,
                      rows: list[dict]) -> dict:
        values = []
        for row in rows:
            game_id = row.get("game_id") or row.get("game")
            values.append((artifact_id, season, observed_at, int(game_id),
                           row.get("date") or row.get("kickoff_time"),
                           row.get("home_team") or row.get("home"),
                           row.get("away_team") or row.get("away"),
                           str(row.get("status")), Jsonb(row)))
        with connect(self.config) as con:
            with con.cursor() as cur:
                cur.executemany(
                    "insert into analytics.whoscored_schedule_observations values("
                    "%s,%s,%s,%s,%s,%s,%s,%s,%s)", values,
                )
        return {"scheduled_matches": len(values)}

    def covered_whoscored_ids(self, season: str) -> set[int]:
        with connect(self.config, autocommit=True) as con:
            rows = con.execute(
                "select ws_match_id from analytics.whoscored_matches where season=%s", (season,)
            ).fetchall()
        return {int(row["ws_match_id"]) for row in rows}

    def load_whoscored_match(self, artifact_id: str, season: str, observed_at: str,
                             payload_sha256: str, data: dict, quality: dict) -> dict:
        mcd = data.get("matchCentreData", data)
        match_id = int(data.get("matchId") or mcd.get("matchId"))
        home, away = mcd["home"], mcd["away"]
        home_score = (home.get("scores") or {}).get("fulltime")
        away_score = (away.get("scores") or {}).get("fulltime")
        events = mcd["events"]
        values = []
        for item in events:
            values.append((
                match_id, int(item["id"]), int(item.get("eventId") or 0),
                int(item.get("minute") or 0), item.get("second"), item.get("expandedMinute"),
                (item.get("period") or {}).get("displayName"),
                (item.get("type") or {}).get("displayName"),
                (item.get("outcomeType") or {}).get("displayName"),
                item.get("teamId"), item.get("playerId"), item.get("x"), item.get("y"),
                item.get("endX"), item.get("endY"), bool(item.get("isTouch")),
                bool(item.get("isShot")), bool(item.get("isGoal")), item.get("relatedEventId"),
                item.get("relatedPlayerId"), Jsonb(item.get("qualifiers") or []), Jsonb(item),
            ))
        kickoff = mcd.get("startTime") or mcd.get("startDate")
        with connect(self.config) as con:
            con.execute(
                """
                insert into analytics.whoscored_matches(ws_match_id,season,kickoff_time,
                  home_team,away_team,status_code,home_score,away_score,event_count,typed_events,
                  located_events,artifact_id,payload_sha256,collected_at)
                values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                on conflict(ws_match_id) do update set event_count=excluded.event_count,
                  typed_events=excluded.typed_events,located_events=excluded.located_events,
                  artifact_id=excluded.artifact_id,payload_sha256=excluded.payload_sha256,
                  collected_at=excluded.collected_at
                """,
                (match_id, season, kickoff, home["name"], away["name"], int(mcd["statusCode"]),
                 home_score, away_score, len(events), quality["typed_events"],
                 quality["located_events"], artifact_id, payload_sha256, observed_at),
            )
            with con.cursor() as cur:
                cur.executemany(
                    """insert into analytics.whoscored_events values(
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    on conflict(ws_match_id,ws_event_id,event_id) do nothing""", values,
                )
        return {"matches": 1, "events": len(values)}

    def status(self) -> dict:
        expected = {
            "fpl_official": self.config.collector_fpl_cadence_seconds,
            "market_odds": self.config.collector_odds_cadence_seconds,
            "whoscored_schedule": self.config.collector_schedule_cadence_seconds,
            "whoscored_events": self.config.collector_events_cadence_seconds,
        }
        with connect(self.config, autocommit=True) as con:
            sources = con.execute(
                "select * from ops.v_data_source_health order by source_name"
            ).fetchall()
            counts = con.execute(
                """select
                (select count(*) from analytics.fpl_team_observations) as fpl_teams,
                (select count(*) from analytics.fpl_event_observations) as fpl_gameweeks,
                (select count(*) from analytics.fpl_player_observations) as fpl_players,
                (select count(*) from analytics.fpl_fixture_observations) as fpl_fixtures,
                (select count(*) from analytics.match_odds_observations) as legacy_odds_matches,
                (select count(distinct provider_event_id)
                   from analytics.market_odds_observations) as odds_events,
                (select count(*) from analytics.market_odds_observations) as odds_market_rows,
                (select count(*) from analytics.whoscored_matches) as event_matches,
                (select count(*) from analytics.whoscored_events) as events"""
            ).fetchone()
            latest_runs = con.execute(
                """select distinct on(source_name) source_name,status,started_at,finished_at,
                error_code,error_detail,metrics,quality from raw.ingestion_runs
                where source_name = any(%s)
                order by source_name,started_at desc""", (list(expected),)
            ).fetchall()
        observed = {row["source_name"] for row in sources}
        sources = list(sources) + [
            {"source_name": name, "last_status": "never", "last_attempt_at": None,
             "last_success_at": None, "age_seconds": None, "cadence_seconds": cadence,
             "consecutive_failures": 0, "health": "missing", "detail": {}}
            for name, cadence in expected.items() if name not in observed
        ]
        sources.sort(key=lambda row: row["source_name"])
        health = "healthy"
        if any(row["health"] != "healthy" for row in sources):
            health = "degraded"
        return {"schema": "mova-data-service-status-v1", "status": health,
                "sources": sources, "counts": counts, "latest_runs": latest_runs}

    def coverage(self) -> dict:
        """Prueba cerrada sobre el último snapshot de cada fuente y su cruce."""
        with connect(self.config, autocommit=True) as con:
            row = con.execute(
                """
                with latest_fpl as (
                  select artifact_id from raw.source_artifacts where source_name='fpl_official'
                  order by observed_at desc limit 1
                ), latest_schedule as (
                  select artifact_id from raw.source_artifacts
                  where source_name='whoscored_schedule' order by observed_at desc limit 1
                ), latest_odds as (
                  select artifact_id from raw.source_artifacts where source_name='market_odds'
                  order by observed_at desc limit 1
                ), completed as (
                  select ws_match_id from analytics.whoscored_schedule_observations
                  where artifact_id=(select artifact_id from latest_schedule) and status='6'
                )
                select
                  (select count(*) from analytics.fpl_team_observations
                   where artifact_id=(select artifact_id from latest_fpl)) as fpl_teams,
                  (select count(*) from analytics.fpl_event_observations
                   where artifact_id=(select artifact_id from latest_fpl)) as fpl_gameweeks,
                  (select count(*) from analytics.fpl_player_observations
                   where artifact_id=(select artifact_id from latest_fpl)) as fpl_players,
                  (select count(*) from analytics.fpl_fixture_observations
                   where artifact_id=(select artifact_id from latest_fpl)) as fpl_fixtures,
                  (select count(*) from analytics.whoscored_schedule_observations
                   where artifact_id=(select artifact_id from latest_schedule)) as schedule_matches,
                  (select count(*) from completed) as completed_matches,
                  (select count(*) from completed c left join analytics.whoscored_matches m
                   on m.ws_match_id=c.ws_match_id where m.ws_match_id is null) as missing_events,
                  (select count(*) from analytics.whoscored_matches
                   where season=%s and event_count not between 1000 and 2500) as invalid_event_matches,
                  (select count(distinct provider_event_id)
                   from analytics.market_odds_observations
                   where artifact_id=(select artifact_id from latest_odds)) as odds_events,
                  (select count(distinct provider_event_id)
                   from analytics.market_odds_observations
                   where artifact_id=(select artifact_id from latest_odds)
                     and market_key='h2h') as odds_h2h_events,
                  (select count(distinct provider_event_id)
                   from analytics.market_odds_observations
                   where artifact_id=(select artifact_id from latest_odds)
                     and market_key='totals') as odds_totals_events,
                  (select count(distinct bookmaker_key)
                   from analytics.market_odds_observations
                   where artifact_id=(select artifact_id from latest_odds)) as odds_bookmakers,
                  (select count(*) from raw.quality_checks q join raw.ingestion_runs r
                   on r.run_id=q.run_id where not q.passed and r.started_at > now()-interval '7 days')
                    as failed_quality_checks
                """, (self.config.season,),
            ).fetchone()
        specs = [
            ("fpl_teams", row["fpl_teams"] == 20, 20),
            ("fpl_gameweeks", row["fpl_gameweeks"] == 38, 38),
            ("fpl_players", 500 <= row["fpl_players"] <= 800, "500..800"),
            ("fpl_fixtures", row["fpl_fixtures"] == 380, 380),
            ("whoscored_schedule", row["schedule_matches"] == 380, 380),
            ("completed_event_coverage", row["missing_events"] == 0, 0),
            ("event_volume_contract", row["invalid_event_matches"] == 0, 0),
            ("odds_present", row["odds_events"] > 0, ">0"),
            ("odds_h2h_coverage", row["odds_h2h_events"] == row["odds_events"],
             row["odds_events"]),
            ("odds_totals_coverage", row["odds_totals_events"] == row["odds_events"],
             row["odds_events"]),
            ("odds_bookmakers", row["odds_bookmakers"] >= 5, ">=5"),
            ("quality_checks", row["failed_quality_checks"] == 0, 0),
        ]
        observed_keys = {
            "whoscored_schedule": "schedule_matches",
            "completed_event_coverage": "missing_events",
            "event_volume_contract": "invalid_event_matches",
            "odds_present": "odds_events",
            "odds_h2h_coverage": "odds_h2h_events",
            "odds_totals_coverage": "odds_totals_events",
            "quality_checks": "failed_quality_checks",
        }
        checks = [{"name": name, "passed": passed, "expected": expected,
                   "observed": row.get(observed_keys.get(name, name))}
                  for name, passed, expected in specs]
        return {
            "schema": "mova-data-service-coverage-v1",
            "status": "complete" if all(item["passed"] for item in checks) else "incomplete",
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "summary": dict(row), "checks": checks,
        }

    def prometheus(self) -> str:
        return prometheus(self.status())


def publish_status(config, state: dict) -> None:
    write_atomic(config.collector_root / "status.json", canonical_bytes(state))


def publish_coverage(config, state: dict) -> None:
    write_atomic(config.collector_root / "coverage.json", canonical_bytes(state))


def read_status(config) -> dict:
    path = config.collector_root / "status.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "mova-data-service-status-v1":
        raise ValueError("snapshot de estado del data service inválido")
    return payload


def read_coverage(config) -> dict:
    path = config.collector_root / "coverage.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "mova-data-service-coverage-v1":
        raise ValueError("snapshot de cobertura del data service inválido")
    return payload


def prometheus(state: dict) -> str:
    lines = [
        "# HELP mova_data_source_health Source health (1 healthy, 0 unhealthy).",
        "# TYPE mova_data_source_health gauge",
        "# HELP mova_data_source_age_seconds Seconds since last successful collection.",
        "# TYPE mova_data_source_age_seconds gauge",
        "# HELP mova_data_source_consecutive_failures Consecutive failed runs.",
        "# TYPE mova_data_source_consecutive_failures gauge",
        "mova_data_service_up 1",
    ]
    for row in state["sources"]:
        name = str(row["source_name"]).replace('"', '\\"')
        lines.append(f'mova_data_source_health{{source="{name}"}} '
                     f'{1 if row["health"] == "healthy" else 0}')
        lines.append(f'mova_data_source_age_seconds{{source="{name}"}} '
                     f'{int(row["age_seconds"] or 0)}')
        lines.append(f'mova_data_source_consecutive_failures{{source="{name}"}} '
                     f'{int(row["consecutive_failures"] or 0)}')
        if row["source_name"] == "market_odds":
            quota = ((row.get("detail") or {}).get("quality") or {}).get("quota") or {}
            if quota.get("remaining") is not None:
                lines.append(f'mova_data_odds_quota_remaining {int(quota["remaining"])}')
            if quota.get("used") is not None:
                lines.append(f'mova_data_odds_quota_used {int(quota["used"])}')
    for key, value in state["counts"].items():
        metric = str(key).replace("-", "_")
        lines.append(f"mova_data_rows{{dataset=\"{metric}\"}} {int(value or 0)}")
    return "\n".join(lines) + "\n"
