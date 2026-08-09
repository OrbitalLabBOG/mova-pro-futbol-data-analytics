"""Optimizador de plantilla con horizonte rodante (WP-006).

Tres piezas separadas a proposito:

- `horizon`    proyecta xp sobre N jornadas usando el CALENDARIO, no el futuro.
- `heuristics` recorta el mercado antes de resolver, con criterio declarado.
- `milp`       resuelve el programa entero mixto y devuelve una `Decision`.
- `freehit`    valora el free hit aparte, porque su reversion no cabe en el MILP.

La separacion importa porque el estado del arte dice que lo que separa a un
optimizador competente de uno ingenuo es el horizonte, no el solver.
"""
from mova_fpl.optimizer.heuristics import ShortlistReport, shortlist
from mova_fpl.optimizer.horizon import build_xp_matrix, per_match_rate
from mova_fpl.optimizer.milp import Infeasible, OptimizerConfig, solve
from mova_fpl.optimizer.freehit import FreeHitPlan, free_hit_budget
from mova_fpl.optimizer.freehit import evaluate as evaluate_free_hit

__all__ = ["solve", "OptimizerConfig", "Infeasible", "build_xp_matrix",
           "evaluate_free_hit", "FreeHitPlan", "free_hit_budget",
           "per_match_rate", "shortlist", "ShortlistReport"]
