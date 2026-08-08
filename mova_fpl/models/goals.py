"""Componente de goles y asistencias. Poisson sobre tasas por 90 (ADR-003).

Por que Poisson y no una regresion sobre puntos: los goles son un conteo raro y
su varianza es su media. Un modelo que solo predice el valor esperado no puede
decirle al optimizador que un delantero de 0,6 goles por 90 es una loteria y un
mediocentro de 0,15 es un metronomo. La varianza sale gratis del supuesto.

Por que xG y no goles: xG es la misma senal con menos ruido. Pero no es la misma
cantidad — hay jugadores que rematan mejor que su xG de forma sostenida— asi que
se estima un FACTOR DE DEFINICION por posicion sobre los datos de entrenamiento
y se mezcla con la tasa de goles observada.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from mova_fpl.models.features.points_features import (
    K_ATAQUE, POSICIONES, normaliza_posicion,
)

#: cuanto pesa xG frente a los goles observados. xG es menos ruidoso pero ciego
#: a la definicion; los goles son lo contrario.
PESO_XG = 0.7

#: cotas del factor de correccion. La de asistencias es MAS ANCHA a proposito:
#: medido sobre 2022-2025, las asistencias reales superan a xA de forma
#: sistematica (DEF 1,32 - MID 1,52 - FWD 2,47), porque xA solo puntua la calidad
#: de la ocasion del ultimo pase y FPL acredita asistencias que xA no ve.
#: No es ruido, es una diferencia de definicion, y recortarla a 1,6 la ocultaba.
COTA_DEFINICION = (0.6, 1.6)
COTA_CREACION = (0.6, 2.8)
#: xG/xA acumulado minimo para creer en el cociente. Los porteros suman 3,5 de xA
#: en cuatro temporadas: su cociente aparente de 4,9 es una casualidad, no un dato.
VOLUMEN_MINIMO = 50.0


@dataclass
class GoalsModel:
    """Tasas de gol y asistencia por 90, encogidas y ajustadas por rival."""
    peso_xg: float = PESO_XG
    k: float = K_ATAQUE
    definicion: dict = field(default_factory=dict)      # posicion -> goles/xG
    creacion: dict = field(default_factory=dict)        # posicion -> asistencias/xA
    metadata: dict = field(default_factory=dict)

    def fit(self, df: pd.DataFrame) -> "GoalsModel":
        """Estima el factor de definicion por posicion sobre el historico."""
        if df.empty or "expected_goals" not in df.columns:
            self.definicion = dict.fromkeys(POSICIONES, 1.0)
            self.creacion = dict.fromkeys(POSICIONES, 1.0)
            self.metadata = {"filas": 0, "aviso": "sin xG en el historico: factores en 1.0"}
            return self

        d = df[pd.to_numeric(df["minutes"], errors="coerce").fillna(0) > 0].copy()
        d["pos"] = normaliza_posicion(d["position"]) if "position" in d else pd.NA
        for origen, destino, campo, cota in (
                ("goals_scored", "expected_goals", "definicion", COTA_DEFINICION),
                ("assists", "expected_assists", "creacion", COTA_CREACION)):
            tabla = {}
            for p in POSICIONES:
                sub = d[d["pos"] == p]
                a = pd.to_numeric(sub.get(origen), errors="coerce")
                b = pd.to_numeric(sub.get(destino), errors="coerce")
                # SOLO filas donde existen las dos. xG llega en 2022-23 y los goles
                # estan desde 2016-17: dividir sumas de universos distintos daba un
                # factor de definicion de 1,6, que no es habilidad sino un sesgo de
                # cobertura. Se detecto porque las tres posiciones tocaron el tope.
                juntos = a.notna() & b.notna()
                real, esp = float(a[juntos].sum()), float(b[juntos].sum())
                tabla[p] = float(np.clip(real / esp, *cota)) if esp > VOLUMEN_MINIMO else 1.0
            setattr(self, campo, tabla)

        self.metadata = {"filas": int(len(d)), "temporadas": sorted(d["season"].unique())
                         if "season" in d else []}
        return self

    def rate(self, tasas: pd.DataFrame, posiciones: pd.Series, tipo: str) -> np.ndarray:
        """Tasa por 90 combinada de xG con goles (o xA con asistencias)."""
        esperada, real, factores = (("xg90", "g90", self.definicion) if tipo == "gol"
                                    else ("xa90", "a90", self.creacion))
        x = pd.to_numeric(tasas.get(esperada), errors="coerce").to_numpy(dtype=float)
        r = pd.to_numeric(tasas.get(real), errors="coerce").to_numpy(dtype=float)
        f = posiciones.map(lambda p: factores.get(p, 1.0)).to_numpy(dtype=float)

        x_aj = x * f
        # si falta uno de los dos, manda el que exista; si faltan ambos, cero
        combinada = np.where(
            np.isfinite(x_aj) & np.isfinite(r), self.peso_xg * x_aj + (1 - self.peso_xg) * r,
            np.where(np.isfinite(x_aj), x_aj, np.where(np.isfinite(r), r, 0.0)))
        return np.clip(combinada, 0.0, None)

    def project(self, tasas: pd.DataFrame, posiciones: pd.Series, noventas: np.ndarray,
                multiplicador: np.ndarray) -> dict:
        """Lambdas de Poisson del partido. `noventas` = minutos esperados / 90."""
        lam_g = self.rate(tasas, posiciones, "gol") * noventas * multiplicador
        lam_a = self.rate(tasas, posiciones, "asistencia") * noventas * multiplicador
        return {"lambda_goles": lam_g, "lambda_asistencias": lam_a}
