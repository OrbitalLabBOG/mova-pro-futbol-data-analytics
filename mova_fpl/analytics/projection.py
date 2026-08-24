"""Adaptador causal del modelo vivo a filas persistibles por el harness."""

from __future__ import annotations

from mova_fpl.data import live
from mova_fpl.data.store import Store
from mova_fpl.engine.projection import points_projection
from mova_fpl.models.points import COMPONENTES
from mova_fpl.models.registry import git_sha, load
from mova_fpl.analytics.market import MarketDefensePointsModel

HISTORY_SEASON = "2025-26"


def projection_signature(minutes_version: str, points_version: str, *, market: bool) -> dict:
    versions = {"minutes": minutes_version, "points": points_version,
                "projection_contract": "model-analytics-v1"}
    if market:
        versions["market_weight"] = 0.95
    return {"versions": versions, "code_git_sha": git_sha()}


def project_snapshot(*, boot: dict, fixtures: list, season: str, gw: int,
                     minutes_version: str, points_version: str,
                     market_context: list[dict] | None = None) -> dict:
    """Proyecta un snapshot pre-deadline sin leer resultados de la GW objetivo."""
    signature = projection_signature(minutes_version, points_version,
                                     market=market_context is not None)
    versions = signature["versions"]
    roster = live.roster(boot, fixtures, season, gw)
    history = Store().as_of(HISTORY_SEASON, 39)
    models = {"minutes": load("minutes", minutes_version),
              "points": load("points", points_version)}
    if market_context is not None:
        models["points"] = MarketDefensePointsModel(models["points"], market_context)
    _, detail = points_projection(
        history, roster, models, season, con_desglose=True,
        equipos=live.teams(boot), disponibilidad=roster["disponibilidad"].to_numpy(),
    )
    joined = roster.merge(detail, on="element", how="inner", validate="one_to_one")
    schedule = live.team_schedule(fixtures, boot, gw, gw)
    rows = []
    for item in joined.to_dict("records"):
        fixture_count = int(schedule.get((item["team"], gw), 1))
        components = {name: float(item[name]) * fixture_count for name in COMPONENTES}
        rows.append({
            "element": int(item["element"]), "fixture_id": int(item["fixture"]),
            "player_name": str(item["name"]), "position": str(item["position"]),
            "team": str(item["team"]), "opponent_team": int(item["opponent_team"]),
            "xp": float(item["xp"]) * fixture_count,
            "xp_sd": float(item["xp_sd"]) * fixture_count ** .5,
            "p_play": float(1 - (1 - item["p_juega"]) ** fixture_count),
            "p_60": float(1 - (1 - item["p_60"]) ** fixture_count),
            "components": components,
            "context": {"fixture_count": fixture_count,
                        "availability": float(item["disponibilidad"]),
                        "status": item["estado"],
                        "p_clean_sheet_award": float(1 - (1 - item["p_60"] *
                            item["p_porteria_cero"]) ** fixture_count)},
        })
    return {"rows": rows, **signature,
            "history_rows": len(history),
            "history_season": HISTORY_SEASON}
