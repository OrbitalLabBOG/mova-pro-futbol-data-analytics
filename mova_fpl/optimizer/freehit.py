"""Free hit: valor y plantilla de una jornada desacoplada.

Por que no vive dentro del MILP
-------------------------------
El free hit deja armar la plantilla que uno quiera para UNA jornada, y al cierre
siguiente todo vuelve como estaba. Esa reversion rompe la restriccion que sostiene
el modelo multi-jornada:

    s[i, g+1] = s[i, g] + buy[i, g] - sell[i, g]

Meterlo al modelo grande obligaria a duplicar las variables de plantilla de esa
jornada y a condicionar el enlace con big-M. Mas variables, mas holgura numerica y
un modelo que cuesta mas leer.

Pero un free hit ES, por definicion, una jornada suelta: no hereda restricciones de
transferencia del pasado y no se las impone al futuro. Entonces su valor se calcula
exacto con un solve independiente de una sola jornada, con el presupuesto que da
vender la plantilla entera. Sale mas simple Y mas correcto que aproximarlo dentro.

Sesgo declarado (H-FH-01)
-------------------------
La comparacion es "mejor jornada con free hit" contra "mejor jornada sin el", ambas
a horizonte 1. Eso ignora que las transferencias normales PERSISTEN y el free hit
no, asi que sobreestima ligeramente al chip. En las jornadas donde de verdad se
juega —blancas, con media plantilla sin partido— la diferencia es de un punto o dos
frente a una ventaja de decenas. El planificador lo compensa con su umbral.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from mova_fpl.optimizer.milp import OptimizerConfig, Solution, solve
from mova_fpl.rules.market import squad_value


@dataclass(frozen=True, slots=True)
class FreeHitPlan:
    """Lo que rendiria un free hit en una jornada concreta."""
    gw: int
    value: float                  # puntos esperados extra frente a no jugarlo
    budget: float                 # presupuesto disponible al liquidar la plantilla
    squad: tuple                  # los 15 de la jornada
    starters: tuple
    captain: int | None
    bench_order: tuple
    baseline: float               # objetivo sin chip, para auditar la resta


def free_hit_budget(state) -> float:
    """Lo que se puede gastar: vender todo al precio de venta, mas el banco.

    Sin plantilla previa (arranque en frio) no hay nada que liquidar y el free hit
    no tiene sentido: se devuelve el presupuesto nominal.
    """
    if state.squad is None:
        return float(state.rules["budget"])
    return round(squad_value(state.squad.players, use_selling_price=True) + state.bank, 1)


def evaluate(state, xp_row: dict, config: OptimizerConfig | None = None) -> FreeHitPlan:
    """Cuanto vale jugar el free hit en `state.gw`, y con que plantilla.

    `xp_row` es {element: xp} SOLO de la jornada evaluada: el free hit no mira mas
    alla, porque su plantilla no sobrevive a la jornada.
    """
    base_cfg = config or OptimizerConfig()
    # el desempate y el epsilon distorsionarian una resta de objetivos
    cfg = replace(base_cfg, horizon=1, tie_break=0.0, chip_epsilon=0.0)
    gw = state.gw
    matriz = {gw: dict(xp_row)}

    sin_chip = solve(_sin_chips(state), matriz, cfg)

    presupuesto = free_hit_budget(state)
    libre = _estado_libre(state, presupuesto)
    con_chip = solve(libre, matriz, cfg)

    xi = set(con_chip.starters[gw])
    banca = tuple(i for i in con_chip.squad[gw] if i not in xi)
    return FreeHitPlan(
        gw=gw,
        value=round(con_chip.objective - sin_chip.objective, 4),
        budget=presupuesto,
        squad=con_chip.squad[gw],
        starters=con_chip.starters[gw],
        captain=con_chip.captain[gw],
        bench_order=banca,
        baseline=round(sin_chip.objective, 4),
    )


def _sin_chips(state):
    """El mismo estado, con toda autorizacion de chip retirada."""
    return replace(state, chips_allowed={})


def _estado_libre(state, presupuesto: float):
    """Estado equivalente a 'plantilla desde cero con este presupuesto'.

    Se apoya en el camino de ARRANQUE EN FRIO que el MILP ya tiene: sin plantilla
    previa no hay transferencias que cobrar, que es exactamente la semantica del
    free hit. No hace falta codigo nuevo en el modelo.
    """
    return replace(state, squad=None, bank=0.0, chips_allowed={},
                   lock_in=frozenset(),
                   rules={**state.rules, "budget": presupuesto})
