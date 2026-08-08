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
    chip_policy: str = "none"


def decide(gw: int, state: State, config: Config | None = None) -> Decision:
    config = config or Config()
    if gw != state.gw:
        raise ValueError(f"gw={gw} no coincide con state.gw={state.gw}")
    try:
        policy = POLICIES[config.policy]
    except KeyError:
        raise ValueError(f"politica desconocida: {config.policy}. Validas: {sorted(POLICIES)}") from None
    return policy(state, config)
