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

from dataclasses import dataclass

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
    # Proxies de eventos nativos de FPL. Estan disponibles en las diez
    # temporadas y solo entran desde historia cerrada. El modelo productivo no
    # los consume todavia; el laboratorio puede contrastarlos causalmente.
    ("influence", "influence90"),
    ("creativity", "creativity90"),
    ("threat", "threat90"),
    ("ict_index", "ict90"),
)


def player_rates(history: pd.DataFrame, half_life_appearances: float | None = None) -> pd.DataFrame:
    """Tasas por 90 y por aparicion de cada jugador, sin encoger todavia.

    Indexado por `player_key`. Una columna ausente en el historico produce NaN,
    jamas cero: no saber cuantos despejes hizo un jugador en 2019 no es saber
    que hizo cero (REQ-F-001).
    """
    if history.empty:
        return pd.DataFrame(columns=["n90", "apariciones", "posicion"]).rename_axis("player_key")

    if half_life_appearances is not None and half_life_appearances <= 0:
        raise ValueError("half_life_appearances debe ser positivo")
    d = history.copy()
    d["player_key"] = d["player_key"].fillna("desconocido")
    d = d.sort_values([c for c in ("player_key", "season", "gw", "fixture") if c in d])
    d["minutos"] = pd.to_numeric(d["minutes"], errors="coerce").fillna(0.0)
    jug = d[d["minutos"] > 0].copy()
    if jug.empty:
        return pd.DataFrame(columns=["n90", "apariciones", "posicion"]).rename_axis("player_key")

    g = jug.groupby("player_key", sort=False)
    if half_life_appearances is None:
        jug["_peso"] = 1.0
    else:
        age = g["minutos"].transform("size") - g.cumcount() - 1
        jug["_peso"] = np.exp2(-age.to_numpy(dtype=float) / float(half_life_appearances))
    weighted_minutes = jug["minutos"] * jug["_peso"]
    sum_weight = jug["_peso"].groupby(jug["player_key"], sort=False).sum()
    sum_minutes = weighted_minutes.groupby(jug["player_key"], sort=False).sum()
    out = pd.DataFrame({
        "n90": sum_minutes / 90.0,
        "apariciones": sum_weight,
        "minutos_medios": sum_minutes / sum_weight.replace(0.0, np.nan),
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
        valid = v.notna()
        suma = (v[valid] * jug.loc[valid, "_peso"]).groupby(
            jug.loc[valid, "player_key"], sort=False).sum(min_count=1)
        expo = (jug.loc[valid, "minutos"] * jug.loc[valid, "_peso"]).groupby(
            jug.loc[valid, "player_key"], sort=False).sum() / 90.0
        out[nombre] = suma / expo.replace(0.0, np.nan)

    if "bonus" in jug.columns:
        b = pd.to_numeric(jug["bonus"], errors="coerce")
        valid = b.notna()
        numerator = (b[valid] * jug.loc[valid, "_peso"]).groupby(
            jug.loc[valid, "player_key"], sort=False).sum()
        denominator = jug.loc[valid, "_peso"].groupby(
            jug.loc[valid, "player_key"], sort=False).sum()
        out["bonus_aparicion"] = numerator / denominator.replace(0.0, np.nan)
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


# ----------------------------------------- recencia Empirical Bayes en 2 etapas

ATTACK_RATES = frozenset({
    "g90", "a90", "xg90", "xa90", "threat90", "creativity90",
})
DEFENSE_ROLE_RATES = frozenset({
    "saves90", "defcon90", "cbi90", "recuperaciones90", "entradas90",
})
BONUS_ROLE_RATES = frozenset({
    "bps90", "bonus_aparicion", "influence90", "ict90",
})
DISCIPLINE_RATES = frozenset({
    "amarillas90", "rojas90", "penaltis_parados90", "autogoles90",
})

ALL_RATE_SPECS = tuple(TASAS_POR_90) + (("bonus", "bonus_aparicion"),)


@dataclass(frozen=True)
class RecencyEBConfig:
    """Hiperparámetros de recencia Empirical Bayes en dos etapas para PointsModel.

    Etapa 1 (prior pretemporada):
        n_eff = gamma_club * min(n90_prev, n_cap)
        mu_0  = (n_eff * r_prev + k_pop * mu_pop(pos, price_quartile)) / (n_eff + k_pop)

    Etapa 2 (actualización in-season por edad en GWs):
        w_t   = 2^(-(gw_target - 1 - gw_t) / H)
        r_hat = (sum(w_t * x_t) + k_in * mu_0) / (sum(w_t * e_t) + k_in)
    """
    h_attack: float = 8.0
    k_in_attack: float = 6.0
    h_role: float = 5.0
    k_in_role: float = 4.0
    k_in_newcomer_attack: float | None = None
    k_in_newcomer_role: float | None = None
    n_cap: float = 15.0
    gamma_club: float = 0.7
    k_pop_attack: float = K_ATAQUE
    k_pop_defense: float = K_DEFENSA
    k_pop_bonus: float = K_BONUS
    k_pop_discipline: float = K_DISCIPLINA
    price_quartiles: int = 4
    skip_bonus_double_shrink: bool = True

    def __post_init__(self) -> None:
        if self.h_attack <= 0 or self.h_role <= 0:
            raise ValueError("h_attack y h_role deben ser positivos")
        if self.k_in_attack < 0 or self.k_in_role < 0:
            raise ValueError("k_in_attack y k_in_role deben ser >= 0")
        if self.n_cap <= 0:
            raise ValueError("n_cap debe ser positivo")
        if not (0.0 < self.gamma_club <= 1.0):
            raise ValueError("gamma_club debe estar en (0, 1]")
        if self.price_quartiles < 1:
            raise ValueError("price_quartiles debe ser >= 1")

    @property
    def effective_k_in_newcomer_attack(self) -> float:
        if self.k_in_newcomer_attack is not None:
            return float(self.k_in_newcomer_attack)
        return max(8.0, float(self.k_in_attack) + 2.0)

    @property
    def effective_k_in_newcomer_role(self) -> float:
        if self.k_in_newcomer_role is not None:
            return float(self.k_in_newcomer_role)
        return max(6.0, float(self.k_in_role) + 2.0)

    def half_life_for(self, rate_name: str) -> float:
        if rate_name in ATTACK_RATES:
            return float(self.h_attack)
        return float(self.h_role)

    def k_pop_for(self, rate_name: str) -> float:
        if rate_name in ATTACK_RATES:
            return float(self.k_pop_attack)
        if rate_name in DEFENSE_ROLE_RATES:
            return float(self.k_pop_defense)
        if rate_name in BONUS_ROLE_RATES:
            return float(self.k_pop_bonus)
        if rate_name in DISCIPLINE_RATES:
            return float(self.k_pop_discipline)
        return float(self.k_pop_attack)

    def k_in_for(self, rate_name: str, *, newcomer: bool) -> float:
        if rate_name in ATTACK_RATES:
            return self.effective_k_in_newcomer_attack if newcomer else float(self.k_in_attack)
        if rate_name in DISCIPLINE_RATES:
            base = max(float(self.k_in_role), float(self.k_pop_discipline))
            return base + 2.0 if newcomer else base
        return self.effective_k_in_newcomer_role if newcomer else float(self.k_in_role)


def _initial_prices_by_player(df: pd.DataFrame) -> pd.Series:
    """Precio inicial (primera observación cronológica con `value` finito) por `player_key`."""
    if df.empty or "value" not in df.columns:
        return pd.Series(dtype=float)
    d = df.copy()
    d["player_key"] = d["player_key"].fillna("desconocido")
    d["_val"] = pd.to_numeric(d["value"], errors="coerce")
    d = d[d["_val"].notna()]
    if d.empty:
        return pd.Series(dtype=float)
    sort_cols = [c for c in ("season", "gw", "fixture") if c in d.columns]
    if sort_cols:
        d = d.sort_values(sort_cols, kind="mergesort")
    return d.groupby("player_key", sort=False)["_val"].first()


def stratified_population_priors(df: pd.DataFrame, price_quartiles: int = 4) -> dict:
    """Media ponderada por exposición, estratificada por `(posición × cuartil de precio inicial)`.

    No usa la mediana global de posición: preserva la media poblacional de tasas
    Poisson asimétricas dentro de cada tramo de precio inicial.
    """
    rate_names = [name for _, name in ALL_RATE_SPECS]
    empty = {
        "edges": {},
        "by_stratum": {},
        "by_pos": {p: dict.fromkeys(rate_names, np.nan) for p in POSICIONES},
        "global": dict.fromkeys(rate_names, np.nan),
    }
    if df.empty:
        return empty

    d = df.copy()
    d["player_key"] = d["player_key"].fillna("desconocido")
    d["_min"] = pd.to_numeric(d["minutes"], errors="coerce").fillna(0.0)
    jug = d[d["_min"] > 0].copy()
    if jug.empty:
        return empty

    jug["_n90"] = jug["_min"] / 90.0
    jug["_pos"] = normaliza_posicion(jug["position"]).fillna("MID") if "position" in jug.columns else "MID"

    # Precio inicial por jugador en esta temporada (nunca precio tardío).
    init_price = _initial_prices_by_player(d)
    jug["_price0"] = jug["player_key"].map(init_price)

    # Cuartiles por posición sobre jugadores con exposición positiva en `df`.
    edges: dict[str, np.ndarray] = {}
    player_meta = jug.groupby("player_key", sort=False).agg(
        pos=("_pos", "last"),
        price0=("_price0", "first"),
    )
    if price_quartiles > 1:
        qs = np.linspace(0.0, 1.0, price_quartiles + 1)[1:-1]
        for p in POSICIONES:
            vals = player_meta.loc[player_meta["pos"] == p, "price0"].dropna().to_numpy(dtype=float)
            if len(vals) >= price_quartiles:
                edges[p] = np.unique(np.quantile(vals, qs))
            else:
                edges[p] = np.array([], dtype=float)
    else:
        for p in POSICIONES:
            edges[p] = np.array([], dtype=float)

    q_arr = np.full(len(jug), -1, dtype=int)
    pos_vals = jug["_pos"].to_numpy()
    p0_vals = jug["_price0"].to_numpy(dtype=float)
    for p in POSICIONES:
        mask = (pos_vals == p) & np.isfinite(p0_vals)
        if not mask.any():
            continue
        ed = edges.get(p, np.array([], dtype=float))
        q_arr[mask] = np.digitize(p0_vals[mask], ed, right=True) if len(ed) > 0 else 0
    jug["_q"] = q_arr

    by_stratum: dict[tuple[str, int], dict[str, float]] = {}
    by_pos: dict[str, dict[str, float]] = {p: {} for p in POSICIONES}
    global_means: dict[str, float] = {}

    for col, rate_name in ALL_RATE_SPECS:
        if col not in jug.columns:
            global_means[rate_name] = np.nan
            for p in POSICIONES:
                by_pos[p][rate_name] = np.nan
            continue
        v = pd.to_numeric(jug[col], errors="coerce")
        valid = v.notna()
        if not valid.any():
            global_means[rate_name] = np.nan
            for p in POSICIONES:
                by_pos[p][rate_name] = np.nan
            continue

        expo_col = np.ones(int(valid.sum()), dtype=float) if rate_name == "bonus_aparicion" else jug.loc[valid, "_n90"].to_numpy(dtype=float)
        x_vals = v.loc[valid].to_numpy(dtype=float)
        tot_e = float(expo_col.sum())
        global_means[rate_name] = float(x_vals.sum() / tot_e) if tot_e > 0 else np.nan

        sub = pd.DataFrame({
            "pos": jug.loc[valid, "_pos"].to_numpy(),
            "q": jug.loc[valid, "_q"].to_numpy(),
            "x": x_vals,
            "e": expo_col,
        })
        gp = sub.groupby("pos", sort=False).agg(x=("x", "sum"), e=("e", "sum"))
        for p in POSICIONES:
            if p in gp.index and gp.loc[p, "e"] > 0:
                by_pos[p][rate_name] = float(gp.loc[p, "x"] / gp.loc[p, "e"])
            else:
                by_pos[p][rate_name] = global_means[rate_name]

        valid_q = sub[sub["q"] >= 0]
        if not valid_q.empty:
            gs = valid_q.groupby(["pos", "q"], sort=False).agg(x=("x", "sum"), e=("e", "sum"))
            for (p, q_bin), row in gs.iterrows():
                if row["e"] > 0:
                    by_stratum.setdefault((str(p), int(q_bin)), {})[rate_name] = float(row["x"] / row["e"])

    return {
        "edges": edges,
        "by_stratum": by_stratum,
        "by_pos": by_pos,
        "global": global_means,
    }


def _split_prev_curr_history(history: pd.DataFrame,
                             target_season: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Separa el histórico causal en temporada inmediatamente anterior y temporada actual."""
    if history.empty:
        return history.iloc[0:0], history.iloc[0:0]
    if "season" not in history.columns:
        return history.iloc[0:0], history

    seasons = sorted(str(s) for s in history["season"].dropna().unique())
    if not seasons:
        return history.iloc[0:0], history

    if target_season is None:
        curr_season = seasons[-1]
    else:
        curr_season = str(target_season)

    past = [s for s in seasons if s < curr_season]
    prev_season = past[-1] if past else None

    season_str = history["season"].astype(str)
    curr_hist = history[season_str == curr_season]
    prev_hist = history[season_str == prev_season] if prev_season is not None else history.iloc[0:0]
    return prev_hist, curr_hist


def prepare_eb_state(history: pd.DataFrame, cfg: RecencyEBConfig, *,
                     target_season: str | None = None,
                     target_gw: int | None = None,
                     fallback_priors: dict | None = None) -> dict:
    """Precalcula agregados causales de Etapa 1 (temporada previa) y Etapa 2 (in-season EWM)."""
    prev_hist, curr_hist = _split_prev_curr_history(history, target_season=target_season)

    prev_pop = stratified_population_priors(prev_hist, price_quartiles=cfg.price_quartiles)
    curr_pop = stratified_population_priors(curr_hist, price_quartiles=cfg.price_quartiles)

    # --- Etapa 1: agregados de la temporada previa por jugador
    prev_last_team: dict[str, str] = {}
    prev_sum: dict[str, pd.Series] = {}
    prev_expo: dict[str, pd.Series] = {}
    prev_n90 = pd.Series(dtype=float)

    if not prev_hist.empty:
        p = prev_hist.copy()
        p["player_key"] = p["player_key"].fillna("desconocido")
        sort_cols = [c for c in ("season", "gw", "fixture") if c in p.columns]
        if sort_cols:
            p = p.sort_values(sort_cols, kind="mergesort")
        if "team" in p.columns:
            t_valid = p[p["team"].notna()]
            if not t_valid.empty:
                prev_last_team = {
                    str(k): str(v).strip()
                    for k, v in t_valid.groupby("player_key", sort=False)["team"].last().items()
                }
        p["_min"] = pd.to_numeric(p["minutes"], errors="coerce").fillna(0.0)
        p_jug = p[p["_min"] > 0].copy()
        if not p_jug.empty:
            p_jug["_n90"] = p_jug["_min"] / 90.0
            prev_n90 = p_jug.groupby("player_key", sort=False)["_n90"].sum()
            for col, rate_name in ALL_RATE_SPECS:
                if col not in p_jug.columns:
                    continue
                v = pd.to_numeric(p_jug[col], errors="coerce")
                valid = v.notna()
                if not valid.any():
                    continue
                keys_v = p_jug.loc[valid, "player_key"]
                prev_sum[rate_name] = v.loc[valid].groupby(keys_v, sort=False).sum()
                if rate_name == "bonus_aparicion":
                    prev_expo[rate_name] = pd.Series(1.0, index=keys_v.index).groupby(keys_v, sort=False).sum()
                else:
                    prev_expo[rate_name] = p_jug.loc[valid, "_n90"].groupby(keys_v, sort=False).sum()

    # --- Etapa 2: EWM solo sobre la temporada actual, ponderado por edad en GWs
    curr_init_price = _initial_prices_by_player(curr_hist)
    ewm_x: dict[str, pd.Series] = {}
    ewm_e: dict[str, pd.Series] = {}
    ewm_n90_role = pd.Series(dtype=float)

    if not curr_hist.empty:
        c = curr_hist.copy()
        c["player_key"] = c["player_key"].fillna("desconocido")
        c["_min"] = pd.to_numeric(c["minutes"], errors="coerce").fillna(0.0)
        c["_gw"] = pd.to_numeric(c["gw"], errors="coerce") if "gw" in c.columns else 1.0
        c_jug = c[c["_min"] > 0].copy()
        if not c_jug.empty:
            c_jug["_n90"] = c_jug["_min"] / 90.0
            if target_gw is not None:
                gw_ref = float(int(target_gw) - 1)
            else:
                max_gw = pd.to_numeric(c["gw"], errors="coerce").max() if "gw" in c.columns else 1.0
                gw_ref = float(max_gw) if np.isfinite(max_gw) else 1.0
            age = np.maximum(0.0, gw_ref - c_jug["_gw"].fillna(gw_ref).to_numpy(dtype=float))

            weights_by_h: dict[float, np.ndarray] = {}
            for h in {float(cfg.h_attack), float(cfg.h_role)}:
                weights_by_h[h] = np.exp2(-age / h)

            w_role = weights_by_h[float(cfg.h_role)]
            ewm_n90_role = (c_jug["_n90"] * w_role).groupby(c_jug["player_key"], sort=False).sum()

            for col, rate_name in ALL_RATE_SPECS:
                if col not in c_jug.columns:
                    continue
                v = pd.to_numeric(c_jug[col], errors="coerce")
                valid = v.notna()
                if not valid.any():
                    continue
                h = cfg.half_life_for(rate_name)
                w_all = weights_by_h[h]
                valid_np = valid.to_numpy()
                w_v = w_all[valid_np]
                keys_v = c_jug.loc[valid, "player_key"]
                x_v = v.loc[valid].to_numpy(dtype=float)
                e_v = np.ones(len(x_v), dtype=float) if rate_name == "bonus_aparicion" else c_jug.loc[valid, "_n90"].to_numpy(dtype=float)
                ewm_x[rate_name] = pd.Series(w_v * x_v, index=keys_v.index).groupby(keys_v, sort=False).sum()
                ewm_e[rate_name] = pd.Series(w_v * e_v, index=keys_v.index).groupby(keys_v, sort=False).sum()

    return {
        "prev_pop": prev_pop,
        "curr_pop": curr_pop,
        "fallback_priors": fallback_priors or {},
        "prev_last_team": prev_last_team,
        "prev_sum": prev_sum,
        "prev_expo": prev_expo,
        "prev_n90": prev_n90,
        "curr_init_price": curr_init_price,
        "ewm_x": ewm_x,
        "ewm_e": ewm_e,
        "ewm_n90_role": ewm_n90_role,
    }


def apply_eb_rates(roster: pd.DataFrame, posiciones: pd.Series,
                   eb_state: dict, cfg: RecencyEBConfig) -> pd.DataFrame:
    """Calcula las tasas posteriores en dos etapas para cada fila de `roster`.

    Reemplaza a `apply_priors` + `position_priors` (no se apila encima).
    """
    n = len(roster)
    out = pd.DataFrame(index=roster.index)
    if n == 0:
        out["n90"] = np.array([], dtype=float)
        return out

    keys = roster["player_key"].fillna("desconocido").astype(str).to_numpy()
    pos_arr = posiciones.fillna("MID").astype(str).to_numpy()

    # Precio inicial causal de la temporada actual (primera aparición en curr_hist, si no roster.value)
    curr_init_price: pd.Series = eb_state["curr_init_price"]
    roster_val = (
        pd.to_numeric(roster["value"], errors="coerce").to_numpy(dtype=float)
        if "value" in roster.columns else np.full(n, np.nan)
    )
    if not curr_init_price.empty:
        mapped_p0 = curr_init_price.reindex(keys).to_numpy(dtype=float)
        price0 = np.where(np.isfinite(mapped_p0), mapped_p0, roster_val)
    else:
        price0 = roster_val

    # Cuartiles de precio inicial desde la temporada previa (o actual si no hay previa)
    prev_pop = eb_state["prev_pop"]
    curr_pop = eb_state["curr_pop"]
    fallback_priors = eb_state["fallback_priors"]

    def _digitize_for(pop_dict: dict) -> np.ndarray:
        edges_map = pop_dict.get("edges", {})
        q_arr = np.full(n, -1, dtype=int)
        for p in POSICIONES:
            mask = (pos_arr == p) & np.isfinite(price0)
            if not mask.any():
                continue
            ed = edges_map.get(p)
            if ed is None:
                continue
            q_arr[mask] = np.digitize(price0[mask], ed, right=True) if len(ed) > 0 else 0
        return q_arr

    q_prev = _digitize_for(prev_pop)
    q_curr = _digitize_for(curr_pop)

    # Descuento por cambio de club entre temporada previa y club actual
    prev_last_team: dict[str, str] = eb_state["prev_last_team"]
    curr_team = (
        roster["team"].fillna("").astype(str).str.strip().to_numpy()
        if "team" in roster.columns else np.full(n, "", dtype=object)
    )
    prev_team = np.array([prev_last_team.get(k, "") for k in keys], dtype=object)
    club_changed = (prev_team != "") & (curr_team != "") & (prev_team != curr_team)
    gamma = np.where(club_changed, float(cfg.gamma_club), 1.0)

    prev_sum = eb_state["prev_sum"]
    prev_expo = eb_state["prev_expo"]
    ewm_x = eb_state["ewm_x"]
    ewm_e = eb_state["ewm_e"]

    def _lookup_pop(rate_name: str) -> np.ndarray:
        # Prioridad: estrato prev_pop -> pos prev_pop -> global prev_pop
        # Si la columna no existía en prev_hist, usa curr_pop (p. ej. defcon90 en 2025-26)
        # y por último priors_entrenamiento.
        use_prev = np.isfinite(prev_pop["global"].get(rate_name, np.nan))
        pop_src = prev_pop if use_prev else curr_pop
        q_idx = q_prev if use_prev else q_curr
        by_stratum = pop_src["by_stratum"]
        by_pos = pop_src["by_pos"]
        glob = pop_src["global"].get(rate_name, np.nan)

        mu = np.empty(n, dtype=float)
        for i in range(n):
            p = pos_arr[i]
            q_i = int(q_idx[i])
            val = np.nan
            if q_i >= 0:
                val = by_stratum.get((p, q_i), {}).get(rate_name, np.nan)
            if not np.isfinite(val):
                val = by_pos.get(p, {}).get(rate_name, np.nan)
            if not np.isfinite(val):
                val = glob
            if not np.isfinite(val):
                val = fallback_priors.get(p, {}).get(rate_name, np.nan)
            mu[i] = float(val) if np.isfinite(val) else np.nan
        return mu

    for _, rate_name in ALL_RATE_SPECS:
        mu_pop = _lookup_pop(rate_name)

        # Etapa 1: prior individual de la temporada previa
        if rate_name in prev_expo:
            n_prev = prev_expo[rate_name].reindex(keys).fillna(0.0).to_numpy(dtype=float)
            x_prev = prev_sum[rate_name].reindex(keys).fillna(0.0).to_numpy(dtype=float)
        else:
            n_prev = np.zeros(n, dtype=float)
            x_prev = np.zeros(n, dtype=float)

        r_prev = np.where(n_prev > 0.0, x_prev / np.where(n_prev > 0.0, n_prev, 1.0), 0.0)
        n_eff = gamma * np.minimum(n_prev, float(cfg.n_cap))
        k_pop = cfg.k_pop_for(rate_name)

        mu_pop_ok = np.isfinite(mu_pop)
        mu0 = np.where(
            mu_pop_ok,
            (n_eff * r_prev + k_pop * np.where(mu_pop_ok, mu_pop, 0.0)) / (n_eff + k_pop),
            np.where(n_eff > 0.0, r_prev, np.nan),
        )

        # Etapa 2: actualización EWM solo sobre temporada actual
        if rate_name in ewm_e:
            s_x = ewm_x[rate_name].reindex(keys).fillna(0.0).to_numpy(dtype=float)
            s_e = ewm_e[rate_name].reindex(keys).fillna(0.0).to_numpy(dtype=float)
        else:
            s_x = np.zeros(n, dtype=float)
            s_e = np.zeros(n, dtype=float)

        is_newcomer = n_eff <= 0.0
        k_in = np.where(
            is_newcomer,
            cfg.k_in_for(rate_name, newcomer=True),
            cfg.k_in_for(rate_name, newcomer=False),
        )
        mu0_ok = np.isfinite(mu0)
        denom = s_e + k_in
        r_hat = np.where(
            mu0_ok,
            (s_x + k_in * np.where(mu0_ok, mu0, 0.0)) / np.where(denom > 0.0, denom, 1.0),
            np.where(s_e > 0.0, s_x / np.where(s_e > 0.0, s_e, 1.0), np.nan),
        )
        out[rate_name] = r_hat

    # Exposición efectiva informativa (BonusModel no vuelve a encoger con skip_bonus_double_shrink=True)
    prev_n90_s: pd.Series = eb_state["prev_n90"]
    ewm_n90_s: pd.Series = eb_state["ewm_n90_role"]
    n_prev_tot = prev_n90_s.reindex(keys).fillna(0.0).to_numpy(dtype=float) if not prev_n90_s.empty else np.zeros(n)
    n_in_tot = ewm_n90_s.reindex(keys).fillna(0.0).to_numpy(dtype=float) if not ewm_n90_s.empty else np.zeros(n)
    out["n90"] = gamma * np.minimum(n_prev_tot, float(cfg.n_cap)) + n_in_tot
    return out
