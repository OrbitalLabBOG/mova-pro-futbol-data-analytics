"""Proyección causal jugador × fixture × jornada para el horizonte rodante."""
from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

from mova_fpl.engine.projection import _proba_minutos
from mova_fpl.rules import get as get_rules
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
        schedule = store.team_fixtures(season, gw, until)
        horizon_xp: dict[int, dict[int, float]] = {}
        horizon_sd: dict[int, dict[int, float]] = {}

        current = roster.drop_duplicates("element", keep="first").copy()
        current["team"] = current["team"].astype(str)
        ids = current["element"].astype(int).tolist()
        # Un único information set por decisión: no hay nuevas alineaciones ni
        # minutos observados entre GW hipotéticas. La incertidumbre de jugar se
        # mantiene y el contexto de rival sí cambia fixture a fixture.
        current_proba = _proba_minutos(history, current, models["minutes"])
        probability = {int(element): values for element, values in zip(
            current["element"], current_proba)}
        prepared = models["points"].prepare_history(history)

        for target_gw in range(int(gw), until + 1):
            expected = defaultdict(float)
            variance = defaultdict(float)
            games = defaultdict(int)
            gw_schedule = schedule[schedule["gw"] == target_gw]
            rows = []
            for fixture, pair in gw_schedule.groupby("fixture", sort=True):
                if len(pair) < 2:
                    continue
                for match in pair.itertuples(index=False):
                    players = current[current["team"] == str(match.team)].copy()
                    if players.empty:
                        continue
                    players["season"] = season
                    players["gw"] = target_gw
                    players["fixture"] = int(fixture)
                    players["opponent_team"] = match.opponent_team
                    players["was_home"] = match.was_home
                    players["kickoff_time"] = match.kickoff_time
                    rows.append(players)

            if rows:
                fixture_roster = pd.concat(rows, ignore_index=True)
                minute_proba = np.vstack([
                    probability[int(element)] for element in fixture_roster["element"]
                ])
                opponent_names = self._opponent_names(gw_schedule)
                scoring = get_rules(season).SCORING
                detail = models["points"].project(
                    history, fixture_roster, minute_proba, scoring,
                    scoring.defcon_thresholds, equipos=opponent_names,
                    prepared=prepared,
                )
                for element, mu, sd in zip(
                        fixture_roster["element"], detail["xp"], detail["xp_sd"]):
                    key = int(element)
                    expected[key] += float(mu)
                    # Independencia condicional entre partidos. Conservamos la
                    # aproximación declarada para DGW hasta tener correlaciones
                    # de disponibilidad estimables en suficientes temporadas.
                    variance[key] += float(sd) ** 2
                    games[key] += 1

            discount = float(config.decay) ** (target_gw - int(gw))
            horizon_xp[target_gw] = {e: expected[e] * discount for e in ids}
            horizon_sd[target_gw] = {e: float(np.sqrt(variance[e])) * discount for e in ids}

            if target_gw == int(gw):
                snapshot = current[["element", "player_key", "name", "position", "team"]].copy()
                snapshot["xp"] = snapshot["element"].map(expected).fillna(0.0)
                snapshot["xp_sd"] = snapshot["element"].map(
                    lambda e: float(np.sqrt(variance[int(e)]))).fillna(0.0)
                snapshot["n_fixtures"] = snapshot["element"].map(games).fillna(0).astype(int)
                self.snapshots[(season, int(gw))] = snapshot

        current_xp = current["element"].map(horizon_xp.get(int(gw), {})).fillna(0.0)
        return ProjectionBundle(
            xp=pd.Series(current_xp.to_numpy(dtype=float), dtype=float),
            horizon_xp=horizon_xp,
            horizon_sd=horizon_sd,
        )

    @staticmethod
    def _opponent_names(schedule: pd.DataFrame) -> dict[int, str]:
        """Traduce el id anual de rival al nombre que usa ``team_strength``."""
        output: dict[int, str] = {}
        for _, pair in schedule.groupby("fixture", sort=False):
            rows = list(pair.itertuples(index=False))
            for row in rows:
                other = next((candidate for candidate in rows
                              if str(candidate.team) != str(row.team)), None)
                if other is None or pd.isna(row.opponent_team):
                    continue
                output[int(row.opponent_team)] = str(other.team)
        return output
