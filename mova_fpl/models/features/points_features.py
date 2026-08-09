"""Agregados causales por jugador y por equipo para el modelo de puntos.

A diferencia de `minutes_features`, aqui no se construye una matriz fila a fila:
lo que necesita la proyeccion es el ESTADO de cada jugador antes del cierre —su
tasa de goles por 90, su tasa de acciones defensivas, su bonus por aparicion— y
el estado de cada equipo. Son agregados, no observaciones.

La causalidad no se impone aqui: viene garantizada aguas arriba porque el frame
que entra es siempre `Store.as_of` o `Store.multi_season_as_of` (ADR-002). Este
modulo no lee la base de datos ni conoce la jornada objetivo.

Regla de encogimiento
---------------------
Toda tasa individual se encoge hacia un prior de posicion segun la exposicion
observada, medida en noventas jugados:

    tasa = (n90 * observado + k * prior) / (n90 + k)

Con `n90 = 0` la tasa ES el prior. No hay division por cero ni tasas de 3 goles
por 90 salidas de un jugador con doce minutos.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

#: noventas jugados para que lo observado pese la mitad frente al prior
K_ATAQUE = 8.0        # goles y asistencias: senal ruidosa, encoge fuerte
K_DEFENSA = 4.0       # acciones defensivas: senal mucho mas estable
K_BONUS = 6.0
K_DISCIPLINA = 10.0   # tarjetas: eventos raros
K_EQUIPO = 5.0        # partidos de equipo para creer en su ataque/defensa

POSICIONES = ("GKP", "DEF", "MID", "FWD")


def normaliza_posicion(s: pd.Series) -> pd.Series:
    p = s.astype("string").str.upper().str.strip()
    return p.replace({"GK": "GKP", "GOALKEEPER": "GKP", "G": "GKP", "D": "DEF",
                      "DEFENDER": "DEF", "M": "MID", "MIDFIELDER": "MID",
                      "F": "FWD", "FORWARD": "FWD", "STRIKER": "FWD"})


def shrink(observado, n, prior, k: float):
    """Media posterior de una tasa con prior de posicion. Vectorizada."""
    n = np.asarray(n, dtype=float)
    obs = np.asarray(observado, dtype=float)
    prior = np.asarray(prior, dtype=float)
    obs = np.where(np.isfinite(obs), obs, 0.0)
    return (n * obs + k * prior) / (n + k)


# --------------------------------------------------------------- por jugador

#: (columna del almacen, nombre de la tasa). Todas se normalizan por 90 minutos.
TASAS_POR_90 = (
    ("goals_scored", "g90"),
    ("assists", "a90"),
    ("expected_goals", "xg90"),
    ("expected_assists", "xa90"),
    ("saves", "saves90"),
    ("yellow_cards", "amarillas90"),
    ("red_cards", "rojas90"),
    ("defensive_contribution", "defcon90"),
    ("clearances_blocks_interceptions", "cbi90"),
    ("recoveries", "recuperaciones90"),
    ("tackles", "entradas90"),
    ("penalties_saved", "penaltis_parados90"),
    ("own_goals", "autogoles90"),
    ("bps", "bps90"),
)


def player_rates(history: pd.DataFrame) -> pd.DataFrame:
    """Tasas por 90 y por aparicion de cada jugador, sin encoger todavia.

    Indexado por `player_key`. Una columna ausente en el historico produce NaN,
    jamas cero: no saber cuantos despejes hizo un jugador en 2019 no es saber
    que hizo cero (REQ-F-001).
    """
    if history.empty:
        return pd.DataFrame(columns=["n90", "apariciones", "posicion"]).rename_axis("player_key")

    d = history.copy()
    d["player_key"] = d["player_key"].fillna("desconocido")
    d["minutos"] = pd.to_numeric(d["minutes"], errors="coerce").fillna(0.0)
    jug = d[d["minutos"] > 0]
    if jug.empty:
        return pd.DataFrame(columns=["n90", "apariciones", "posicion"]).rename_axis("player_key")

    g = jug.groupby("player_key", sort=False)
    out = pd.DataFrame({
        "n90": g["minutos"].sum() / 90.0,
        "apariciones": g.size(),
        "minutos_medios": g["minutos"].mean(),
    })

    for col, nombre in TASAS_POR_90:
        if col not in jug.columns:
            out[nombre] = np.nan
            continue
        v = pd.to_numeric(jug[col], errors="coerce")
        # una columna que no existe en NINGUNA fila del historico queda NaN
        if v.notna().sum() == 0:
            out[nombre] = np.nan
            continue
        suma = v.groupby(jug["player_key"], sort=False).sum(min_count=1)
        expo = jug.loc[v.notna(), "minutos"].groupby(
            jug.loc[v.notna(), "player_key"], sort=False).sum() / 90.0
        out[nombre] = suma / expo.replace(0.0, np.nan)

    if "bonus" in jug.columns:
        b = pd.to_numeric(jug["bonus"], errors="coerce")
        out["bonus_aparicion"] = b.groupby(jug["player_key"], sort=False).mean()
    else:
        out["bonus_aparicion"] = np.nan

    if "position" in jug.columns:
        out["posicion"] = normaliza_posicion(jug["position"]).groupby(
            jug["player_key"], sort=False).last()
    else:
        out["posicion"] = pd.NA
    return out


def position_priors(rates: pd.DataFrame, minimo_n90: float = 3.0) -> dict:
    """Prior por posicion: la mediana ponderada de quienes tienen exposicion real.

    Se usa la MEDIANA y no la media porque las tasas de ataque tienen cola larga:
    con la media, el prior de un delantero lo fija Haaland.
    """
    cols = [n for _, n in TASAS_POR_90] + ["bonus_aparicion", "minutos_medios"]
    priors: dict = {}
    if rates.empty:
        return {p: dict.fromkeys(cols, np.nan) for p in POSICIONES}

    solidos = rates[rates["n90"] >= minimo_n90]
    base = solidos if len(solidos) >= 40 else rates
    global_ = {c: float(base[c].median()) if c in base and base[c].notna().any() else np.nan
               for c in cols}
    for p in POSICIONES:
        sub = base[base["posicion"] == p]
        priors[p] = {c: (float(sub[c].median())
                         if c in sub and sub[c].notna().any() else global_[c])
                     for c in cols}
    return priors


def apply_priors(rates: pd.DataFrame, priors: dict, posiciones: pd.Series,
                 columnas=None, k: float | dict | None = None) -> pd.DataFrame:
    """Encoge las tasas de `rates` hacia el prior de su posicion."""
    columnas = columnas or [n for _, n in TASAS_POR_90] + ["bonus_aparicion"]
    ks = {c: (k.get(c, K_ATAQUE) if isinstance(k, dict) else (k or K_ATAQUE)) for c in columnas}
    out = pd.DataFrame(index=rates.index)
    n90 = rates["n90"].to_numpy(dtype=float) if "n90" in rates else np.zeros(len(rates))
    for c in columnas:
        prior = posiciones.map(lambda p: priors.get(p, {}).get(c, np.nan)).to_numpy(dtype=float)
        obs = rates[c].to_numpy(dtype=float) if c in rates else np.full(len(rates), np.nan)
        vista = np.where(np.isfinite(obs), n90, 0.0)          # sin dato, no hay exposicion
        out[c] = shrink(np.nan_to_num(obs), vista, prior, ks[c])
    return out


# ----------------------------------------------------------------- por equipo

def team_strength(history: pd.DataFrame, k: float = K_EQUIPO,
                  temporadas: int = 1) -> dict:
    """Ataque y defensa multiplicativos por equipo, mas el factor de localia.

    Se calcula sobre filas EQUIPO-PARTIDO, no jugador-partido: un partido cuenta
    una vez, no quince. Los goles salen del marcador, que es exacto, no de
    `goals_conceded` por jugador, que depende de los minutos que estuvo en campo.

    `temporadas` acota la ventana a las N mas recientes. El defecto es 1 porque la
    fuerza de un club es una propiedad del presente: promediar diez temporadas
    mezcla plantillas, entrenadores y divisiones distintas, y le asigna a un
    recien ascendido el rendimiento que tuvo la ultima vez que estuvo arriba.
    En el backtest es inocuo —el historico ya viene acotado a la temporada en
    curso— pero en la decision en vivo cambia el resultado.
    """
    vacio = {"ataque": {}, "defensa": {}, "media": 1.35, "factor_local": 1.0,
             "factor_visitante": 1.0, "id_a_nombre": {}, "partidos": {}}
    req = {"team", "fixture", "was_home", "team_h_score", "team_a_score"}
    if history.empty or not req <= set(history.columns):
        return vacio

    d = history.dropna(subset=["team", "fixture"]).copy()
    if temporadas and "season" in d.columns:
        vigentes = sorted(d["season"].dropna().unique())[-int(temporadas):]
        d = d[d["season"].isin(vigentes)]
        if d.empty:
            return vacio
    d["was_home"] = pd.to_numeric(d["was_home"], errors="coerce")
    partidos = d.drop_duplicates(subset=["season", "gw", "fixture", "team"]).copy()
    if partidos.empty:
        return vacio

    h = pd.to_numeric(partidos["team_h_score"], errors="coerce")
    a = pd.to_numeric(partidos["team_a_score"], errors="coerce")
    local = partidos["was_home"] == 1
    partidos["marcados"] = np.where(local, h, a)
    partidos["encajados"] = np.where(local, a, h)
    partidos = partidos.dropna(subset=["marcados", "encajados"])
    if partidos.empty:
        return vacio

    media = float(partidos["marcados"].mean()) or 1.35
    ml = partidos.loc[local, "marcados"].mean()
    mv = partidos.loc[~local, "marcados"].mean()
    factor_local = float(ml / media) if np.isfinite(ml) and media else 1.0
    factor_visitante = float(mv / media) if np.isfinite(mv) and media else 1.0

    g = partidos.groupby("team")
    n = g.size()
    ataque = shrink(g["marcados"].mean() / media, n, 1.0, k)
    defensa = shrink(g["encajados"].mean() / media, n, 1.0, k)

    # id numerico de rival -> nombre de club, deducido del emparejamiento
    id_a_nombre: dict = {}
    if "opponent_team" in partidos.columns:
        for (_, _, _), par in partidos.groupby(["season", "gw", "fixture"], sort=False):
            if len(par) != 2:
                continue
            f1, f2 = par.iloc[0], par.iloc[1]
            id_a_nombre[int(f1["opponent_team"])] = str(f2["team"])
            id_a_nombre[int(f2["opponent_team"])] = str(f1["team"])

    return {
        "ataque": {str(t): float(v) for t, v in zip(n.index, ataque)},
        "defensa": {str(t): float(v) for t, v in zip(n.index, defensa)},
        "media": media, "factor_local": factor_local, "factor_visitante": factor_visitante,
        "id_a_nombre": id_a_nombre,
        "partidos": {str(t): int(v) for t, v in n.items()},
    }


def lambda_conceded(fuerza: dict, equipo: str, rival: str, local: bool) -> float:
    """Goles que se espera que encaje `equipo` en este partido."""
    at = fuerza["ataque"].get(str(rival), 1.0)
    df = fuerza["defensa"].get(str(equipo), 1.0)
    sitio = fuerza["factor_visitante"] if local else fuerza["factor_local"]
    return max(0.05, fuerza["media"] * at * df * sitio)


def multiplicador_ataque(fuerza: dict, equipo: str, rival: str, local: bool) -> float:
    """Cuanto mas o menos de lo habitual se espera que produzca este jugador."""
    at = fuerza["ataque"].get(str(equipo), 1.0)
    df = fuerza["defensa"].get(str(rival), 1.0)
    sitio = fuerza["factor_local"] if local else fuerza["factor_visitante"]
    base = fuerza["ataque"].get(str(equipo), 1.0)
    if base <= 0:
        return 1.0
    return float(np.clip((at * df * sitio) / max(at, 1e-6), 0.4, 2.0))
