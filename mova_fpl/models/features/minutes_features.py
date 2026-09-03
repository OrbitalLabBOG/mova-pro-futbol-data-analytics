"""Features del modelo de minutos. Causales por construccion.

Todas se calculan con `shift(1)` dentro del historial del jugador ordenado por
(temporada, jornada, partido): una fila jamas ve su propio resultado ni ninguno
posterior. La agrupacion usa `player_key`, no `element`, porque FPL reasigna los
ids cada temporada (ver data/identity.py).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ORDEN = ["player_key", "season", "gw", "fixture"]

FEATURES = [
    "n_prev", "ewm_min_corto", "ewm_min_largo", "tasa_jugo", "tasa_60",
    "min_anterior", "min_hace_2", "std_min_5", "racha_ceros",
    "tasa_titular", "precio", "es_gk", "es_def", "es_mid", "es_fwd",
    "local", "gw_num", "primera_de_temporada", "temporadas_vistas",
]


def _clase(minutos: pd.Series) -> pd.Series:
    """0 = no jugo · 1 = 1..59 minutos · 2 = 60 o mas."""
    return np.select([minutos <= 0, minutos < 60], [0, 1], default=2)


def build(df: pd.DataFrame) -> pd.DataFrame:
    """Construye la matriz de features y el objetivo.

    `df` debe venir de `Store.as_of` o `Store.multi_season_as_of`: la ventana
    temporal ya esta garantizada aguas arriba.
    """
    d = df.copy()
    d["player_key"] = d["player_key"].fillna("desconocido")
    d = d.sort_values(ORDEN).reset_index(drop=True)

    d["minutos"] = pd.to_numeric(d["minutes"], errors="coerce").fillna(0)
    d["y"] = _clase(d["minutos"])
    d["jugo"] = (d["minutos"] > 0).astype(float)
    d["jugo_60"] = (d["minutos"] >= 60).astype(float)

    g = d.groupby("player_key", sort=False)
    sh = lambda s: s.shift(1)                                    # noqa: E731

    d["n_prev"] = g.cumcount()
    d["ewm_min_corto"] = g["minutos"].transform(lambda s: sh(s).ewm(halflife=2, min_periods=1).mean())
    d["ewm_min_largo"] = g["minutos"].transform(lambda s: sh(s).ewm(halflife=8, min_periods=1).mean())
    d["tasa_jugo"] = g["jugo"].transform(lambda s: sh(s).expanding().mean())
    d["tasa_60"] = g["jugo_60"].transform(lambda s: sh(s).expanding().mean())
    d["min_anterior"] = g["minutos"].transform(sh)
    d["min_hace_2"] = g["minutos"].transform(lambda s: s.shift(2))
    d["std_min_5"] = g["minutos"].transform(lambda s: sh(s).rolling(5, min_periods=2).std())

    # partidos consecutivos sin jugar, contados hasta la fila anterior
    def _racha(s: pd.Series) -> pd.Series:
        # s.shift(1) ya es "el partido anterior": hay que incorporar ese valor
        # ANTES de anotar el conteo, o la racha queda una jornada corta.
        out, n = [], 0
        for v in s.shift(1).fillna(-1):
            n = 0 if v != 0 else n + 1        # v < 0 = sin historial
            out.append(n)
        return pd.Series(out, index=s.index, dtype=float)

    d["racha_ceros"] = g["minutos"].transform(_racha)

    # titularidades: la columna existe desde 2022-23; NaN antes, nunca 0 inventado
    if "starts" in d.columns:
        st = pd.to_numeric(d["starts"], errors="coerce")
        d["tasa_titular"] = st.groupby(d["player_key"], sort=False).transform(
            lambda s: sh(s).expanding().mean())
    else:
        d["tasa_titular"] = np.nan

    d["temporadas_vistas"] = (g["season"].transform(lambda s: sh(s).ne(sh(s).shift()).cumsum())
                              .fillna(0).astype(float))
    d["primera_de_temporada"] = (d["gw"] <= 1).astype(float)

    d["precio"] = pd.to_numeric(d["value"], errors="coerce") / 10.0
    pos = d["position"].astype("string").str.upper()
    for col, val in (("es_gk", "GK"), ("es_def", "DEF"), ("es_mid", "MID"), ("es_fwd", "FWD")):
        d[col] = pos.str.startswith(val).fillna(False).astype(float)
    d["es_gk"] = ((pos == "GK") | (pos == "GKP")).fillna(False).astype(float)

    d["local"] = pd.to_numeric(d["was_home"], errors="coerce").fillna(0.5)
    d["gw_num"] = pd.to_numeric(d["gw"], errors="coerce")

    return d


def matrix(d: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    return d[FEATURES].astype(float), d["y"].astype(int)


def build_targets(history: pd.DataFrame, targets: pd.DataFrame) -> pd.DataFrame:
    """Construye solo las filas objetivo con el mismo estado que :func:`build`.

    ``build`` sigue siendo la vía de entrenamiento fila a fila. En producción y
    replay no tiene sentido materializar features para todo el pasado en cada
    deadline: basta resumir el histórico causal y anexar los atributos del
    catálogo objetivo. Esta función es algebraicamente equivalente para una
    fila objetivo por jugador.
    """
    target = targets.copy().reset_index(drop=True)
    target["player_key"] = target["player_key"].fillna("desconocido")

    if history.empty:
        state = pd.DataFrame(index=pd.Index([], name="player_key"))
    else:
        d = history.copy()
        d["player_key"] = d["player_key"].fillna("desconocido")
        d = d.sort_values(ORDEN).reset_index(drop=True)
        d["minutos"] = pd.to_numeric(d["minutes"], errors="coerce").fillna(0.0)
        d["jugo"] = (d["minutos"] > 0).astype(float)
        d["jugo_60"] = (d["minutos"] >= 60).astype(float)
        if "starts" in d:
            d["titular"] = pd.to_numeric(d["starts"], errors="coerce")
        else:
            d["titular"] = np.nan

        def previous_two(values: pd.Series):
            return float(values.iloc[-2]) if len(values) >= 2 else np.nan

        def zero_streak(values: pd.Series) -> float:
            count = 0
            for value in reversed(values.to_numpy(dtype=float)):
                if value != 0:
                    break
                count += 1
            return float(count)

        grouped = d.groupby("player_key", sort=False)
        state = grouped.agg(
            n_prev=("minutos", "size"),
            tasa_jugo=("jugo", "mean"),
            tasa_60=("jugo_60", "mean"),
            min_anterior=("minutos", "last"),
            min_hace_2=("minutos", previous_two),
            std_min_5=("minutos", lambda values: values.tail(5).std()),
            racha_ceros=("minutos", zero_streak),
            tasa_titular=("titular", "mean"),
            temporadas_vistas=("season", "nunique"),
        )
        state["ewm_min_corto"] = grouped["minutos"].agg(
            lambda values: values.ewm(halflife=2, min_periods=1).mean().iloc[-1])
        state["ewm_min_largo"] = grouped["minutos"].agg(
            lambda values: values.ewm(halflife=8, min_periods=1).mean().iloc[-1])

    out = state.reindex(target["player_key"].to_numpy()).reset_index(drop=True)
    historical = (
        "n_prev", "ewm_min_corto", "ewm_min_largo", "tasa_jugo", "tasa_60",
        "min_anterior", "min_hace_2", "std_min_5", "racha_ceros",
        "tasa_titular", "temporadas_vistas",
    )
    for column in historical:
        if column not in out:
            out[column] = np.nan
    out["n_prev"] = out.get("n_prev", pd.Series(index=out.index, dtype=float)).fillna(0.0)
    out["racha_ceros"] = out.get(
        "racha_ceros", pd.Series(index=out.index, dtype=float)).fillna(0.0)
    out["temporadas_vistas"] = out.get(
        "temporadas_vistas", pd.Series(index=out.index, dtype=float)).fillna(0.0)
    out["primera_de_temporada"] = (
        pd.to_numeric(target["gw"], errors="coerce") <= 1).astype(float)
    out["precio"] = pd.to_numeric(target["value"], errors="coerce") / 10.0
    pos = target["position"].astype("string").str.upper()
    out["es_gk"] = ((pos == "GK") | (pos == "GKP")).fillna(False).astype(float)
    out["es_def"] = pos.str.startswith("DEF").fillna(False).astype(float)
    out["es_mid"] = pos.str.startswith("MID").fillna(False).astype(float)
    out["es_fwd"] = pos.str.startswith("FWD").fillna(False).astype(float)
    out["local"] = pd.to_numeric(target["was_home"], errors="coerce").fillna(0.5)
    out["gw_num"] = pd.to_numeric(target["gw"], errors="coerce")
    out["element"] = target["element"].to_numpy()
    out["player_key"] = target["player_key"].to_numpy()
    out["y"] = 0
    out["_objetivo"] = True
    return out
