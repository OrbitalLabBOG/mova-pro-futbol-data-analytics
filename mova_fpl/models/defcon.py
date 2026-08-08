"""Contribucion defensiva: P(conteo >= umbral). Binomial negativa (ADR-003).

Aqui esta la ventaja competitiva que persigue el proyecto (I-05): la regla es de
2025/26, el mercado todavia no la tiene incorporada en el precio, y son dos
puntos por jugador y jornada que un modelo de puntos monolitico no ve.

Por que binomial negativa y no Poisson: los conteos defensivos estan
SOBREDISPERSOS. Un central hace 4 despejes un dia y 14 el siguiente segun cuanto
ataque el rival, y esa varianza extra viene del partido, no del jugador. Con
Poisson, P(>= 10) queda sistematicamente mal en las dos colas.

Umbrales (temporada 2025/26 y 2026/27, sin cambios):
    DEF        >= 10 CBIT   (despejes, bloqueos, intercepciones, entradas)
    MID / FWD  >= 12 CBIRT  (lo anterior mas recuperaciones)
    GKP        no elegible

La columna `defensive_contribution` del almacen YA viene con el conteo correcto
por posicion — verificado: coincide con CBIT en el 100% de los DEF y con CBIRT
en el 100% de MID y FWD.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.stats import nbinom

from mova_fpl.models.features.points_features import normaliza_posicion
from mova_fpl.rules.base import Position

#: dispersion de arranque cuando no hay datos para estimarla. Valor alto = casi Poisson.
DISPERSION_POR_DEFECTO = 6.0
#: cotas de cordura: por debajo la cola se dispara, por encima colapsa a Poisson
DISPERSION_MIN, DISPERSION_MAX = 1.0, 60.0


@dataclass
class DefConModel:
    """Conteo de acciones defensivas por 90 y su probabilidad de cruzar el umbral."""
    dispersion: dict = field(default_factory=dict)      # posicion -> r
    sin_datos: bool = True
    metadata: dict = field(default_factory=dict)

    def fit(self, df: pd.DataFrame) -> "DefConModel":
        """Estima la dispersion por posicion con el metodo de los momentos.

        Devuelve `sin_datos = True` si el historico no contiene la columna. Es el
        caso del backtest ciego de 2025/26: la regla no existia antes, asi que el
        componente arranca sin informacion y aprende dentro de la temporada.
        """
        self.dispersion = dict.fromkeys(("DEF", "MID", "FWD"), DISPERSION_POR_DEFECTO)
        self.sin_datos = True
        if df.empty or "defensive_contribution" not in df.columns:
            self.metadata = {"filas": 0, "aviso": "el historico no trae defensive_contribution"}
            return self

        d = df.copy()
        d["minutos"] = pd.to_numeric(d["minutes"], errors="coerce").fillna(0.0)
        d["dc"] = pd.to_numeric(d["defensive_contribution"], errors="coerce")
        d = d[(d["minutos"] > 0) & d["dc"].notna()]
        if d.empty:
            self.metadata = {"filas": 0, "aviso": "sin filas con conteo defensivo"}
            return self

        d["pos"] = normaliza_posicion(d["position"])
        d["n90"] = d["minutos"] / 90.0
        detalle = {}
        for p in ("DEF", "MID", "FWD"):
            sub = d[d["pos"] == p]
            if len(sub) < 200:
                continue
            # tasa individual del propio jugador como media condicional
            tasa = sub.groupby("player_key")["dc"].sum() / sub.groupby("player_key")["n90"].sum()
            mu = (sub["player_key"].map(tasa) * sub["n90"]).to_numpy(dtype=float)
            y = sub["dc"].to_numpy(dtype=float)
            resid = float(np.mean((y - mu) ** 2))
            media = float(np.mean(mu))
            extra = resid - media                        # varianza por encima de Poisson
            r = float(np.mean(mu ** 2) / extra) if extra > 1e-6 else DISPERSION_MAX
            self.dispersion[p] = float(np.clip(r, DISPERSION_MIN, DISPERSION_MAX))
            detalle[p] = {"n": int(len(sub)), "media": round(media, 2),
                          "var_residual": round(resid, 2), "r": round(self.dispersion[p], 2)}

        self.sin_datos = not detalle
        self.metadata = {"filas": int(len(d)), "por_posicion": detalle}
        return self

    def p_umbral(self, tasa90: np.ndarray, noventas: np.ndarray, posiciones,
                 umbrales: dict) -> np.ndarray:
        """P(conteo >= umbral) del partido. GKP siempre 0: no es elegible."""
        tasa90 = np.asarray(tasa90, dtype=float)
        noventas = np.asarray(noventas, dtype=float)
        mu = np.clip(np.nan_to_num(tasa90) * np.clip(noventas, 0.0, None), 1e-9, None)

        pos = [p if isinstance(p, Position) else Position.parse(p) for p in posiciones]
        umbral = np.array([umbrales.get(p, 0) for p in pos], dtype=float)
        r = np.array([self.dispersion.get(p.value, DISPERSION_POR_DEFECTO) for p in pos],
                     dtype=float)

        elegible = umbral > 0
        salida = np.zeros(len(mu), dtype=float)
        if elegible.any():
            m, rr, u = mu[elegible], r[elegible], umbral[elegible]
            salida[elegible] = nbinom.sf(u - 1, rr, rr / (rr + m))
        return salida

    def project(self, tasa90, noventas, posiciones, umbrales, puntos: int) -> dict:
        p = self.p_umbral(tasa90, noventas, posiciones, umbrales)
        return {"p_defcon": p, "puntos_defcon": p * puntos}


def evaluate(model: "DefConModel", history_por_gw, umbrales: dict, bins: int = 10) -> dict:
    """Calibracion de P(conteo >= umbral) sobre una ventana temporal (AC-WP005-004).

    `history_por_gw` es un iterable de (historico_causal, resultados_reales) por
    jornada. La separacion la hace quien llama: aqui no se lee la base de datos.
    """
    from mova_fpl.models.minutes import calibration_table, expected_calibration_error

    filas = []
    for hist, real in history_por_gw:
        if real.empty:
            continue
        model.fit(hist) if not hist.empty else None
        d = real[pd.to_numeric(real["minutes"], errors="coerce").fillna(0) > 0].copy()
        if d.empty:
            continue
        d["pos"] = normaliza_posicion(d["position"])
        tasas = (hist[pd.to_numeric(hist["minutes"], errors="coerce").fillna(0) > 0]
                 if not hist.empty else hist)
        if tasas.empty:
            continue
        suma = tasas.groupby("player_key")["defensive_contribution"].sum()
        n90 = tasas.groupby("player_key")["minutes"].sum() / 90.0
        tasa = (suma / n90.replace(0, np.nan))

        d["tasa90"] = d["player_key"].map(tasa)
        d = d.dropna(subset=["tasa90"])
        if d.empty:
            continue
        p = model.p_umbral(d["tasa90"].to_numpy(float),
                           (d["minutes"].to_numpy(float) / 90.0), d["pos"], umbrales)
        umbral = d["pos"].map(lambda x: umbrales.get(Position.parse(x), 0))
        y = ((d["defensive_contribution"] >= umbral) & (umbral > 0)).astype(float)
        filas.append(pd.DataFrame({"pos": d["pos"].to_numpy(), "p": p,
                                   "y": y.to_numpy(), "elegible": (umbral > 0).to_numpy()}))

    if not filas:
        return {"n": 0}
    todo = pd.concat(filas, ignore_index=True)
    eleg = todo[todo["elegible"]]
    salida = {"n": int(len(eleg)),
              "ece": expected_calibration_error(eleg["y"], eleg["p"], bins),
              "brier": float(np.mean((eleg["p"] - eleg["y"]) ** 2)),
              "tasa_base": float(eleg["y"].mean()),
              "tabla": calibration_table(eleg["y"], eleg["p"], bins)}
    salida["por_posicion"] = {
        p: {"n": int(len(s)),
            "ece": expected_calibration_error(s["y"], s["p"], bins),
            "predicho": float(s["p"].mean()), "observado": float(s["y"].mean())}
        for p, s in eleg.groupby("pos") if len(s) > 50}
    return salida
