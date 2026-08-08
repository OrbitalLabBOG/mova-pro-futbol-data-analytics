"""Componente de bonus. Mapeo monotono desde BPS por 90 (ADR-003).

El bonus no es del jugador: es un RANKING dentro del partido. Los tres mejores
BPS de los veintidos se llevan 3, 2 y 1. Modelarlo bien exigiria proyectar el BPS
de los otros veintiuno, que no cabe en v1.

Lo que si es defendible: el BPS por 90 de un jugador predice cuantas veces entra
en ese podio. Se estima la relacion empirica —por deciles de BPS/90, la media de
bonus por 90 observada— y se interpola. Es monotona por construccion y explicable.

Sesgo declarado (R-04): la relacion se ajusta con temporadas bajo el BPS vigente
hasta 2025/26. Para 2026/27 el BPS cambia en cuatro puntos (CBI pasa a 1 por cada
3, desaparece `save_out_box`, +1 por parada de ocasion clara, penalti parado
8 -> 7). El componente queda SOBREESTIMADO para defensas y porteros. Por eso se
reporta por separado y no disuelto en el total.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from mova_fpl.models.features.points_features import K_BONUS, shrink

DECILES = 10
#: minutos minimos para que BPS por 90 signifique algo
MINUTOS_MINIMOS = 20
#: noventas acumulados para que el promedio de un jugador-temporada signifique algo
NOVENTAS_MINIMOS = 5.0


@dataclass
class BonusModel:
    """Bonus esperado por 90 minutos, a partir del BPS por 90 del jugador."""
    cortes: list = field(default_factory=list)          # bordes de BPS/90
    valores: list = field(default_factory=list)         # bonus/90 medio por tramo
    prior_global: float = 0.15
    k: float = K_BONUS
    metadata: dict = field(default_factory=dict)

    def fit(self, df: pd.DataFrame) -> "BonusModel":
        if df.empty or not {"bps", "bonus", "minutes"} <= set(df.columns):
            self.metadata = {"filas": 0, "aviso": "sin bps/bonus en el historico"}
            return self

        d = df.copy()
        d["minutos"] = pd.to_numeric(d["minutes"], errors="coerce").fillna(0.0)
        # con menos de 20 minutos, BPS por 90 es una extrapolacion absurda: un
        # jugador con 3 minutos y 2 BPS proyecta 60 BPS/90. Se excluyen del ajuste.
        d = d[d["minutos"] >= MINUTOS_MINIMOS]
        if len(d) < 500:
            self.metadata = {"filas": int(len(d)), "aviso": "muestra insuficiente"}
            return self

        d["n90"] = d["minutos"] / 90.0
        d["bps_"] = pd.to_numeric(d["bps"], errors="coerce")
        d["bonus_"] = pd.to_numeric(d["bonus"], errors="coerce")
        d = d.dropna(subset=["bps_", "bonus_"])

        # El mapa se ajusta sobre PROMEDIOS DE JUGADOR-TEMPORADA, no sobre partidos
        # sueltos, porque asi es como se aplica despues. Ajustarlo por partido y
        # evaluarlo en la media subestima: el bonus se gana en los partidos buenos,
        # la relacion es convexa y por Jensen E[f(X)] > f(E[X]). Medido en la
        # ventana GW20-38 de 2025-26, el sesgo por partido era de -44,8%.
        clave = ["player_key", "season"] if "season" in d.columns else ["player_key"]
        agg = d.groupby(clave).agg(bps=("bps_", "sum"), bonus=("bonus_", "sum"),
                                   n90=("n90", "sum"))
        agg = agg[agg["n90"] >= NOVENTAS_MINIMOS]
        if len(agg) < 200:
            self.metadata = {"filas": int(len(d)), "aviso": "pocos jugadores-temporada"}
            return self
        d = pd.DataFrame({"bps90": agg["bps"] / agg["n90"],
                          "bonus90": agg["bonus"] / agg["n90"]}).reset_index(drop=True)

        # los bordes se recortan a los percentiles 1 y 99: con el minimo y el
        # maximo, el centro del ultimo tramo cae en 1.369 BPS/90 y la
        # interpolacion del tramo alto queda inservible.
        lo, hi = np.quantile(d["bps90"], [0.01, 0.99])
        d["bps90"] = d["bps90"].clip(lo, hi)
        q = np.unique(np.quantile(d["bps90"], np.linspace(0, 1, DECILES + 1)))
        idx = np.clip(np.digitize(d["bps90"], q[1:-1]), 0, len(q) - 2)
        medias = pd.Series(d["bonus90"].to_numpy()).groupby(idx).mean()
        # se fuerza monotonia: mas BPS nunca puede predecir menos bonus
        vals = np.maximum.accumulate(medias.reindex(range(len(q) - 1)).ffill().bfill().to_numpy())

        self.cortes = q.tolist()
        self.valores = vals.tolist()
        self.prior_global = float(d["bonus90"].mean())
        self.metadata = {"filas": int(len(d)), "tramos": len(vals),
                         "bps90_p50": float(np.median(d["bps90"])),
                         "bonus90_medio": self.prior_global}
        return self

    def bonus_por_90(self, bps90) -> np.ndarray:
        """Interpola el bonus esperado. Sin ajuste, devuelve el prior global."""
        b = np.asarray(pd.to_numeric(pd.Series(bps90), errors="coerce"), dtype=float)
        if not self.valores:
            return np.full(len(b), self.prior_global)
        centros = [(self.cortes[i] + self.cortes[i + 1]) / 2 for i in range(len(self.valores))]
        out = np.interp(np.nan_to_num(b, nan=float(np.nanmedian(b)) if np.isfinite(
            np.nanmedian(b)) else 0.0), centros, self.valores)
        return np.clip(out, 0.0, None)

    def project(self, bps90, bonus_observado, n90_historicos, noventas) -> dict:
        """Combina el mapeo desde BPS con el bonus que el jugador de hecho lleva."""
        desde_bps = self.bonus_por_90(bps90)
        obs = np.asarray(pd.to_numeric(pd.Series(bonus_observado), errors="coerce"), dtype=float)
        mezcla = shrink(np.where(np.isfinite(obs), obs, desde_bps),
                        np.where(np.isfinite(obs), n90_historicos, 0.0), desde_bps, self.k)
        return {"bonus_por_90": mezcla, "puntos_bonus": mezcla * np.asarray(noventas, dtype=float)}
