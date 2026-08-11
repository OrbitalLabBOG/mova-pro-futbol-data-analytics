"""Banda de ruido: perturbaciones estrategicamente irrelevantes (0.5% en xp).

Si el total de temporada se mueve mucho bajo ruido que NO cambia la estrategia,
entonces un delta del agente por debajo de esa banda no es evidencia de nada.
"""
import random, sys
from mova_fpl.agent import Intervention
from mova_fpl.engine.runner import Config
from mova_fpl.engine.simulator import replay
from mova_fpl.trace import TraceWriter
from pathlib import Path
import tempfile

def jitter_agent(seed):
    rng = random.Random(seed)
    def fn(state):
        mult = {c.element: round(1.0 + rng.uniform(-0.005, 0.005), 6) for c in state.candidates}
        return Intervention(gw=state.gw, author=f"jitter:{seed}",
                            rationale="ruido 0.5% estrategicamente irrelevante",
                            xp_multiplier=mult)
    return fn

cfg = Config(policy='milp', projector='points', horizon=3, seed=42,
             chip_policy='planner', structure_lookahead=6)
tmp = Path(tempfile.mkdtemp())
totales = []
for s in [1, 2, 3, 4, 5]:
    tr = TraceWriter(tmp / f"j{s}.db")
    r = replay('2025-26', mode='anonymized', config=cfg, trace=tr,
               run_id=f'jitter-{s}', max_gw=38, verbose=False, agent_fn=jitter_agent(s))
    totales.append(r.total)
    print(f"jitter seed {s}: {r.total} pts", flush=True)
import statistics
print(f"\nbaseline sin ruido: 2303")
print(f"con ruido 0.5%: min {min(totales)} max {max(totales)} media {statistics.mean(totales):.0f} "
      f"desv {statistics.pstdev(totales):.0f}")
print(f"RANGO: {max(totales)-min(totales)} pts")
