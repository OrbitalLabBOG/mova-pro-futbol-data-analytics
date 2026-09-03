"""Proyectores de xp que puede usar el simulador.

`naive`   — placeholder de WP-003: prior de precio y media exponencial.
`minutes` — WP-004: separa CUANTO rinde el jugador cuando juega de CUANTO
            probable es que juegue, y estima lo segundo con el modelo calibrado.
`points`  — WP-005: xP como suma de componentes con distribucion propia
            (goles, asistencias, porteria a cero, contribucion defensiva, bonus,
            tarjetas, paradas), cada uno auditable y con su varianza.

La separacion importa porque son fenomenos distintos: la forma se estima del
historial de puntos, la titularidad de la rotacion. Mezclarlas en una sola media
es lo que hacia el stub.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from mova_fpl.engine.naive import PTS_POR_MILLON, naive_projection, price_prior

#: partidos jugados para que el rendimiento observado pese la mitad frente al prior
SHRINK_APARICIONES = 4.0
#: cuanto rinde un jugador que entra pero no completa 60 minutos, en proporcion
PESO_PARCIAL = 0.45


@dataclass(frozen=True)
class FixtureHorizonProjection:
    """Resultado auditable de una proyección fixture-a-fixture.

    ``horizon_xp`` y ``horizon_sd`` tienen la forma que consume ``State``. El
    detalle de la jornada actual sirve para inspección y pruebas, pero no toma
    ninguna decisión por sí mismo.
    """

    horizon_xp: dict[int, dict[int, float]]
    horizon_sd: dict[int, dict[int, float]]
    current_detail: pd.DataFrame = field(default_factory=pd.DataFrame)
    horizon_detail: dict[int, pd.DataFrame] = field(default_factory=dict)


def _tasa_por_aparicion(history: pd.DataFrame, roster: pd.DataFrame) -> pd.Series:
    """Puntos esperados EN LOS PARTIDOS QUE JUEGA, encogidos hacia el prior de precio."""
    precio = roster["value"].astype(float) / 10.0
    # el prior de precio son puntos por partido incluyendo ausencias; se reescala
    # a puntos por aparicion dividiendo por una tasa de titularidad tipica
    prior = (price_prior(precio) / 0.55).clip(lower=1.0)

    if history.empty:
        return prior.reset_index(drop=True)

    jugados = history[history["minutes"] > 0]
    if jugados.empty:
        return prior.reset_index(drop=True)

    media = jugados.groupby("element")["total_points"].mean()
    n = jugados.groupby("element")["total_points"].size()

    obs = roster["element"].map(media)
    cuenta = roster["element"].map(n).fillna(0.0)
    peso = (cuenta / (cuenta + SHRINK_APARICIONES)).clip(0.0, 1.0)
    return (peso * obs.fillna(prior) + (1 - peso) * prior).astype(float).reset_index(drop=True)


def minutes_projection(history: pd.DataFrame, roster: pd.DataFrame, model) -> pd.Series:
    """xp = rendimiento por aparicion x probabilidad de aparecer.

    `history` viene de as_of: no contiene la jornada objetivo. El modelo de
    minutos se entreno con temporadas anteriores al holdout, asi que tampoco.
    """
    tasa = _tasa_por_aparicion(history, roster)
    proba = _proba_minutos(history, roster, model)
    disponibilidad = proba[:, 2] + PESO_PARCIAL * proba[:, 1]
    return pd.Series(tasa.to_numpy() * disponibilidad, dtype=float)


def _proba_minutos(history: pd.DataFrame, roster: pd.DataFrame, model) -> np.ndarray:
    """Las tres probabilidades de minutos para las filas del catalogo.

    Se factoriza aparte porque la usan el proyector de minutos y el de puntos, y
    construir las features es lo caro del ciclo: una sola vez por jornada.
    """
    from mova_fpl.models.features.minutes_features import build_targets
    target = build_targets(history, roster)
    p = pd.DataFrame(model.predict_proba_built(target), columns=["p0", "p1", "p60"])
    p["element"] = target["element"].to_numpy()
    tgt = p.set_index("element").reindex(roster["element"])[["p0", "p1", "p60"]]
    # un jugador sin fila proyectable se trata como que no juega, no como 50/50:
    # inventar disponibilidad es peor que asumir ausencia
    return tgt.fillna({"p0": 1.0, "p1": 0.0, "p60": 0.0}).to_numpy(dtype=float)


def points_projection(history: pd.DataFrame, roster: pd.DataFrame, modelos: dict,
                      season: str, con_desglose: bool = False, equipos: dict | None = None,
                      disponibilidad=None):
    """xP por componentes (WP-005). Devuelve la serie de xp, o (serie, desglose).

    `modelos` trae el de minutos y el de puntos. El primero decide si juega, el
    segundo cuanto rinde si juega. Separarlos es toda la tesis de ADR-003.
    """
    from mova_fpl.rules import get as get_rules

    proba = _proba_minutos(history, roster, modelos["minutes"])
    if disponibilidad is not None:
        from mova_fpl.data.live import aplicar_disponibilidad
        proba = aplicar_disponibilidad(proba, disponibilidad)
    scoring = get_rules(season).SCORING
    desglose = modelos["points"].project(history, roster, proba, scoring,
                                         scoring.defcon_thresholds, equipos=equipos)
    xp = pd.Series(desglose["xp"].to_numpy(dtype=float), dtype=float)
    return (xp, desglose) if con_desglose else xp


def fixture_horizon_projection(*, history: pd.DataFrame, roster: pd.DataFrame,
                               modelos: dict, season: str, gw: int, horizon: int,
                               schedule: pd.DataFrame, decay: float = 0.84,
                               disponibilidad=None) -> FixtureHorizonProjection:
    """Proyecta cada rival futuro con un único information set predeadline.

    Del futuro solo acepta calendario: equipo, rival, localía y fixture. La
    identidad, precio, forma y probabilidad de minutos del jugador se congelan
    en ``roster``/``history`` al momento de la decisión. Esto hace que el
    horizonte sea rodante: se ejecuta únicamente la primera acción y todo se
    vuelve a estimar en el siguiente deadline.

    En doble jornada se suman medias y varianzas condicionales. La independencia
    de varianzas es una aproximación explícita hasta contar con suficientes DGW
    para estimar la correlación compartida de disponibilidad.
    """
    from mova_fpl.data.live import aplicar_disponibilidad
    from mova_fpl.rules import get as get_rules

    if horizon < 1:
        raise ValueError(f"horizonte debe ser >= 1, recibido {horizon}")
    if not 0 < decay <= 1:
        raise ValueError(f"decay debe estar en (0, 1], recibido {decay}")
    if not isinstance(modelos, dict) or not {"minutes", "points"} <= set(modelos):
        raise ValueError("fixture_horizon_projection requiere bundle minutes+points")
    required = {"gw", "fixture", "team", "opponent_team", "was_home"}
    missing = required - set(schedule.columns)
    if missing:
        raise ValueError(f"calendario fixture-a-fixture incompleto: {sorted(missing)}")

    current = roster.drop_duplicates("element", keep="first").copy()
    current["team"] = current["team"].astype(str)
    ids = current["element"].astype(int).tolist()
    until = int(gw) + int(horizon) - 1
    visible = schedule[
        (pd.to_numeric(schedule["gw"], errors="coerce") >= int(gw))
        & (pd.to_numeric(schedule["gw"], errors="coerce") <= until)
    ].copy()

    probability = _proba_minutos(history, current, modelos["minutes"])
    if disponibilidad is not None:
        probability = aplicar_disponibilidad(probability, disponibilidad)
    by_probability = {
        int(element): values
        for element, values in zip(current["element"], probability)
    }
    prepared = modelos["points"].prepare_history(history)
    scoring = get_rules(season).SCORING
    horizon_xp: dict[int, dict[int, float]] = {}
    horizon_sd: dict[int, dict[int, float]] = {}
    current_detail = pd.DataFrame()
    horizon_detail: dict[int, pd.DataFrame] = {}

    for target_gw in range(int(gw), until + 1):
        expected: defaultdict[int, float] = defaultdict(float)
        variance: defaultdict[int, float] = defaultdict(float)
        games: defaultdict[int, int] = defaultdict(int)
        gw_schedule = visible[visible["gw"].astype(int) == target_gw]
        rows: list[pd.DataFrame] = []

        for fixture, pair in gw_schedule.groupby("fixture", sort=True):
            # Se requieren ambos lados para traducir el id anual del rival al
            # nombre estable usado por el modelo de fuerza de equipo.
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
                players["kickoff_time"] = getattr(match, "kickoff_time", None)
                rows.append(players)

        if rows:
            fixture_roster = pd.concat(rows, ignore_index=True)
            minute_proba = np.vstack([
                by_probability[int(element)] for element in fixture_roster["element"]
            ])
            detail = modelos["points"].project(
                history, fixture_roster, minute_proba, scoring,
                scoring.defcon_thresholds,
                equipos=_opponent_names(gw_schedule), prepared=prepared,
            )
            for element, mu, sd in zip(
                    fixture_roster["element"], detail["xp"], detail["xp_sd"]):
                key = int(element)
                expected[key] += float(mu)
                variance[key] += float(sd) ** 2
                games[key] += 1

        discount = float(decay) ** (target_gw - int(gw))
        horizon_xp[target_gw] = {element: expected[element] * discount for element in ids}
        horizon_sd[target_gw] = {
            element: float(np.sqrt(variance[element])) * discount for element in ids
        }

        detail = current[
            ["element", "player_key", "name", "position", "team"]
        ].copy()
        detail["xp"] = detail["element"].map(expected).fillna(0.0)
        detail["xp_sd"] = detail["element"].map(
                lambda element: float(np.sqrt(variance[int(element)]))
            ).fillna(0.0)
        detail["n_fixtures"] = detail["element"].map(games).fillna(0).astype(int)
        horizon_detail[target_gw] = detail
        if target_gw == int(gw):
            current_detail = detail

    return FixtureHorizonProjection(
        horizon_xp=horizon_xp,
        horizon_sd=horizon_sd,
        current_detail=current_detail,
        horizon_detail=horizon_detail,
    )


def _opponent_names(schedule: pd.DataFrame) -> dict[int, str]:
    """Id anual de rival -> nombre de club, derivado de ambos lados del fixture."""
    output: dict[int, str] = {}
    for _, pair in schedule.groupby("fixture", sort=False):
        rows = list(pair.itertuples(index=False))
        for row in rows:
            other = next(
                (candidate for candidate in rows if str(candidate.team) != str(row.team)),
                None,
            )
            if other is None or pd.isna(row.opponent_team):
                continue
            output[int(row.opponent_team)] = str(other.team)
    return output


PROJECTORS = {"naive": "naive", "minutes": "minutes", "points": "points"}
