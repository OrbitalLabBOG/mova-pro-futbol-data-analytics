"""Proyector placeholder del walking skeleton (WP-003).

Deliberadamente simple: precio como prior y media exponencial del historial,
encogida hacia el prior segun cuantos partidos se hayan visto. Sin modelo de
minutos, sin rival, sin posicion en el campo, sin DefCon. Lo reemplazan
models/minutes.py (WP-004) y models/points.py (WP-005).

El numero que produzca es un PISO contra el cual medir esos modelos, no un logro.

Por que el precio: es informacion conocida antes del cierre y el mercado la fija
sabiendo quien juega. En la GW1 de 2025-26 correlaciona 0,32 con los puntos
reales. Un prior plano por posicion deja el xp casi constante y hace que el
desempate del optimizador arme el equipo de los quince jugadores mas baratos
del juego, que no juegan. Se verifico en la primera corrida del harness.
"""
from __future__ import annotations

import pandas as pd

#: puntos esperados por millon. Calibrado grueso: 4.0M -> ~1.8, 14M -> ~6.3
PTS_POR_MILLON = 0.45
#: partidos observados para que el historial pese la mitad frente al prior
SHRINKAGE_K = 3.0


def price_prior(price: pd.Series) -> pd.Series:
    return (price.astype(float) * PTS_POR_MILLON).clip(lower=0.5)


def naive_projection(history: pd.DataFrame, roster: pd.DataFrame,
                     half_life: float = 6.0) -> pd.Series:
    """Puntos esperados por elemento.

    `history` viene de as_of(): jamas incluye la jornada objetivo. En la GW1
    esta vacio y el resultado es exclusivamente el prior de precio.
    """
    price = roster["value"].astype(float) / 10.0
    prior = price_prior(price)

    if history.empty:
        return prior.reset_index(drop=True)

    h = history.sort_values("gw")
    alpha = 1 - 0.5 ** (1 / max(half_life, 1e-6))
    medias = h.groupby("element")["total_points"].apply(lambda s: s.ewm(alpha=alpha).mean().iloc[-1])
    tasa = h.groupby("element")["minutes"].apply(lambda s: (s > 0).mean())
    vistos = h.groupby("element")["gw"].nunique()

    obs = roster["element"].map(medias)
    apar = roster["element"].map(tasa).fillna(0.0)
    n = roster["element"].map(vistos).fillna(0.0)

    senal = (obs * apar.clip(0.0, 1.0)).fillna(prior)
    peso = (n / (n + SHRINKAGE_K)).clip(0.0, 1.0)          # sin partidos -> puro prior
    return (peso * senal + (1 - peso) * prior).astype(float).reset_index(drop=True)
