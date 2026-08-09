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

import numpy as np
import pandas as pd

from mova_fpl.engine.naive import PTS_POR_MILLON, naive_projection, price_prior

#: partidos jugados para que el rendimiento observado pese la mitad frente al prior
SHRINK_APARICIONES = 4.0
#: cuanto rinde un jugador que entra pero no completa 60 minutos, en proporcion
PESO_PARCIAL = 0.45


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
    objetivo = roster.copy()
    for c in ("minutes", "starts", "total_points"):
        objetivo[c] = np.nan

    cols = ["player_key", "season", "gw", "fixture", "minutes", "starts",
            "value", "position", "was_home", "element", "total_points"]
    hist = history.reindex(columns=cols) if not history.empty else pd.DataFrame(columns=cols)
    marco = pd.concat([hist, objetivo.reindex(columns=cols)], ignore_index=True)
    marco["_objetivo"] = [False] * len(hist) + [True] * len(objetivo)

    from mova_fpl.models.features.minutes_features import build
    d = build(marco)
    p = pd.DataFrame(model.predict_proba_built(d), columns=["p0", "p1", "p60"])
    p["_objetivo"] = d["_objetivo"].to_numpy()
    p["element"] = d["element"].to_numpy()
    tgt = (p[p["_objetivo"]].set_index("element").reindex(roster["element"])
           [["p0", "p1", "p60"]])
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


PROJECTORS = {"naive": "naive", "minutes": "minutes", "points": "points"}
