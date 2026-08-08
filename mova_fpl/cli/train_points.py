"""CLI: entrena el modelo de puntos descompuesto (WP-005).

El entrenamiento usa EXCLUSIVAMENTE temporadas anteriores al holdout. Lo que se
aprende aqui es transversal (factor de definicion, mapeo BPS a bonus, dispersion
defensiva, minutos medios por rama); el estado de cada jugador se calcula en la
proyeccion desde el historico causal de la temporada en curso.
"""
from __future__ import annotations

import argparse
import json

from mova_fpl.data.store import Store
from mova_fpl.models.points import PointsModel
from mova_fpl.models.registry import save


def main() -> None:
    ap = argparse.ArgumentParser(description="Entrena el modelo de puntos por componentes")
    ap.add_argument("--holdout", default="2025-26", help="temporada que NO entra al ajuste")
    ap.add_argument("--version", default="1.0.0")
    args = ap.parse_args()

    store = Store()
    # gw=1 del holdout: por construccion, solo temporadas cerradas anteriores
    df = store.multi_season_as_of(args.holdout, 1)
    print(f"Entrenando con {len(df):,} filas anteriores a {args.holdout} gw1")

    modelo = PointsModel(version=args.version).fit(df)
    meta = modelo.metadata
    print(f"  temporadas       : {', '.join(meta['temporadas'])}")
    print(f"  minutos por rama : parcial {meta['minutos_parcial']} · completo {meta['minutos_completo']}")
    print(f"  definicion (G/xG): {json.dumps({k: round(v, 3) for k, v in modelo.goals.definicion.items()})}")
    print(f"  creacion  (A/xA) : {json.dumps({k: round(v, 3) for k, v in modelo.goals.creacion.items()})}")
    print(f"  bonus            : {modelo.bonus.metadata.get('tramos', 0)} tramos de BPS/90")
    if modelo.defcon.sin_datos:
        print("  defcon           : SIN DATOS en el ajuste — la regla no existia antes de "
              f"{args.holdout}. La dispersion se reestima dentro de la temporada.")
    else:
        print(f"  defcon           : {modelo.defcon.metadata.get('por_posicion')}")

    registro = save(modelo, "points", args.version, {
        "filas_ajuste": meta["filas_ajuste"], "holdout": args.holdout,
        "definicion": modelo.goals.definicion, "creacion": modelo.goals.creacion,
        "defcon_sin_datos": modelo.defcon.sin_datos,
    })
    print(f"\nGuardado: {registro['artifact']} (git {registro['git_sha']})")


if __name__ == "__main__":
    main()
