"""Ejecutor de Producción en Vivo para el Agente FPL (live_agent_runner.py).

Diseñado para operar en tiempo real durante la temporada de Premier League.
Se conecta a la API oficial de FPL, descarga la información previa al deadline,
ejecuta la inferencia xP y el optimizador MILP, y emite la recomendación oficial.
"""
import sys
import argparse
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mova_data.collectors.fpl import FPLCollector
from src.mova_model.inference import FPLInferenceEngine
from src.mova_model.fpl_optimizer import FPLMILPOptimizer


def run_live_agent(gameweek: int = 1, dry_run: bool = True):
    print(f"🚀 Ejecutando Agente FPL en Modo Producción para la Gameweek {gameweek}...")

    # 1. Actualizar datos en vivo desde la API de FPL
    print("📡 Descargando datos en tiempo real de FPL API...")
    collector = FPLCollector()
    collector.fetch_bootstrap()
    collector.fetch_fixtures()

    # 2. Inferencia xP con el modelo de producción
    print("🧠 Calculando matriz de Expected Points (xP) en tiempo real...")
    inference = FPLInferenceEngine(model_version="latest")
    gw_df = inference.predict_gameweek(gameweek=gameweek)

    # 3. Solucionador MILP de plantilla y alineación óptima
    print("⚙️ Ejecutando optimizador combinatorio MILP (£100M, máx 3 por club)...")
    optimizer = FPLMILPOptimizer(model_version="latest")
    squad_decision = optimizer.solve_initial_squad(gameweek=gameweek, budget=100.0)

    # 4. Generar informe técnico de producción
    output_path = ROOT / "outputs" / f"live_decision_GW{gameweek}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    report_md = f"""# Recomendación Oficial de Alineación y Estrategia — Gameweek {gameweek}

> **Fecha de Invocación:** `{timestamp}`  
> **Modo de Operación:** `{'DRY-RUN (Simulación Producción)' if dry_run else 'LIVE OPERATIONAL'}`  
> **Presupuesto Utilizado:** £{squad_decision['total_cost']}M / £100.0M  

---

## ⚽ 1. 11 Titulares Seleccionados

| Posición | Jugador | Club | Precio | $xP$ Pronosticado | Rol |
| :--- | :--- | :---: | :---: | :---: | :---: |
"""
    for p in squad_decision["starters_11"]:
        role = "⭐ CAPITÁN (2x)" if p["player_id"] == squad_decision["captain"]["player_id"] else "Titular"
        report_md += f"| **{p['position']}** | {p['player_name']} | {p['team_short']} | £{p['price']}M | `{p['xp_final']}` pts | {role} |\n"

    report_md += f"""
---

## 🔄 2. Banco de Suplentes (Orden de Prioridad)

"""
    for idx, p in enumerate(squad_decision["bench_4"], 1):
        report_md += f"{idx}. **[{p['position']}] {p['player_name']}** ({p['team_short']}) — £{p['price']}M | $xP$: `{p['xp_final']}` pts\n"

    report_md += f"""
---

## 📈 3. Resumen Táctico
- **Puntos Esperados Totales (11 + C):** `{squad_decision['expected_points']}` pts
- **Capitán Elegido:** **{squad_decision['captain']['player_name']}** ({squad_decision['captain']['team_short']})
- **Saldo de Caja Restante:** £{squad_decision['budget_remaining']}M
"""

    output_path.write_text(report_md, encoding="utf-8")
    print(f"\n✅ Recomendación oficial generada e inspeccionable en: {output_path}")
    print("\n" + report_md)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ejecutor en vivo del Agente FPL")
    parser.add_argument("--gameweek", type=int, default=1, help="Número de Gameweek a operar")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Ejecutar en modo simulación de producción")
    args = parser.parse_args()

    run_live_agent(gameweek=args.gameweek, dry_run=args.dry_run)
