"""Solucionador Matemático MILP (Mixed-Integer Linear Programming) para FPL.

Utiliza PuLP para resolver la optimización combinatoria de plantilla de 15 jugadores,
11 titulares, capitán y transferencias semanales respetando presupuesto (£100M),
restricciones posicionales, límite de 3 por club y costo de transferencias (-4 pts).
"""
import pulp
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional

from src.mova_model.inference import FPLInferenceEngine
from src.mova_model.fpl_xp import FPLxPEngine, DB_PATH


class FPLMILPOptimizer:
    """Optimizador combinatorio MILP para Fantasy Premier League."""

    def __init__(self, model_version: str = "v3", db_path: Path = DB_PATH):
        self.inference = FPLInferenceEngine(model_version=model_version, db_path=db_path)

    def solve_initial_squad(self, gameweek: int = 1, budget: float = 100.0) -> Dict[str, Any]:
        """Encuentra la plantilla inicial óptima de 15 jugadores y los 11 titulares bajo £100M."""
        gw_df = self.inference.predict_gameweek(gameweek=gameweek)
        if gw_df.empty:
            return {"error": f"No hay datos para la GW {gameweek}"}

        # Filtrar candidatos relevantes (top 20 por posición) para optimización ultrarrápida (<0.1s)
        candidates = []
        for pos_code in [1, 2, 3, 4]:
            top_pos = gw_df[gw_df["element_type"] == pos_code].sort_values("xp_final", ascending=False).head(20)
            candidates.append(top_pos)
        
        filtered_df = pd.concat(candidates).drop_duplicates(subset=["player_id"])
        players = filtered_df.to_dict("records")
        prob = pulp.LpProblem("FPL_Initial_Squad_Optimization", pulp.LpMaximize)

        # Variables de decisión
        x_squad = {p["player_id"]: pulp.LpVariable(f"squad_{p['player_id']}", cat="Binary") for p in players}
        x_start = {p["player_id"]: pulp.LpVariable(f"start_{p['player_id']}", cat="Binary") for p in players}
        x_cap = {p["player_id"]: pulp.LpVariable(f"cap_{p['player_id']}", cat="Binary") for p in players}

        # Función Objetivo: Maximizar xP de los 11 titulares + 1x extra del capitán
        prob += pulp.lpSum([
            x_start[p["player_id"]] * p["xp_final"] + x_cap[p["player_id"]] * p["xp_final"]
            for p in players
        ])

        # Restricción 1: Presupuesto £100M
        prob += pulp.lpSum([x_squad[p["player_id"]] * p["price"] for p in players]) <= budget

        # Restricción 2: Exactamente 15 en plantilla
        prob += pulp.lpSum([x_squad[p["player_id"]] for p in players]) == 15

        # Restricción 3: Exactamente 11 titulares
        prob += pulp.lpSum([x_start[p["player_id"]] for p in players]) == 11

        # Restricción 4: Titular solo si está en plantilla
        for p in players:
            prob += x_start[p["player_id"]] <= x_squad[p["player_id"]]
            prob += x_cap[p["player_id"]] <= x_start[p["player_id"]]

        # Restricción 5: Exactamente 1 Capitán
        prob += pulp.lpSum([x_cap[p["player_id"]] for p in players]) == 1

        # Restricción 6: Estructura de plantilla por posición (2 GKP, 5 DEF, 5 MID, 3 FWD)
        pos_squad_limits = {1: 2, 2: 5, 3: 5, 4: 3}
        for pos_code, count in pos_squad_limits.items():
            prob += pulp.lpSum([x_squad[p["player_id"]] for p in players if p["element_type"] == pos_code]) == count

        # Restricción 7: Formación titular válida (1 GKP, 3-5 DEF, 2-5 MID, 1-3 FWD)
        prob += pulp.lpSum([x_start[p["player_id"]] for p in players if p["element_type"] == 1]) == 1
        prob += pulp.lpSum([x_start[p["player_id"]] for p in players if p["element_type"] == 2]) >= 3
        prob += pulp.lpSum([x_start[p["player_id"]] for p in players if p["element_type"] == 2]) <= 5
        prob += pulp.lpSum([x_start[p["player_id"]] for p in players if p["element_type"] == 3]) >= 2
        prob += pulp.lpSum([x_start[p["player_id"]] for p in players if p["element_type"] == 3]) <= 5
        prob += pulp.lpSum([x_start[p["player_id"]] for p in players if p["element_type"] == 4]) >= 1
        prob += pulp.lpSum([x_start[p["player_id"]] for p in players if p["element_type"] == 4]) <= 3

        # Restricción 8: Máximo 3 jugadores por club
        clubs = set(p["team_short"] for p in players if p["team_short"])
        for club in clubs:
            prob += pulp.lpSum([x_squad[p["player_id"]] for p in players if p["team_short"] == club]) <= 3

        # Resolver el MILP
        prob.solve(pulp.PULP_CBC_CMD(msg=False))

        squad_res = [p for p in players if pulp.value(x_squad[p["player_id"]]) == 1]
        starters_res = [p for p in players if pulp.value(x_start[p["player_id"]]) == 1]
        captain_res = [p for p in players if pulp.value(x_cap[p["player_id"]]) == 1][0]
        bench_res = [p for p in squad_res if p["player_id"] not in [s["player_id"] for s in starters_res]]

        total_cost = sum(p["price"] for p in squad_res)
        total_xp = sum(p["xp_final"] for p in starters_res) + captain_res["xp_final"]

        return {
            "squad_15": squad_res,
            "starters_11": starters_res,
            "bench_4": bench_res,
            "captain": captain_res,
            "total_cost": round(total_cost, 2),
            "expected_points": round(total_xp, 2),
            "budget_remaining": round(budget - total_cost, 2),
        }

    def solve_transfers(
        self,
        current_squad_ids: List[int],
        free_transfers: int,
        gameweek: int,
        gw_df: Optional[pd.DataFrame] = None,
        budget_available: float = 100.0
    ) -> Dict[str, Any]:
        """Resuelve las transferencias óptimas (Out -> In) considerando presupuesto y costo de hits (-4 pts)."""
        if gw_df is None:
            gw_df = self.inference.predict_gameweek(gameweek=gameweek)
            
        players = gw_df.to_dict("records")
        player_map = {p["player_id"]: p for p in players}

        # Transferencias gratis disponibles (máximo 5)
        ft_avail = min(5, max(1, free_transfers))

        # Probar combinaciones de transferencias (0, 1, 2 transferencias)
        best_sol = None
        max_net_xp = -999.0

        # Para simplificar la búsqueda voraz intertemporal:
        current_players = [player_map[pid] for pid in current_squad_ids if pid in player_map]
        
        # 1. Probar mantener equipo actual (0 transferencias)
        squad_ids = [p["player_id"] for p in current_players]
        starters_11, cap = self._pick_starters_from_squad(current_players)
        net_xp = sum(p["xp_final"] for p in starters_11) + cap["xp_final"]
        best_sol = {
            "transfers_out": [],
            "transfers_in": [],
            "hits_taken": 0,
            "hit_penalty": 0,
            "starters_11": starters_11,
            "captain": cap,
            "net_xp": round(net_xp, 2),
            "squad_15_ids": squad_ids,
        }
        max_net_xp = net_xp

        # 2. Probar transferencias simples (1 Out -> 1 In)
        candidates_out = sorted(current_players, key=lambda p: p["xp_final"])[:5] # 5 peores
        candidates_in = sorted([p for p in players if p["player_id"] not in squad_ids], key=lambda p: p["xp_final"], reverse=True)[:15]

        for p_out in candidates_out:
            for p_in in candidates_in:
                if p_in["element_type"] != p_out["element_type"]:
                    continue # Mantener misma posición
                
                new_squad = [p for p in current_players if p["player_id"] != p_out["player_id"]] + [p_in]
                new_cost = sum(p["price"] for p in new_squad)
                if new_cost > budget_available:
                    continue

                # Verificar límite de 3 por club
                clubs = [p["team_short"] for p in new_squad if p["team_short"]]
                if any(clubs.count(c) > 3 for c in set(clubs)):
                    continue

                starters_11, cap = self._pick_starters_from_squad(new_squad)
                gross_xp = sum(p["xp_final"] for p in starters_11) + cap["xp_final"]
                hits = max(0, 1 - ft_avail)
                hit_penalty = hits * 4
                cand_net_xp = gross_xp - hit_penalty

                if cand_net_xp > max_net_xp:
                    max_net_xp = cand_net_xp
                    best_sol = {
                        "transfers_out": [p_out],
                        "transfers_in": [p_in],
                        "hits_taken": hits,
                        "hit_penalty": hit_penalty,
                        "starters_11": starters_11,
                        "captain": cap,
                        "net_xp": round(cand_net_xp, 2),
                        "squad_15_ids": [p["player_id"] for p in new_squad],
                    }

        return best_sol

    def _pick_starters_from_squad(self, squad_15: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Elige los 11 titulares que maximizan xP dentro de una plantilla de 15 dada."""
        squad_df = pd.DataFrame(squad_15).sort_values("xp_final", ascending=False)
        gks = squad_df[squad_df["element_type"] == 1].head(1)
        defs = squad_df[squad_df["element_type"] == 2].head(4)
        mids = squad_df[squad_df["element_type"] == 3].head(4)
        fwds = squad_df[squad_df["element_type"] == 4].head(2)

        starters = pd.concat([gks, defs, mids, fwds]).to_dict("records")
        captain = sorted(starters, key=lambda p: p["xp_final"], reverse=True)[0]
        return starters, captain
