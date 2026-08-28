"""Persistencia PostgreSQL y snapshots read-only del servicio analítico."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pandas as pd
from psycopg.types.json import Jsonb

from mova_fpl.ops.collector.contracts import canonical_bytes, write_atomic
from mova_fpl.postgres.store import connect
from mova_fpl.analytics.market import build_context


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class AnalyticsStore:
    def __init__(self, config):
        self.config = config

    def latest_fpl_artifact(self) -> dict | None:
        with connect(self.config, autocommit=True) as con:
            return con.execute(
                "select * from raw.source_artifacts where source_name='fpl_official' "
                "order by observed_at desc limit 1"
            ).fetchone()

    def market_context(self, *, fpl_artifact_id: str, season: str, gw: int,
                       as_of: datetime) -> dict:
        """Odds más recientes conocidas al corte, unidas al fixture oficial."""
        with connect(self.config, autocommit=True) as con:
            odds_artifact = con.execute(
                """select artifact_id,observed_at from raw.source_artifacts
                where source_name='market_odds' and season=%s and observed_at<=%s
                order by observed_at desc limit 1""", (season, as_of),
            ).fetchone()
            fixtures = con.execute(
                """select f.fixture_id as fixture,f.kickoff_time,
                  h.name as home_team,a.name as away_team
                from analytics.fpl_fixture_observations f
                join analytics.fpl_team_observations h
                  on h.artifact_id=f.artifact_id and h.team_id=f.team_h
                join analytics.fpl_team_observations a
                  on a.artifact_id=f.artifact_id and a.team_id=f.team_a
                where f.artifact_id=%s and f.event=%s order by f.fixture_id""",
                (fpl_artifact_id, gw),
            ).fetchall()
            rows = [] if not odds_artifact else con.execute(
                """select provider_event_id,commence_time,home_team,away_team,
                  bookmaker_key,market_key,outcome_name,price,point
                from analytics.market_odds_observations where artifact_id=%s""",
                (odds_artifact["artifact_id"],),
            ).fetchall()
        context, quality = build_context(list(fixtures), list(rows))
        return {"artifact_id": odds_artifact["artifact_id"] if odds_artifact else None,
                "observed_at": odds_artifact["observed_at"] if odds_artifact else None,
                "context": context, "quality": quality}

    def save_projection(self, *, idempotency_key: str, season: str, gw: int,
                        variant: str, versions: dict, cutoff_at: str,
                        input_artifact_id: str, manifest: dict, rows: list[dict],
                        status: str, artifact_path: str, artifact_sha256: str) -> tuple[str, bool]:
        with connect(self.config) as con:
            existing = con.execute(
                "select batch_id from analytics.model_projection_batches "
                "where idempotency_key=%s", (idempotency_key,)
            ).fetchone()
            if existing:
                return existing["batch_id"], True
            batch_id = _id("projection")
            con.execute(
                """update analytics.model_projection_batches set status='superseded'
                where season=%s and target_gw=%s and variant=%s and status<>'superseded'""",
                (season, gw, variant),
            )
            con.execute(
                """insert into analytics.model_projection_batches(
                batch_id,idempotency_key,season,target_gw,variant,model_versions,cutoff_at,
                input_artifact_id,input_manifest,player_count,status,artifact_path,artifact_sha256)
                values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (batch_id, idempotency_key, season, gw, variant, Jsonb(versions), cutoff_at,
                 input_artifact_id, Jsonb(manifest), len(rows), status, artifact_path,
                 artifact_sha256),
            )
            values = [(
                batch_id, int(row["element"]), row.get("fixture_id"), row["player_name"],
                row["position"], row["team"], row.get("opponent_team"), float(row["xp"]),
                row.get("xp_sd"), float(row["p_play"]), float(row["p_60"]),
                Jsonb(row["components"]), Jsonb(row.get("context") or {}),
            ) for row in rows]
            with con.cursor() as cur:
                cur.executemany(
                    """insert into analytics.player_projections values(
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", values,
                )
        return batch_id, False

    def projection_by_key(self, idempotency_key: str) -> dict | None:
        with connect(self.config, autocommit=True) as con:
            return con.execute(
                "select batch_id,player_count,variant from analytics.model_projection_batches "
                "where idempotency_key=%s", (idempotency_key,),
            ).fetchone()

    def pending_batches(self, season: str) -> list[dict]:
        with connect(self.config, autocommit=True) as con:
            return con.execute(
                """select b.* from analytics.model_projection_batches b
                where b.season=%s and b.status<>'superseded'
                order by b.target_gw,b.generated_at""", (season,),
            ).fetchall()

    def projection_frame(self, batch_id: str) -> pd.DataFrame:
        with connect(self.config, autocommit=True) as con:
            rows = con.execute(
                "select * from analytics.player_projections where batch_id=%s order by element",
                (batch_id,),
            ).fetchall()
        return pd.DataFrame(rows)

    def research_focus(self, *, squad: list[dict], batch_id: str | None,
                       candidate_limit: int = 10) -> list[dict]:
        """Contexto público mínimo para orientar noticias hacia sujetos relevantes."""
        owned = {int(item["element"]): item for item in squad if item.get("element")}
        with connect(self.config, autocommit=True) as con:
            artifact = con.execute(
                "select artifact_id from raw.source_artifacts "
                "where source_name='fpl_official' order by observed_at desc limit 1"
            ).fetchone()
            if not artifact:
                return []
            projected = []
            if batch_id:
                projected = con.execute(
                    "select element,player_name,team,position,xp,p_play,p_60 "
                    "from analytics.player_projections where batch_id=%s "
                    "order by xp desc limit %s",
                    (batch_id, candidate_limit + len(owned)),
                ).fetchall()
            candidates = [row for row in projected if int(row["element"]) not in owned][
                :candidate_limit
            ]
            projected_by_element = {int(row["element"]): row for row in projected}
            elements = sorted({*owned, *(int(row["element"]) for row in candidates)})
            if not elements:
                return []
            players = con.execute(
                """select p.element,p.web_name,p.team_id,p.element_type,p.status,p.chance_next,
                  p.news,t.name team_name,t.short_name team_short,
                  concat_ws(' ',nullif(p.payload->>'first_name',''),
                    nullif(p.payload->>'second_name','')) full_name
                from analytics.fpl_player_observations p
                join analytics.fpl_team_observations t
                  on t.artifact_id=p.artifact_id and t.team_id=p.team_id
                where p.artifact_id=%s and p.element=any(%s)""",
                (artifact["artifact_id"], elements),
            ).fetchall()
        by_element = {int(row["element"]): row for row in players}
        positions = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
        result = []
        for element in elements:
            player = by_element.get(element)
            if not player:
                continue
            owned_row = owned.get(element)
            projection = projected_by_element.get(element)
            reasons = []
            if owned_row:
                reasons.append("current_squad")
            if any(int(row["element"]) == element for row in candidates):
                reasons.append("top_projection_candidate")
            result.append({
                "element": element,
                "player_name": player.get("full_name") or player["web_name"],
                "web_name": player["web_name"],
                "team": player.get("team_name") or player.get("team_short"),
                "position": positions.get(int(player["element_type"]), "unknown"),
                "focus_reason": reasons,
                "squad_position": int(owned_row["position"]) if owned_row else None,
                "is_captain": bool(owned_row and owned_row.get("is_captain")),
                "is_vice_captain": bool(owned_row and owned_row.get("is_vice_captain")),
                "xp": float(projection["xp"]) if projection else None,
                "p_play": float(projection["p_play"])
                if projection and projection.get("p_play") is not None else None,
                "p_60": float(projection["p_60"])
                if projection and projection.get("p_60") is not None else None,
                "official_status": player.get("status"),
                "official_chance_next": player.get("chance_next"),
                "official_news": player.get("news") or None,
            })
        return sorted(
            result,
            key=lambda item: (
                0 if item["is_captain"] else 1 if "current_squad" in item["focus_reason"] else 2,
                item["squad_position"] or 99,
                -(item["xp"] or 0.0),
            ),
        )

    def actual_frame(self, season: str, gw: int) -> tuple[pd.DataFrame, str | None, bool]:
        with connect(self.config, autocommit=True) as con:
            checked = con.execute(
                """select data_checked from analytics.fpl_event_observations
                where season=%s and event_id=%s order by observed_at desc limit 1""",
                (season, gw),
            ).fetchone()
            artifact = con.execute(
                """select artifact_id from analytics.fpl_event_live_observations
                where season=%s and event=%s order by observed_at desc limit 1""",
                (season, gw),
            ).fetchone()
            if not artifact:
                return pd.DataFrame(), None, bool(checked and checked["data_checked"])
            rows = con.execute(
                """select element,total_points,minutes,stats from
                analytics.fpl_event_live_observations where artifact_id=%s and event=%s
                order by element""", (artifact["artifact_id"], gw),
            ).fetchall()
        return pd.DataFrame(rows), artifact["artifact_id"], bool(checked and checked["data_checked"])

    def reference_metrics(self, batch: dict, *, limit: int) -> list[dict]:
        with connect(self.config, autocommit=True) as con:
            rows = con.execute(
                """select metrics from (
                  select distinct on(e.gw) e.gw,e.metrics,e.evaluated_at
                  from analytics.model_evaluation_runs e
                  join analytics.model_projection_batches b on b.batch_id=e.batch_id
                  where e.season=%s and e.variant=%s and e.gw<%s
                    and e.settlement_status='final' and b.model_versions=%s
                  order by e.gw,e.evaluated_at desc
                ) latest order by gw desc limit %s""",
                (batch["season"], batch["variant"], batch["target_gw"],
                 Jsonb(batch["model_versions"]), max(limit, 20)),
            ).fetchall()
        return [row["metrics"] for row in reversed(rows)]

    def save_evaluation(self, *, idempotency_key: str, batch: dict, settlement: str,
                        metrics: dict, drift: dict, components: list[dict],
                        actual_artifact_id: str) -> tuple[str, bool]:
        with connect(self.config) as con:
            existing = con.execute(
                "select evaluation_id from analytics.model_evaluation_runs "
                "where idempotency_key=%s", (idempotency_key,)
            ).fetchone()
            if existing:
                return existing["evaluation_id"], True
            evaluation_id = _id("evaluation")
            con.execute(
                """insert into analytics.model_evaluation_runs(
                evaluation_id,idempotency_key,batch_id,season,gw,variant,settlement_status,
                sample_size,metrics,drift_status,drift,actual_artifact_id)
                values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (evaluation_id, idempotency_key, batch["batch_id"], batch["season"],
                 batch["target_gw"], batch["variant"], settlement,
                 metrics["sample_size"], Jsonb(metrics), drift["status"], Jsonb(drift),
                 actual_artifact_id),
            )
            values = [(evaluation_id, item["component"], item["predicted_total"],
                       item["actual_total"], item["bias"], item["relative_bias"], item["mae"])
                      for item in components]
            with con.cursor() as cur:
                cur.executemany(
                    "insert into analytics.model_evaluation_components values(%s,%s,%s,%s,%s,%s,%s)",
                    values,
                )
        return evaluation_id, False

    def status(self, *, limit: int = 100) -> dict:
        with connect(self.config, autocommit=True) as con:
            latest = con.execute(
                "select * from analytics.v_model_latest_scorecard order by evaluated_at desc limit %s",
                (limit,),
            ).fetchall()
            batches = con.execute(
                "select batch_id,season,target_gw,variant,model_versions,cutoff_at,generated_at,"
                "player_count,status from analytics.model_projection_batches "
                "order by generated_at desc limit %s", (limit,),
            ).fetchall()
            counts = con.execute(
                """select
                (select count(*) from analytics.model_projection_batches) projections,
                (select count(*) from analytics.model_evaluation_runs) evaluations,
                (select count(*) from analytics.model_evaluation_runs
                  where drift_status='alert') drift_alerts"""
            ).fetchone()
            inventory = con.execute(
                """select
                (select count(distinct event) from analytics.fpl_event_live_observations
                  where season=%s) fpl_live_gameweeks,
                (select count(*) from analytics.fpl_event_live_observations
                  where season=%s) fpl_live_player_rows,
                (select count(distinct provider_event_id)
                  from analytics.market_odds_observations where season=%s) odds_events,
                (select count(*) from analytics.whoscored_matches where season=%s) event_matches,
                (select count(*) from analytics.whoscored_events e join analytics.whoscored_matches m
                  on m.ws_match_id=e.ws_match_id where m.season=%s) whoscored_events""",
                (self.config.season,) * 5,
            ).fetchone()
        current_gw = max((int(row["gw"]) for row in latest
                          if row["season"] == self.config.season), default=None)
        current = [row for row in latest if current_gw is not None
                   and row["season"] == self.config.season and int(row["gw"]) == current_gw]
        overall = "alert" if any(row["drift_status"] == "alert" for row in current) else "healthy"
        return {
            "schema": "mova-analytics-service-status-v1",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "status": overall, "counts": counts, "latest_scorecards": latest,
            "latest_projection_batches": batches,
            "data_inventory": inventory,
            "signals": {
                "fpl_official": {"mode": "active", "use": "projection_and_evaluation"},
                "market_odds": {"mode": "active_shadow_not_promoted",
                                "use": "odds_cs_shadow_scorecard"},
                "whoscored_events": {"mode": "rejected_by_experiment",
                                     "use": "research_only"},
            },
        }


def publish_status(config, state: dict) -> None:
    write_atomic(config.analytics_root / "status.json", canonical_bytes(state))


def read_status(config) -> dict:
    payload = json.loads((config.analytics_root / "status.json").read_text(encoding="utf-8"))
    if payload.get("schema") != "mova-analytics-service-status-v1":
        raise ValueError("snapshot del analytics service inválido")
    return payload


def prometheus(state: dict) -> str:
    scorecards = state.get("latest_scorecards") or []
    head = scorecards[0] if scorecards else {}
    current = [row for row in scorecards if row.get("season") == head.get("season")
               and row.get("gw") == head.get("gw")]
    lines = [f'mova_analytics_service_up {1 if state.get("status") != "unavailable" else 0}']
    for item in current or [head]:
        metrics = item.get("metrics") or {}
        points, minutes, cs = (metrics.get("points") or {}, metrics.get("minutes") or {},
                               metrics.get("clean_sheet") or {})
        labels = (f'season="{item.get("season", "none")}",gw="{item.get("gw", 0)}",'
                  f'variant="{item.get("variant", "none")}"')
        values = {
            "mova_model_sample_size": metrics.get("sample_size"),
            "mova_model_points_mae": points.get("mae"),
            "mova_model_points_rmse": points.get("rmse"),
            "mova_model_points_spearman": points.get("spearman"),
            "mova_model_points_relative_bias": points.get("relative_bias"),
            "mova_model_play_ece": minutes.get("play_ece"),
            "mova_model_p60_ece": minutes.get("p60_ece"),
            "mova_model_clean_sheet_brier": cs.get("brier"),
        }
        lines.append(f'mova_model_drift_alert{{{labels}}} '
                     f'{1 if item.get("drift_status") == "alert" else 0}')
        lines.extend(f'{name}{{{labels}}} {value}' for name, value in values.items()
                     if value is not None)
        for component in metrics.get("components") or []:
            component_label = str(component["component"]).replace('"', '\\"')
            component_labels = f'{labels},component="{component_label}"'
            for suffix in ("predicted_total", "actual_total", "bias", "relative_bias", "mae"):
                value = component.get(suffix)
                if value is not None:
                    lines.append(f'mova_model_component_{suffix}{{{component_labels}}} {value}')
    return "\n".join(lines) + "\n"
