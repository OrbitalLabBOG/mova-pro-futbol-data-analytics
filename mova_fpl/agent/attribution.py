"""Cuanto valio una intervencion. Medido, no estimado.

Toda intervencion se evalua igual: se decide dos veces —con ella y sin ella— y se
puntuan las dos decisiones contra los MISMOS resultados reales. La resta es el
valor. No hay formula cerrada ni auto-reporte del agente.

Dos numeros distintos y hay que no confundirlos:

- `expected_delta`  lo que el modelo CREIA que iba a ganar. Se conoce antes de
                    jugar la jornada y sirve para decidir.
- `realized_delta`  lo que de verdad gano. Solo existe despues, y es el unico que
                    cuenta para juzgar si el agente aporta.

Un agente puede tener `expected_delta` alto siempre —basta con inflar sus propias
proyecciones— y `realized_delta` negativo. Por eso la bitacora guarda los dos: la
brecha entre ambos es su calibracion, y es la metrica que de verdad lo retrata.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Attribution:
    """Ficha de una intervencion: que se propuso, que cambio y cuanto valio."""
    gw: int
    author: str
    rationale: str
    expected_delta: float                 # xp esperado con - sin
    realized_delta: int | None = None     # puntos reales con - sin (None antes de jugar)
    points_with: int | None = None
    points_without: int | None = None
    changed: bool = False                 # ¿cambio algo en la decision?
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"gw": self.gw, "author": self.author, "rationale": self.rationale,
                "expected_delta": round(self.expected_delta, 3),
                "realized_delta": self.realized_delta,
                "points_with": self.points_with, "points_without": self.points_without,
                "changed": self.changed, "detail": self.detail}

    def as_note(self) -> str:
        signo = f"{self.expected_delta:+.1f} xp"
        if self.realized_delta is not None:
            signo += f" · {self.realized_delta:+d} pts reales"
        if not self.changed:
            return f"{self.author}: sin efecto sobre la decision"
        return f"{self.author}: {signo} — {self.rationale}"


def measure(state, intervention, config, decide_fn) -> Attribution:
    """Efecto ESPERADO de una intervencion, antes de que se juegue la jornada.

    Es lo que se puede saber a la hora del deadline: si la intervencion cambio la
    decision y cuanto xp promete. El valor realizado se rellena despues, cuando
    hay resultados, con `settle`.
    """
    from mova_fpl.agent.contract import apply

    base = decide_fn(state.gw, state, config)
    tocado = apply(state, intervention)
    nuevo = decide_fn(state.gw, tocado, config)

    cambio = base.fingerprint() != nuevo.fingerprint()
    return Attribution(
        gw=state.gw, author=intervention.author, rationale=intervention.rationale,
        expected_delta=round(nuevo.expected_points - base.expected_points, 3),
        changed=cambio,
        detail={
            "fingerprint_sin": base.fingerprint(), "fingerprint_con": nuevo.fingerprint(),
            "chip_sin": base.chip, "chip_con": nuevo.chip,
            "entran": sorted(set(nuevo.squad_15) - set(base.squad_15)),
            "salen": sorted(set(base.squad_15) - set(nuevo.squad_15)),
            "capitan_sin": base.captain, "capitan_con": nuevo.captain,
        },
    )


def settle(attribution: Attribution, points_with: int, points_without: int) -> Attribution:
    """Cierra la ficha con los puntos reales de las dos decisiones."""
    from dataclasses import replace
    return replace(attribution, points_with=points_with, points_without=points_without,
                   realized_delta=points_with - points_without)


def summarize(fichas) -> dict:
    """Balance de una temporada de intervenciones. Lo que se le pregunta al agente.

    `calibracion` es la brecha media entre lo prometido y lo entregado. Positiva
    significa que el agente promete mas de lo que cumple.
    """
    con_efecto = [f for f in fichas if f.changed]
    cerradas = [f for f in con_efecto if f.realized_delta is not None]
    realizado = sum(f.realized_delta for f in cerradas)
    esperado = sum(f.expected_delta for f in cerradas)
    return {
        "intervenciones": len(fichas),
        "con_efecto": len(con_efecto),
        "medidas": len(cerradas),
        "valor_realizado": realizado,
        "valor_esperado": round(esperado, 1),
        "calibracion": round((esperado - realizado) / len(cerradas), 2) if cerradas else None,
        "aciertos": sum(1 for f in cerradas if f.realized_delta > 0),
        "fallos": sum(1 for f in cerradas if f.realized_delta < 0),
    }
