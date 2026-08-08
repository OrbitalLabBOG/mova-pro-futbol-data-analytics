"""Reporte de cobertura: que columnas existen en que temporada (REQ-F-001)."""
from __future__ import annotations

import argparse

from mova_fpl.data.store import Store


def render(store: Store) -> str:
    cov = store.coverage()
    filas = cov["filas"]
    lines = ["# Cobertura del almacen canonico FPL", ""]
    lines.append(f"Filas totales: {int(filas.sum()):,} en {len(cov)} temporadas")
    lines.append("")
    header = "| columna | " + " | ".join(s[2:] for s in cov.index) + " |"
    lines += [header, "|" + "---|" * (len(cov) + 1)]
    lines.append("| **filas** | " + " | ".join(f"{int(v):,}" for v in filas) + " |")
    for col in cov.columns:
        if col == "filas":
            continue
        cells = []
        for season in cov.index:
            n, tot = int(cov.loc[season, col]), int(filas[season])
            cells.append("·" if n == 0 else ("X" if n == tot else f"{100*n//tot}%"))
        if set(cells) == {"·"}:
            continue
        lines.append(f"| {col} | " + " | ".join(cells) + " |")
    lines += ["", "`X` = presente en todas las filas · `·` = ausente (NULL, nunca 0) · `n%` = parcial"]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Matriz de cobertura por temporada")
    ap.add_argument("--out", help="escribir a archivo")
    args = ap.parse_args()
    text = render(Store())
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"escrito en {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
