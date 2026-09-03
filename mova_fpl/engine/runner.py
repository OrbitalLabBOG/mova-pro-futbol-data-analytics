"""LA funcion de decision (ADR-004).

Existe exactamente una. El simulador de backtest y el runner en vivo son solo
dos proveedores de `State`. Si aparece logica de decision fuera de aqui, el
backtest deja de ser evidencia sobre produccion.
"""
from __future__ import annotations

from dataclasses import dataclass

from mova_fpl.engine.policies import POLICIES
from mova_fpl.engine.state import Decision, State


@dataclass(frozen=True, slots=True)
class Config:
    policy: str = "greedy-stub"
    projector: str = "naive"          # naive (WP-003) | minutes (WP-004)
    model_version: str = "1.0.0"
    horizon: int = 1
    seed: int = 42
    #: "none" = no se juegan chips (comportamiento de v1, reproduce los 2.217).
    #: "planner" = el planificador de engine/planner.py autoriza jornada a jornada.
    chip_policy: str = "none"
    #: jornadas de calendario que el planificador considera anunciadas. Ver L-01.
    structure_lookahead: int = 6
    # --- mandos del optimizador (WP-006). Solo los lee la politica `milp`.
    decay: float = 0.84               # descuento por jornada futura
    bench_weight: float = 0.12        # valor del banquillo en el objetivo
    top_k: int = 30                   # recorte de mercado por posicion (0 = sin recorte)
    max_hits: int = 2                 # tope de transferencias pagadas por jornada
    time_limit: int = 30              # segundos por jornada antes de rendirse
    transfer_penalty: float = 0.0     # valor de opcion de conservar un cambio
    terminal_free_transfer_value: float = 0.0  # valor de continuación al truncar horizonte
    uncertainty_transfer_weight: float = 0.0  # robustez epistemica de compra/venta


def decide(gw: int, state: State, config: Config | None = None) -> Decision:
    config = config or Config()
    if gw != state.gw:
        raise ValueError(f"gw={gw} no coincide con state.gw={state.gw}")
    try:
        policy = POLICIES[config.policy]
    except KeyError:
        raise ValueError(f"politica desconocida: {config.policy}. Validas: {sorted(POLICIES)}") from None
    return policy(state, config)
