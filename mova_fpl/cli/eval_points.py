"""CLI: evaluacion del modelo de puntos por componente (WP-005).

Recorre una ventana temporal de la temporada, proyecta con informacion causal y
contrasta cada componente contra lo que de verdad ocurrio. Un total que cuadra
puede esconder dos componentes que se compensan; por eso se mide uno por uno.
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from mova_fpl.data.store import Store
from mova_fpl.engine.projection import _proba_minutos
from mova_fpl.models.defcon import evaluate as eval_defcon
from mova_fpl.models.minutes import calibration_table, expected_calibration_error
from mova_fpl.models.points import COMPONENTES
from mova_fpl.models.registry import load
from mova_fpl.rules import get as get_rules
from mova_fpl.rules.base import Position

#: puntos realmente obtenidos por componente, calculados desde el resultado
def componentes_reales(res: pd.DataFrame, scoring) -> pd.DataFrame:
    d = res[pd.to_numeric(res["minutes"], errors="coerce").fillna(0) > 0].copy()
    if d.empty:
        return pd.DataFrame()
    pos = d["position"].astype("string").str.upper().replace({"GK": "GKP"}).map(Position.parse)
    num = lambda c: pd.to_numeric(d.get(c), errors="coerce").fillna(0.0)   # noqa: E731

    atras = pos.isin([Position.GKP, Position.DEF]).to_numpy()
    umbral = pos.map(lambda p: scoring.defcon_thresholds.get(p, 0)).to_numpy(dtype=float)
    dc = num("defensive_contribution").to_numpy()

    out = pd.DataFrame({
        "element": d["element"].to_numpy(),
        "pts_aparicion": np.where(num("minutes") >= scoring.minutes_for_long,
                                  scoring.appearance_long, scoring.appearance_short),
        "pts_goles": num("goals_scored") * pos.map(lambda p: scoring.goal_points.get(p, 4)),
        "pts_asistencias": num("assists") * scoring.assist_points,
        "pts_cs": num("clean_sheets") * pos.map(lambda p: scoring.clean_sheet_points.get(p, 0)),
        "pts_encajados": -(num("goals_conceded") // 2) * atras,
        "pts_defcon": np.where((umbral > 0) & (dc >= umbral), scoring.defcon_points, 0.0),
        "pts_bonus": num("bonus"),
        "pts_tarjetas": (num("yellow_cards") * scoring.yellow_card_points
                         + num("red_cards") * scoring.red_card_points),
        "pts_paradas": num("saves") // scoring.saves_per_point,
        "pts_otros": (num("penalties_saved") * scoring.penalty_save_points
                      + num("own_goals") * scoring.own_goal_points),
        "total_real": num("total_points"),
    })
    return out.groupby("element", as_index=False).sum()      # colapsa dobles jornadas


def main() -> None:
    ap = argparse.ArgumentParser(description="Evalua el modelo de puntos por componente")
    ap.add_argument("--season", default="2025-26")
    ap.add_argument("--desde", type=int, default=20, help="primera jornada de la ventana")
    ap.add_argument("--hasta", type=int, default=38)
    ap.add_argument("--version", default="1.0.0")
    ap.add_argument("--out")
    args = ap.parse_args()

    store = Store()
    scoring = get_rules(args.season).SCORING
    modelos = {"minutes": load("minutes", "1.0.0"), "points": load("points", args.version)}

    proyectado, realizado, ventana = [], [], []
    for gw in range(args.desde, args.hasta + 1):
        hist, roster = store.as_of(args.season, gw), store.roster(args.season, gw)
        res = store.results(args.season, gw)
        if roster.empty or res.empty:
            continue
        p = _proba_minutos(hist, roster, modelos["minutes"])
        pred = modelos["points"].project(hist, roster, p, scoring, scoring.defcon_thresholds)
        pred["gw"] = gw
        proyectado.append(pred)
        real = componentes_reales(res, scoring)
        real["gw"] = gw
        realizado.append(real)
        ventana.append((hist, res))
        print(f"  GW{gw:>2}  {len(pred):>3} proyectados · {len(real):>3} con minutos", flush=True)

    pred = pd.concat(proyectado, ignore_index=True)
    real = pd.concat(realizado, ignore_index=True)
    j = pred.merge(real, on=["element", "gw"], suffixes=("_pred", "_real"), how="left").fillna(0.0)

    lineas = [f"# WP-005 · Evaluacion por componente · {args.season} GW{args.desde}-{args.hasta}", "",
              f"Proyecciones: {len(pred):,} · con minutos jugados: {int((j['total_real'] > 0).sum()):,}", "",
              "## Calibracion por componente", "",
              "| Componente | Predicho (total) | Real (total) | Sesgo | Sesgo relativo |",
              "|---|---:|---:|---:|---:|"]
    for c in COMPONENTES:
        p_, r_ = float(j[f"{c}_pred"].sum()), float(j[f"{c}_real"].sum())
        rel = (p_ - r_) / abs(r_) * 100 if r_ else float("nan")
        rel_txt = "—" if rel != rel else f"{rel:+.1f}%"
        lineas.append(f"| `{c}` | {p_:,.0f} | {r_:,.0f} | {p_ - r_:+,.0f} | {rel_txt} |")
    tp, tr = float(j["xp"].sum()), float(j["total_real"].sum())
    lineas.append(f"| **total** | **{tp:,.0f}** | **{tr:,.0f}** | **{tp - tr:+,.0f}** | "
                  f"**{100*(tp-tr)/tr:+.1f}%** |")

    corr = float(j["xp"].corr(j["total_real"]))
    lineas += ["", f"Correlacion xP con puntos reales: **{corr:.3f}** "
                   f"(por jugador-jornada, {len(j):,} pares).", ""]

    umbrales = scoring.defcon_thresholds
    dc = eval_defcon(modelos["points"].defcon, ventana, umbrales)
    if dc.get("n"):
        lineas += ["## Calibracion de la contribucion defensiva (AC-WP005-004)", "",
                   f"ECE global **{dc['ece']:.4f}** (umbral 0,08) · Brier {dc['brier']:.4f} · "
                   f"tasa base {dc['tasa_base']:.3f} · n = {dc['n']:,}", "",
                   "| Posicion | n | ECE | Predicho | Observado |", "|---|---:|---:|---:|---:|"]
        for p, s in dc["por_posicion"].items():
            lineas.append(f"| {p} | {s['n']:,} | {s['ece']:.4f} | {s['predicho']:.3f} | "
                          f"{s['observado']:.3f} |")
        lineas += ["", "### Curva de calibracion", "",
                   "| Bin | n | Predicho | Observado |", "|---|---:|---:|---:|"]
        for _, r in dc["tabla"].iterrows():
            if r["n"]:
                lineas.append(f"| {r['bin']} | {int(r['n']):,} | {r['predicho']:.3f} | "
                              f"{r['observado']:.3f} |")
        print(f"\nDefCon: ECE {dc['ece']:.4f} · Brier {dc['brier']:.4f} · n {dc['n']:,}")

    # AC-WP005-006: el bonus va aparte porque su sesgo para 2026/27 es conocido
    bp, br = float(j["pts_bonus_pred"].sum()), float(j["pts_bonus_real"].sum())
    lineas += ["", "## Componente de bonus, reportado por separado (AC-WP005-006)", "",
               f"| | Predicho | Real |", "|---|---:|---:|",
               f"| Puntos de bonus | {bp:,.0f} | {br:,.0f} |",
               f"| Cuota del xP total | {100*bp/tp:.1f}% | {100*br/tr:.1f}% |", "",
               "El bonus se aisla porque su sesgo para 2026/27 esta identificado y no medido "
               "(R-04): el BPS cambia en cuatro reglas y la que mas pesa —CBI pasa de 1 punto "
               "por cada 2 acciones a 1 por cada 3— rebaja el BPS de defensas y porteros. "
               "El componente queda **sobreestimado para esas dos posiciones** en 2026/27, y "
               "esa parte del xP es la unica que hay que descontar mentalmente.", ""]

    y = (j["total_real"] > 0).astype(float).to_numpy()
    pj = np.clip(j["p_juega"].to_numpy(dtype=float), 0, 1)
    lineas += ["## Probabilidad de jugar (heredada de WP-004)", "",
               f"ECE de P(juega) sobre esta ventana: **{expected_calibration_error(y, pj):.4f}**", "",
               "| Bin | n | Predicho | Observado |", "|---|---:|---:|---:|"]
    for _, r in calibration_table(y, pj).iterrows():
        if r["n"]:
            lineas.append(f"| {r['bin']} | {int(r['n']):,} | {r['predicho']:.3f} | "
                          f"{r['observado']:.3f} |")

    texto = "\n".join(lineas) + "\n"
    print("\n" + "\n".join(lineas[:20]))
    if args.out:
        from pathlib import Path
        Path(args.out).write_text(texto, encoding="utf-8")
        print(f"\nInforme: {args.out}")


if __name__ == "__main__":
    main()
