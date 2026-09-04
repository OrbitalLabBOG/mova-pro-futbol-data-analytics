"""xP descompuesto por componente (ADR-003, REQ-F-005).

No es una regresion sobre `total_points`. Es la suma de componentes con
distribucion propia, cada uno auditable por separado:

    xP = P(1-59) * puntos_si_juega_parcial + P(60+) * puntos_si_juega_completo

y dentro de cada rama:

    aparicion + goles + asistencias + porteria_a_cero - goles_encajados
    + contribucion_defensiva + bonus - tarjetas + paradas + otros

La estructura por RAMAS, en vez de una sola formula con P(60+) suelta, existe
porque las reglas de FPL no son lineales en los minutos: la porteria a cero
requiere 60 minutos exactos, la penalizacion por goles encajados cuenta solo los
que entran con el jugador en campo, y los puntos de aparicion son 1 o 2, nunca
1,4. Promediar primero y aplicar reglas despues da un numero que ninguna rama
puede producir.

Cada componente reporta ademas su varianza (AC-WP005-007). La varianza total
incluye el termino de mezcla entre ramas, que es el dominante para un suplente:
lo incierto de un rotativo no es cuanto rinde, es si juega.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from mova_fpl.models.bonus import BonusModel
from mova_fpl.models.cleansheet import CleanSheetModel, esperanza_division
from mova_fpl.models.defcon import DefConModel
from mova_fpl.models.features.points_features import (
    K_ATAQUE, K_BONUS, K_DEFENSA, K_DISCIPLINA, apply_priors, multiplicador_ataque,
    lambda_conceded, normaliza_posicion, player_rates, position_priors, team_strength,
)
from mova_fpl.models.goals import GoalsModel
from mova_fpl.rules.base import Position

NOMBRE = "points"
VERSION = "1.0.0"

#: minutos medios de referencia por rama, si el historico no alcanza para estimarlos
MINUTOS_PARCIAL, MINUTOS_COMPLETO = 28.0, 84.0

#: encogimiento por familia de tasa
K_POR_TASA = {
    "g90": K_ATAQUE, "a90": K_ATAQUE, "xg90": K_ATAQUE, "xa90": K_ATAQUE,
    "saves90": K_DEFENSA, "defcon90": K_DEFENSA, "cbi90": K_DEFENSA,
    "recuperaciones90": K_DEFENSA, "entradas90": K_DEFENSA,
    "amarillas90": K_DISCIPLINA, "rojas90": K_DISCIPLINA,
    "penaltis_parados90": K_DISCIPLINA, "autogoles90": K_DISCIPLINA,
    "bps90": K_BONUS, "bonus_aparicion": K_BONUS,
}

#: columnas de puntos que suman el total. El orden es el de la formula.
COMPONENTES = ("pts_aparicion", "pts_goles", "pts_asistencias", "pts_cs",
               "pts_encajados", "pts_defcon", "pts_bonus", "pts_tarjetas",
               "pts_paradas", "pts_otros")


@dataclass
class PointsModel:
    """Orquesta los componentes. No predice nada por si mismo: los compone."""
    name: str = NOMBRE
    version: str = VERSION
    goals: GoalsModel = field(default_factory=GoalsModel)
    cleansheet: CleanSheetModel = field(default_factory=CleanSheetModel)
    defcon: DefConModel = field(default_factory=DefConModel)
    bonus: BonusModel = field(default_factory=BonusModel)
    minutos_parcial: float = MINUTOS_PARCIAL
    minutos_completo: float = MINUTOS_COMPLETO
    #: None reproduce la media histórica. Un valor activa EWM por apariciones
    #: únicamente en el estado de deadline; los priors de entrenamiento quedan
    #: congelados para que la ablation mida recencia y nada más.
    player_recency_half_life: float | None = None
    priors_entrenamiento: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    # ------------------------------------------------------------------ ajuste

    def fit(self, df: pd.DataFrame) -> "PointsModel":
        """Aprende los parametros GLOBALES con temporadas anteriores al holdout.

        Lo que se aprende aqui es transversal —factor de definicion, mapeo de BPS
        a bonus, dispersion defensiva, minutos medios por rama, priors de
        posicion—, nunca el estado de un jugador concreto. Ese se calcula en
        `project` a partir del historico causal de la temporada en curso.
        """
        self.goals.fit(df)
        self.defcon.fit(df)
        self.bonus.fit(df)

        if not df.empty and "minutes" in df.columns:
            m = pd.to_numeric(df["minutes"], errors="coerce")
            parcial, completo = m[(m > 0) & (m < 60)], m[m >= 60]
            if len(parcial) > 100:
                self.minutos_parcial = float(parcial.mean())
            if len(completo) > 100:
                self.minutos_completo = float(completo.mean())

        tasas = player_rates(df)
        self.priors_entrenamiento = position_priors(tasas)
        self.metadata = {
            "filas_ajuste": int(len(df)),
            "temporadas": sorted(df["season"].unique()) if "season" in df else [],
            "minutos_parcial": round(self.minutos_parcial, 1),
            "minutos_completo": round(self.minutos_completo, 1),
            "defcon_sin_datos": self.defcon.sin_datos,
            "definicion": self.goals.definicion,
        }
        return self

    # -------------------------------------------------------------- proyeccion

    def project(self, history: pd.DataFrame, roster: pd.DataFrame,
                minutes_proba: np.ndarray, scoring, umbrales: dict,
                equipos: dict | None = None, prepared: dict | None = None) -> pd.DataFrame:
        """Desglose por componente para cada fila del catalogo (AC-WP005-002).

        `history` viene de `as_of`: nunca contiene la jornada objetivo.
        `minutes_proba` es la salida del modelo de WP-004, columnas [p0, p1, p60].
        `equipos` traduce el id numerico de rival a nombre de club. Se pasa cuando la
        numeracion del catalogo NO coincide con la del historico — que es justo el caso
        de una temporada nueva: FPL reasigna los ids de equipo cada anio igual que los
        de jugador. Sin el, el ajuste por rival se aplicaria contra el club equivocado.
        """
        n = len(roster)
        if n == 0:
            return pd.DataFrame(columns=["element", "xp", "xp_sd", *COMPONENTES])

        pos = normaliza_posicion(roster["position"]).fillna("MID")
        prepared = prepared or self.prepare_history(history)
        tasas_hist = prepared["player_rates"]
        priors = prepared["priors"]
        estado = self._estado_jugador(roster, tasas_hist, priors, pos)
        fuerza = prepared["team_strength"]

        mult, lam_enc = self._contexto_partido(roster, fuerza, equipos)
        p = np.asarray(minutes_proba, dtype=float)
        p1, p60 = p[:, 1], p[:, 2]

        ramas = {}
        for nombre, minutos, completa in (("parcial", self.minutos_parcial, False),
                                          ("completo", self.minutos_completo, True)):
            ramas[nombre] = self._rama(estado, pos, minutos / 90.0, mult, lam_enc,
                                       scoring, umbrales, completa)

        out = pd.DataFrame({"element": roster["element"].to_numpy()})
        for c in COMPONENTES:
            out[c] = p1 * ramas["parcial"][c] + p60 * ramas["completo"][c]
        out["xp"] = out[list(COMPONENTES)].sum(axis=1)

        mu1 = sum(ramas["parcial"][c] for c in COMPONENTES)
        mu60 = sum(ramas["completo"][c] for c in COMPONENTES)
        v1 = ramas["parcial"]["_var"]
        v60 = ramas["completo"]["_var"]
        # varianza total de la mezcla: E[Var | rama] + Var(E[· | rama])
        segundo = p1 * (v1 + mu1 ** 2) + p60 * (v60 + mu60 ** 2)
        out["xp_sd"] = np.sqrt(np.clip(segundo - out["xp"].to_numpy() ** 2, 0.0, None))

        out["p_juega"] = p1 + p60
        out["p_60"] = p60
        out["noventas_esperados"] = (p1 * self.minutos_parcial
                                     + p60 * self.minutos_completo) / 90.0
        out["p_porteria_cero"] = ramas["completo"]["_p_cs"]
        out["p_defcon"] = ramas["completo"]["_p_defcon"]
        out["lambda_encajados"] = lam_enc
        out["multiplicador_rival"] = mult
        return out

    def prepare_history(self, history: pd.DataFrame) -> dict:
        """Calcula una vez el estado compartido por todos los fixtures del plan.

        Es un snapshot puro de la información disponible en el deadline. Pasarlo
        a varias llamadas de ``project`` no adelanta datos; evita reagrupar el
        mismo histórico para cada jornada hipotética del horizonte.
        """
        tasas_hist = player_rates(history, self.player_recency_half_life)
        # el conteo defensivo solo existe desde 2025/26: si el ajuste no lo vio,
        # la dispersion se reestima con lo que lleve la temporada en curso
        if self.defcon.sin_datos and "defensive_contribution" in history.columns:
            self.defcon.fit(history)
        return {
            "player_rates": tasas_hist,
            "priors": self._priors(tasas_hist),
            "team_strength": team_strength(history),
        }

    # ---------------------------------------------------------------- internos

    def _priors(self, tasas_hist: pd.DataFrame) -> dict:
        """Prior de posicion: el de entrenamiento, refrescado con la temporada viva."""
        vivos = position_priors(tasas_hist)
        base = self.priors_entrenamiento or {}
        salida = {}
        for p in set(base) | set(vivos):
            a, b = base.get(p, {}), vivos.get(p, {})
            salida[p] = {k: (b[k] if k in b and np.isfinite(b.get(k, np.nan)) else a.get(k, np.nan))
                         for k in set(a) | set(b)}
        return salida

    def _estado_jugador(self, roster, tasas_hist, priors, pos) -> pd.DataFrame:
        """Tasas del jugador encogidas hacia su prior de posicion."""
        clave = roster["player_key"].fillna("desconocido")
        crudo = tasas_hist.reindex(clave.to_numpy())
        crudo.index = roster.index
        # ``reindex`` sobre un catálogo sin historia puede dejar dtype object;
        # normalizarlo explícitamente evita depender del downcast silencioso de
        # pandas, que está deprecado y cambiará en una versión futura.
        crudo["n90"] = pd.to_numeric(crudo["n90"], errors="coerce").fillna(0.0)
        encogido = apply_priors(crudo, priors, pos, k=K_POR_TASA)
        encogido["n90"] = crudo["n90"]
        return encogido

    def _contexto_partido(self, roster, fuerza, equipos=None) -> tuple[np.ndarray, np.ndarray]:
        """Multiplicador ofensivo y goles esperados en contra, por fila."""
        id_a_nombre = equipos if equipos else fuerza.get("id_a_nombre", {})
        mult, lam = [], []
        for _, r in roster.iterrows():
            equipo = str(r.get("team", ""))
            rival = id_a_nombre.get(int(r["opponent_team"]), "") if pd.notna(
                r.get("opponent_team")) else ""
            local = bool(pd.to_numeric(pd.Series([r.get("was_home")]),
                                       errors="coerce").fillna(0.5).iloc[0] >= 0.5)
            mult.append(multiplicador_ataque(fuerza, equipo, rival, local))
            lam.append(lambda_conceded(fuerza, equipo, rival, local))
        return np.asarray(mult, dtype=float), np.asarray(lam, dtype=float)

    def _rama(self, estado, pos, n90, mult, lam_enc, scoring, umbrales, completa) -> dict:
        """Puntos y varianza CONDICIONADOS a jugar esta cantidad de minutos."""
        cero = np.zeros(len(estado), dtype=float)
        n90v = np.full(len(estado), float(n90))

        lam = self.goals.project(estado, pos, n90v, mult)
        pts_gol = pos.map(lambda p: scoring.goal_points.get(Position.parse(p), 4)).to_numpy(float)
        pts_asi = float(scoring.assist_points)

        cs = self.cleansheet.project(lam_enc * n90v, pos, scoring)
        p_cs = cs["p_porteria_cero"] if completa else cero
        puntos_cs = cs["puntos_cs"] if completa else cero

        d = self.defcon.project(estado["defcon90"].to_numpy(float), n90v, pos, umbrales,
                                scoring.defcon_points)
        bono = self.bonus.project(estado["bps90"], estado["bonus_aparicion"],
                                  estado["n90"], n90v)

        amar = estado["amarillas90"].to_numpy(float) * n90v
        rojas = estado["rojas90"].to_numpy(float) * n90v
        paradas = estado["saves90"].to_numpy(float) * n90v
        penp = estado["penaltis_parados90"].to_numpy(float) * n90v
        auto = estado["autogoles90"].to_numpy(float) * n90v

        comp = {
            "pts_aparicion": np.full(len(estado), float(
                scoring.appearance_long if completa else scoring.appearance_short)),
            "pts_goles": lam["lambda_goles"] * pts_gol,
            "pts_asistencias": lam["lambda_asistencias"] * pts_asi,
            "pts_cs": puntos_cs,
            "pts_encajados": cs["puntos_encajados"],
            "pts_defcon": d["puntos_defcon"],
            "pts_bonus": bono["puntos_bonus"],
            "pts_tarjetas": (amar * scoring.yellow_card_points
                             + rojas * scoring.red_card_points),
            "pts_paradas": esperanza_division(paradas, scoring.saves_per_point),
            "pts_otros": (penp * scoring.penalty_save_points
                          + auto * scoring.own_goal_points),
        }

        # varianza por componente. Poisson para conteos, Bernoulli para umbrales.
        var = (lam["lambda_goles"] * pts_gol ** 2
               + lam["lambda_asistencias"] * pts_asi ** 2
               + (p_cs * (1 - p_cs) * np.array(
                   [scoring.clean_sheet_points.get(Position.parse(p), 0) for p in pos],
                   dtype=float) ** 2)
               + d["p_defcon"] * (1 - d["p_defcon"]) * scoring.defcon_points ** 2
               + lam_enc * n90v / 4.0                      # aprox. de Var(floor(X/2))
               + bono["puntos_bonus"]                       # tratada como conteo
               + amar * scoring.yellow_card_points ** 2
               + rojas * scoring.red_card_points ** 2
               + paradas / scoring.saves_per_point ** 2)          # aprox. de Var(floor(S/3))

        comp["_var"] = var
        comp["_p_cs"] = p_cs
        comp["_p_defcon"] = d["p_defcon"]
        return comp
