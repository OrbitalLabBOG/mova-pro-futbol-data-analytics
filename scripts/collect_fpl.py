"""CLI principal para recolección e ingesta de datos Fantasy Premier League (FPL API)."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mova_data.collectors.fpl import FPLCollector
from src.mova_data.loaders.fpl_loader import (
    load_fpl_bootstrap,
    load_fpl_fixtures,
    load_fpl_player_summary,
)
from src.mova_data.db import init_db, DB_PATH


def main():
    parser = argparse.ArgumentParser(description="Colector idempotente de Fantasy Premier League")
    parser.add_argument("--bootstrap", action="store_true", help="Descargar y cargar bootstrap-static")
    parser.add_argument("--fixtures", action="store_true", help="Descargar y cargar fixtures FPL")
    parser.add_argument("--players", action="store_true", help="Descargar y cargar historial de todos los jugadores")
    parser.add_argument("--all", action="store_true", help="Ejecutar recolección y carga completa")
    parser.add_argument("--force", action="store_true", help="Forzar re-descarga omitiendo caché")
    args = parser.parse_args()

    init_db(DB_PATH)
    collector = FPLCollector()

    run_all = args.all or (not args.bootstrap and not args.fixtures and not args.players)

    if args.bootstrap or run_all:
        print("📥 Descargando FPL bootstrap-static...")
        b_path = collector.fetch_bootstrap(force=args.force)
        counts = load_fpl_bootstrap(b_path, DB_PATH)
        print(f"  ✓ Cargados en DB: {counts['teams']} equipos, {counts['players']} jugadores, {counts['gameweeks']} gameweeks.")

    if args.fixtures or run_all:
        print("📥 Descargando FPL fixtures...")
        f_path = collector.fetch_fixtures(force=args.force)
        n_fx = load_fpl_fixtures(f_path, DB_PATH)
        print(f"  ✓ Cargados en DB: {n_fx} fixtures FPL.")

    if args.players or run_all:
        print("📥 Descargando historial de jugadores FPL...")
        b_path = collector.fetch_bootstrap()
        import json
        with open(b_path, encoding="utf-8") as f:
            data = json.load(f)
        players = data.get("elements", [])
        total_history = 0
        for i, p in enumerate(players, 1):
            p_id = p["id"]
            p_path = collector.fetch_player_summary(p_id, force=args.force)
            n_hist = load_fpl_player_summary(p_path, p_id, DB_PATH)
            total_history += n_hist
            if i % 100 == 0 or i == len(players):
                print(f"  Progreso: {i}/{len(players)} jugadores procesados ({total_history} registros)...")
        print(f"  ✓ {len(players)} jugadores procesados, {total_history} registros de historial cargados en DB.")

    print("🎉 Ingesta FPL completada exitosamente.")


if __name__ == "__main__":
    main()
