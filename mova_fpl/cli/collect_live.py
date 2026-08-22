"""Captura inmutable del estado oficial de FPL antes del deadline.

No introduce una segunda primitiva de red: reutiliza exclusivamente los GET de
``data.sources``. El snapshot permite que investigacion, modelos y acta final
consuman exactamente los mismos bytes aunque la API cambie entre pasos.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from mova_fpl.data.snapshot import ROOT, collect, load_snapshot, validate


def main() -> None:
    ap = argparse.ArgumentParser(description="Snapshot inmutable de la API oficial FPL")
    ap.add_argument("--season", default="2026-27")
    ap.add_argument("--gw", type=int, required=True)
    ap.add_argument("--out-root", type=Path, default=ROOT / "data/raw/fpl_live")
    args = ap.parse_args()
    dest, manifest = collect(args.season, args.gw, args.out_root)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"snapshot={dest}")


if __name__ == "__main__":
    main()
