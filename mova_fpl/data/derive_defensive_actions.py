"""Deriva el conteo defensivo desde eventos Opta y lo contrasta con el CSV (AC-WP005-003).

Por que hace falta
------------------
La columna `defensive_contribution` del almacen viene del CSV de FPL y es la que
alimenta al modelo. Si esa columna estuviera mal, todo el componente defensivo
—que es la ventaja competitiva que persigue el proyecto— estaria construido
sobre arena. Aqui se reconstruye el conteo desde los eventos crudos de 291
partidos de 2025/26 y se mide cuanto concuerda.

El punto no es sustituir la columna: es saber si se puede confiar en ella, y
caracterizar en que casos no.

La correspondencia de eventos
-----------------------------
FPL cuenta, segun la posicion:

    DEF        CBIT   = despejes + bloqueos + intercepciones + entradas
    MID / FWD  CBIRT  = lo anterior + recuperaciones

Opta via WhoScored no expone una categoria "bloqueo" limpia: hay `BlockedPass`,
que es un pase interceptado con el cuerpo, y los remates bloqueados aparecen
anotados sobre el rematador. Por eso se evaluan VARIANTES de correspondencia y
se reporta cual concuerda mejor, en vez de asumir una y llamarla verdad.
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pandas as pd

from mova_fpl.data.identity import player_key
from mova_fpl.data.store import DEFAULT_DB, Store

MUNDIAL_DB = Path(__file__).resolve().parents[2] / "data" / "mundial.db"

#: variantes de correspondencia entre eventos Opta y el conteo de FPL
VARIANTES = {
    "estricta": {"cbit": ("Clearance", "Interception", "Tackle"),
                 "extra_cbirt": ("BallRecovery",)},
    "con_bloqueos": {"cbit": ("Clearance", "Interception", "Tackle", "BlockedPass"),
                     "extra_cbirt": ("BallRecovery",)},
    "entradas_ganadas": {"cbit": ("Clearance", "Interception", "BlockedPass"),
                         "extra_cbirt": ("BallRecovery",), "solo_exitosas": ("Tackle",)},
}


def eventos_defensivos(db: Path = MUNDIAL_DB) -> pd.DataFrame:
    """Conteo por partido, jugador y tipo de evento. Solo Premier League 2025/26."""
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as con:
        ev = pd.read_sql_query(
            """SELECT e.match_id, e.player_name, e.team_name, e.event_type, e.outcome,
                      COUNT(*) AS n
               FROM events e
               JOIN matches m ON m.match_id = e.match_id
               WHERE m.competition LIKE 'Premier League%'
                 AND e.player_name IS NOT NULL
                 AND e.event_type IN ('Clearance','Interception','Tackle','BallRecovery','BlockedPass')
               GROUP BY 1,2,3,4,5""", con)
        partidos = pd.read_sql_query(
            """SELECT match_id, start_utc, home_team, away_team FROM matches
               WHERE competition LIKE 'Premier League%'""", con)
    return ev, partidos


def conteo_por_variante(ev: pd.DataFrame, variante: dict) -> pd.DataFrame:
    """Aplica una correspondencia y devuelve cbit / cbirt por jugador-partido."""
    solo_ok = set(variante.get("solo_exitosas", ()))
    d = ev[~ev["event_type"].isin(solo_ok) | (ev["outcome"] == "Successful")]

    base = d[d["event_type"].isin(variante["cbit"]) | d["event_type"].isin(solo_ok)]
    extra = d[d["event_type"].isin(variante["extra_cbirt"])]
    llave = ["match_id", "player_name", "team_name"]
    cbit = base.groupby(llave)["n"].sum().rename("cbit")
    rec = extra.groupby(llave)["n"].sum().rename("recuperaciones")
    out = pd.concat([cbit, rec], axis=1).fillna(0.0).reset_index()
    out["cbirt"] = out["cbit"] + out["recuperaciones"]
    return out


def _fecha(serie: pd.Series) -> pd.Series:
    return pd.to_datetime(serie, format="%d/%m/%Y", errors="coerce").dt.date


def empareja(conteo: pd.DataFrame, partidos: pd.DataFrame, fpl: pd.DataFrame) -> pd.DataFrame:
    """Cruza jugador-partido de Opta con jugador-jornada de FPL.

    El cruce es por FECHA y CLUB, no por identificadores: las dos fuentes no
    comparten ninguno. La identidad del jugador usa la misma normalizacion que
    el resto del paquete (`data/identity.player_key`).
    """
    partidos = partidos.copy()
    partidos["fecha"] = _fecha(partidos["start_utc"])
    conteo = conteo.merge(partidos[["match_id", "fecha", "home_team", "away_team"]],
                          on="match_id", how="left")
    conteo["clave"] = conteo["player_name"].map(player_key)

    f = fpl.copy()
    f["fecha"] = pd.to_datetime(f["kickoff_time"], errors="coerce", utc=True).dt.date
    f["clave"] = f["player_key"]

    return conteo.merge(f, on=["fecha", "clave"], how="inner", suffixes=("_opta", "_fpl"))


def concordancia(cruce: pd.DataFrame) -> dict:
    """Cuanto coincide el conteo derivado con el del CSV, por posicion."""
    d = cruce[cruce["minutes"] > 0].copy()
    if d.empty:
        return {"n": 0}
    pos = d["position"].astype("string").str.upper().replace({"GK": "GKP"})
    d["derivado"] = d["cbirt"].where(pos.isin(["MID", "FWD"]), d["cbit"])
    d["dif"] = d["derivado"] - d["defensive_contribution"]

    salida = {"n": int(len(d)),
              "exacto": float((d["dif"] == 0).mean()),
              "±1": float((d["dif"].abs() <= 1).mean()),
              "±2": float((d["dif"].abs() <= 2).mean()),
              "sesgo_medio": float(d["dif"].mean()),
              "correlacion": float(d["derivado"].corr(d["defensive_contribution"]))}
    salida["por_posicion"] = {
        p: {"n": int(len(s)), "exacto": float((s["dif"] == 0).mean()),
            "±1": float((s["dif"].abs() <= 1).mean()),
            "sesgo": float(s["dif"].mean())}
        for p, s in d.groupby(pos.to_numpy()) if len(s) > 50}
    return salida


def por_componente(ev: pd.DataFrame, partidos: pd.DataFrame, fpl: pd.DataFrame) -> pd.DataFrame:
    """Contrasta cada evento Opta contra su columna equivalente del CSV.

    Es el diagnostico que localiza la discrepancia. Comparar solo el total dice
    QUE no cuadra; comparar componente a componente dice DONDE.
    """
    llave = ["match_id", "player_name", "team_name"]
    piv = (ev.pivot_table(index=llave, columns="event_type", values="n", aggfunc="sum")
           .fillna(0.0).reset_index())
    for c in ("Clearance", "Interception", "Tackle", "BallRecovery", "BlockedPass"):
        if c not in piv.columns:
            piv[c] = 0.0
    d = empareja(piv, partidos, fpl)
    d = d[d["minutes"] > 0]
    if d.empty:
        return pd.DataFrame()

    d = d.assign(ci=d["Clearance"] + d["Interception"])
    pares = [
        ("Tackle", "tackles", d["Tackle"], d["tackles"]),
        ("BallRecovery", "recoveries", d["BallRecovery"], d["recoveries"]),
        ("Clearance + Interception", "clearances_blocks_interceptions",
         d["ci"], d["clearances_blocks_interceptions"]),
    ]
    filas = []
    for nombre, col, a, b in pares:
        a, b = pd.to_numeric(a, errors="coerce"), pd.to_numeric(b, errors="coerce")
        filas.append({"opta": nombre, "csv": col, "n": int(len(d)),
                      "exacto": float((a == b).mean()), "±1": float((a - b).abs().mean() <= 1)
                      if False else float(((a - b).abs() <= 1).mean()),
                      "media_opta": float(a.mean()), "media_csv": float(b.mean()),
                      "correlacion": float(a.corr(b))})

    # el residuo de CBI son los BLOQUEOS, que Opta no expone como evento propio
    implicito = pd.to_numeric(d["clearances_blocks_interceptions"], errors="coerce") - d["ci"]
    filas.append({"opta": "bloqueos implicitos (CBI − C − I)", "csv": "—", "n": int(len(d)),
                  "exacto": float("nan"), "±1": float("nan"),
                  "media_opta": float(d["BlockedPass"].mean()), "media_csv": float(implicito.mean()),
                  "correlacion": float(d["BlockedPass"].corr(implicito))})
    return pd.DataFrame(filas)


def main() -> None:
    ap = argparse.ArgumentParser(description="Deriva conteo defensivo desde eventos Opta")
    ap.add_argument("--season", default="2025-26")
    ap.add_argument("--out", help="escribir el informe en Markdown")
    args = ap.parse_args()

    if not MUNDIAL_DB.exists():
        raise SystemExit(f"no existe {MUNDIAL_DB}: no hay eventos Opta que derivar")

    ev, partidos = eventos_defensivos()
    print(f"Eventos defensivos: {int(ev['n'].sum()):,} en {ev['match_id'].nunique()} partidos")

    with sqlite3.connect(f"file:{DEFAULT_DB}?mode=ro", uri=True) as con:
        fpl = pd.read_sql_query(
            """SELECT season, gw, element, player_key, name, position, team, minutes,
                      kickoff_time, defensive_contribution, clearances_blocks_interceptions,
                      recoveries, tackles
               FROM player_gameweek WHERE season = ? AND defensive_contribution IS NOT NULL""",
            con, params=(args.season,))
    print(f"Filas FPL con conteo defensivo: {len(fpl):,}")

    lineas = [f"# WP-005 · Conteo defensivo derivado de Opta contra el CSV de FPL", "",
              f"**Temporada:** {args.season} · **Partidos con eventos:** "
              f"{ev['match_id'].nunique()} de 380 · **Eventos:** {int(ev['n'].sum()):,}", "",
              "## Concordancia por variante de correspondencia", "",
              "| Variante | Pares | Exacto | ±1 | ±2 | Sesgo medio | Correlación |",
              "|---|---:|---:|---:|---:|---:|---:|"]

    resultados = {}
    for nombre, variante in VARIANTES.items():
        cruce = empareja(conteo_por_variante(ev, variante), partidos, fpl)
        r = concordancia(cruce)
        resultados[nombre] = r
        if r["n"]:
            lineas.append(f"| `{nombre}` | {r['n']:,} | {100*r['exacto']:.1f}% | "
                          f"{100*r['±1']:.1f}% | {100*r['±2']:.1f}% | {r['sesgo_medio']:+.2f} | "
                          f"{r['correlacion']:.3f} |")
        print(f"  {nombre:18s} n={r.get('n',0):>6,}  exacto={100*r.get('exacto',0):5.1f}%  "
              f"±1={100*r.get('±1',0):5.1f}%  sesgo={r.get('sesgo_medio',0):+.2f}")

    mejor = max(resultados, key=lambda k: resultados[k].get("±1", 0))
    lineas += ["", f"Mejor correspondencia: **`{mejor}`**.", "",
               "## Desglose por posición de la mejor variante", "",
               "| Posición | Pares | Exacto | ±1 | Sesgo |", "|---|---:|---:|---:|---:|"]
    for p, s in resultados[mejor].get("por_posicion", {}).items():
        lineas.append(f"| {p} | {s['n']:,} | {100*s['exacto']:.1f}% | {100*s['±1']:.1f}% | "
                      f"{s['sesgo']:+.2f} |")

    comp = por_componente(ev, partidos, fpl)
    if not comp.empty:
        lineas += ["", "## Dónde está la discrepancia", "",
                   "| Evento Opta | Columna del CSV | Exacto | ±1 | Media Opta | Media CSV | Corr. |",
                   "|---|---|---:|---:|---:|---:|---:|"]
        for _, r in comp.iterrows():
            ex = "—" if r["exacto"] != r["exacto"] else f"{100*r['exacto']:.1f}%"
            u1 = "—" if r["±1"] != r["±1"] else f"{100*r['±1']:.1f}%"
            lineas.append(f"| {r['opta']} | `{r['csv']}` | {ex} | {u1} | {r['media_opta']:.2f} | "
                          f"{r['media_csv']:.2f} | {r['correlacion']:.3f} |")
        print("\n" + comp.to_string(index=False))

    if args.out:
        Path(args.out).write_text("\n".join(lineas) + "\n", encoding="utf-8")
        print(f"\nInforme: {args.out}")


if __name__ == "__main__":
    main()
