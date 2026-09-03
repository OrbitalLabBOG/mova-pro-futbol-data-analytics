"""Adaptador del simulador al proyector causal compartido con el runtime vivo."""
from __future__ import annotations

import pandas as pd

from mova_fpl.engine.projection import fixture_horizon_projection
from mova_fpl.engine.simulator import ProjectionBundle


class FixtureProjector:
    """Adaptador de research para proyectar cada rival futuro por separado.

    Solo usa la plantilla y los precios visibles en la jornada actual. Del
    futuro lee exclusivamente calendario (club, rival, localía y fixture), no
    jugadores, rendimiento ni precios. Ejecutar una jornada vuelve a estimar
    todo y solo se aplica el primer paso de la política.
    """

    def __init__(self):
        self.snapshots: dict[tuple[str, int], pd.DataFrame] = {}

    def __call__(self, *, history, roster, models, season, gw, store, config,
                 max_gw, alias) -> ProjectionBundle:
        if alias:
            raise ValueError("FixtureProjector requiere mode='named' para preservar contexto de club")
        if not isinstance(models, dict) or not {"minutes", "points"} <= set(models):
            raise ValueError("FixtureProjector requiere bundle minutes+points")

        until = min(int(max_gw), int(gw) + int(config.horizon) - 1)
        current = roster.drop_duplicates("element", keep="first").copy()
        projection = fixture_horizon_projection(
            history=history,
            roster=current,
            modelos=models,
            season=season,
            gw=gw,
            horizon=until - int(gw) + 1,
            schedule=store.team_fixtures(season, gw, until),
            decay=config.decay,
        )
        self.snapshots[(season, int(gw))] = projection.current_detail
        current_xp = current["element"].map(
            projection.horizon_xp.get(int(gw), {})
        ).fillna(0.0)
        return ProjectionBundle(
            xp=pd.Series(current_xp.to_numpy(dtype=float), dtype=float),
            horizon_xp=projection.horizon_xp,
            horizon_sd=projection.horizon_sd,
        )
