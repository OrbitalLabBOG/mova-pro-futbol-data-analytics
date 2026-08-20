"""CLI: entrena, evalua y registra el modelo de minutos."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from mova_fpl.data.schema import SEASONS
from mova_fpl.data.store import Store
from mova_fpl.models.minutes import MinutesModel
from mova_fpl.models.registry import save
from mova_fpl.trace.writer import DEFAULT_TRACE, TraceWriter


def registrar(registro: dict, db: Path = DEFAULT_TRACE) -> None:
    TraceWriter(db)                                     # asegura el esquema
    with sqlite3.connect(db) as con:
        con.execute(
            """INSERT OR REPLACE INTO model_versions
               (name, version, git_sha, trained_at, train_rows, metrics)
               VALUES (?,?,?,?,?,?)""",
            (registro["name"], registro["version"], registro["git_sha"],
             registro["trained_at"], registro["train_rows"],
             json.dumps(registro["metrics"], ensure_ascii=False, default=str)))


def main() -> None:
    ap = argparse.ArgumentParser(description="Modelo de minutos FPL")
    ap.add_argument("--holdout", default="2025-26", help="temporada de evaluacion, no vista")
    ap.add_argument("--version", default="1.0.0")
    ap.add_argument(
        "--production",
        action="store_true",
        help="ajusta para produccion usando todo el historico hasta --holdout; "
             "la ultima temporada se reserva para calibracion, no para evaluacion",
    )
    ap.add_argument("--no-calibrar", action="store_true")
    ap.add_argument("--out", help="reporte de calibracion en Markdown")
    args = ap.parse_args()

    if args.holdout not in SEASONS:
        raise SystemExit(f"temporada invalida: {args.holdout}")

    corte = SEASONS.index(args.holdout)
    train_seasons = SEASONS[:corte]
    if len(train_seasons) < 2:
        raise SystemExit("hacen falta al menos dos temporadas para entrenar y calibrar")
    calib = args.holdout if args.production else train_seasons[-1]

    store = Store()
    if args.production:
        # Para operar la temporada siguiente, la ultima temporada cerrada calibra
        # temporalmente el modelo. No se publican metricas held-out falsas: la
        # evidencia de generalizacion sigue siendo la version benchmark.
        entrena = store.multi_season_as_of(args.holdout, 39)
        evalua = None
        train_seasons = SEASONS[: corte + 1]
    else:
        # el holdout se lee con as_of(gw=1) sobre su temporada => cero filas de esa
        # temporada entran al entrenamiento. La ventana la garantiza el almacen.
        entrena = store.multi_season_as_of(args.holdout, 1)
        evalua = store.multi_season_as_of(args.holdout, 39)
        evalua = evalua[evalua["season"] == args.holdout]

    print(f"Entrenamiento: {', '.join(train_seasons)}  ({len(entrena):,} filas)")
    print(f"Calibracion:   {calib} (temporal, reservada del ajuste base)")
    if evalua is None:
        print("Held-out:      ninguno — artefacto de produccion; usar benchmark separado\n")
    else:
        print(f"Held-out:      {args.holdout}  ({len(evalua):,} filas)\n")

    modelo = MinutesModel(version=args.version, calibrar=not args.no_calibrar)
    modelo.fit(entrena, calib_season=calib)
    if evalua is None:
        m = {
            "mode": "production",
            "fit_through": args.holdout,
            "calib_season": calib,
            "held_out_metrics": False,
        }
    else:
        m = modelo.evaluate(evalua)
        m["mode"] = "benchmark"
        m["holdout"] = args.holdout
        print(f"  ECE  P(60+)   modelo {m['ece_p60']:.4f}   baseline {m['ece_p60_baseline']:.4f}")
        print(f"  Brier P(60+)  modelo {m['brier_p60']:.4f}   baseline {m['brier_p60_baseline']:.4f}")
        print(f"  Log-loss 3 clases: {m['log_loss_3c']:.4f}")
        print(f"\n{m['tabla_calibracion'].to_string(index=False)}")

    registro = save(modelo, "minutes", args.version, m)
    registrar(registro)
    print(f"\n  artefacto: {registro['artifact']}  ·  git {registro['git_sha']}")

    if args.out and evalua is not None:
        t = m["tabla_calibracion"]
        txt = [f"# Modelo de minutos v{args.version} — calibracion", "",
               f"Entrenado con {', '.join(train_seasons)} · calibrado en {calib} · "
               f"evaluado a ciegas en {args.holdout}", "",
               f"| Metrica | Modelo | Baseline (frecuencia del jugador) |", "|---|---:|---:|",
               f"| ECE de P(60+) | **{m['ece_p60']:.4f}** | {m['ece_p60_baseline']:.4f} |",
               f"| Brier de P(60+) | **{m['brier_p60']:.4f}** | {m['brier_p60_baseline']:.4f} |",
               f"| Log-loss 3 clases | {m['log_loss_3c']:.4f} | — |", "",
               f"Filas evaluadas: {m['n']:,} · artefacto `{registro['artifact']}` · git `{registro['git_sha']}`",
               "", "## Curva de calibracion — P(60+)", "",
               "| Bin | n | Predicho | Observado |", "|---|---:|---:|---:|"]
        for _, r in t.iterrows():
            if r["n"]:
                txt.append(f"| {r['bin']} | {int(r['n']):,} | {r['predicho']:.3f} | {r['observado']:.3f} |")
        Path(args.out).write_text("\n".join(txt) + "\n", encoding="utf-8")
        print(f"  reporte: {args.out}")
    elif args.out:
        txt = [f"# Modelo de minutos v{args.version} — produccion", "",
               f"Ajustado con {', '.join(train_seasons)}.",
               f"Calibracion temporal: {calib}.",
               "No se reportan metricas held-out para este artefacto; consultar la version benchmark.", "",
               f"Artefacto `{registro['artifact']}` · SHA-256 `{registro['artifact_sha256']}` · git `{registro['git_sha']}`", ""]
        Path(args.out).write_text("\n".join(txt), encoding="utf-8")
        print(f"  reporte: {args.out}")


if __name__ == "__main__":
    main()
