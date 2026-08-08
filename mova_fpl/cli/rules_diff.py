"""CLI: diff entre versiones de reglas. Aqui si se permite escribir ficheros."""
from __future__ import annotations

import argparse

from mova_fpl.rules.diff import render


def main() -> None:
    ap = argparse.ArgumentParser(description="Diff entre versiones de reglas FPL")
    ap.add_argument("--from", dest="a", default="2025-26")
    ap.add_argument("--to", dest="b", default="2026-27")
    ap.add_argument("--out")
    args = ap.parse_args()
    text = render(args.a, args.b)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"escrito en {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
