"""Que puede tocar un agente, y como se aplica al estado. Puro.

Una `Intervention` es un valor inmutable y serializable: se guarda en la bitacora
tal cual, se vuelve a aplicar identica y se audita despues. No contiene codigo ni
callbacks — un agente que pudiera inyectar logica seria imposible de reproducir.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from mova_fpl.rules.base import Violation
from mova_fpl.rules.chips import CHIP_NAMES, validate_chip

#: cota de los multiplicadores de xp. Un agente puede matizar una proyeccion,
#: no inventarla: fuera de este rango ya no esta ajustando el modelo, lo esta
#: sustituyendo por su opinion.
MULT_MIN, MULT_MAX = 0.0, 2.0


@dataclass(frozen=True, slots=True)
class Intervention:
    """Todo lo que un agente puede mover en una jornada. Nada mas.

    Ausente de esta lista, a proposito: la plantilla, el once, el capitan, el
    orden del banquillo y las transferencias. Eso lo decide el optimizador.
    """
    gw: int
    author: str                                   # "planner" | "agent:noticias" | "julian"
    rationale: str = ""                           # por que. Obligatorio en la practica
    #: element -> factor sobre el xp proyectado. 0.0 = no juega; 1.3 = en racha.
    xp_multiplier: dict = field(default_factory=dict)
    #: chips que el agente pone sobre la mesa, por encima del planificador
    allow_chips: frozenset = frozenset()
    #: chips que el agente veta esta jornada aunque el planificador los proponga
    block_chips: frozenset = frozenset()
    #: jugadores que no se pueden vender (sube de precio, rota pero vuelve)
    lock_in: frozenset = frozenset()
    #: jugadores que no pueden estar en plantilla (lesion no reflejada aun)
    lock_out: frozenset = frozenset()
    #: aversion al riesgo del objetivo. None = no lo toca
    risk_lambda: float | None = None

    def is_empty(self) -> bool:
        return not (self.xp_multiplier or self.allow_chips or self.block_chips
                    or self.lock_in or self.lock_out or self.risk_lambda is not None)

    def to_dict(self) -> dict:
        return {
            "gw": self.gw, "author": self.author, "rationale": self.rationale,
            "xp_multiplier": {int(k): float(v) for k, v in self.xp_multiplier.items()},
            "allow_chips": sorted(self.allow_chips), "block_chips": sorted(self.block_chips),
            "lock_in": sorted(int(i) for i in self.lock_in),
            "lock_out": sorted(int(i) for i in self.lock_out),
            "risk_lambda": self.risk_lambda,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Intervention":
        return cls(
            gw=int(d["gw"]), author=str(d.get("author", "desconocido")),
            rationale=str(d.get("rationale", "")),
            xp_multiplier={int(k): float(v) for k, v in (d.get("xp_multiplier") or {}).items()},
            allow_chips=frozenset(d.get("allow_chips") or ()),
            block_chips=frozenset(d.get("block_chips") or ()),
            lock_in=frozenset(int(i) for i in (d.get("lock_in") or ())),
            lock_out=frozenset(int(i) for i in (d.get("lock_out") or ())),
            risk_lambda=d.get("risk_lambda"),
        )


def validate(intervention: Intervention, state) -> list[Violation]:
    """Todo lo que esta mal en una intervencion, antes de aplicarla.

    Se valida ANTES de tocar el estado: un agente que se equivoca tiene que
    enterarse por un error explicito, no por una decision rara tres pasos
    despues.
    """
    v: list[Violation] = []
    if intervention.gw != state.gw:
        v.append(Violation("INTERVENTION_WRONG_GW",
                           f"la intervencion es de la GW{intervention.gw} y el estado "
                           f"esta en la GW{state.gw}"))
    if not intervention.author:
        v.append(Violation("INTERVENTION_NO_AUTHOR", "toda intervencion necesita autor"))
    if not intervention.rationale.strip() and not intervention.is_empty():
        v.append(Violation("INTERVENTION_NO_RATIONALE",
                           "una intervencion sin motivo escrito no se puede auditar despues"))

    conocidos = {c.element for c in state.candidates}
    if state.squad:
        conocidos |= {p.element for p in state.squad.players}

    for e, m in intervention.xp_multiplier.items():
        if e not in conocidos:
            v.append(Violation("UNKNOWN_PLAYER", f"el elemento {e} no esta en el mercado"))
        if not (MULT_MIN <= float(m) <= MULT_MAX):
            v.append(Violation("MULTIPLIER_OUT_OF_RANGE",
                               f"factor {m} para el elemento {e} fuera de [{MULT_MIN}, {MULT_MAX}]"))

    for e in intervention.lock_in:
        if state.squad is None or e not in {p.element for p in state.squad.players}:
            v.append(Violation("LOCK_IN_NOT_OWNED",
                               f"no se puede proteger al elemento {e}: no esta en la plantilla"))
    solapan = intervention.lock_in & intervention.lock_out
    if solapan:
        v.append(Violation("LOCK_CONFLICT", f"elementos protegidos y vetados a la vez: {sorted(solapan)}"))

    for c in intervention.allow_chips | intervention.block_chips:
        if c not in CHIP_NAMES:
            v.append(Violation("CHIP_UNKNOWN", f"{c!r} no es un chip"))
    chocan = intervention.allow_chips & intervention.block_chips
    if chocan:
        v.append(Violation("CHIP_CONFLICT", f"chips autorizados y vetados a la vez: {sorted(chocan)}"))

    if state.chips is not None:
        for c in sorted(intervention.allow_chips):
            v += validate_chip(c, state.gw, state.chips_used, state.chips)

    if intervention.risk_lambda is not None and intervention.risk_lambda < 0:
        v.append(Violation("RISK_LAMBDA_NEGATIVE",
                           f"risk_lambda {intervention.risk_lambda} no puede ser negativo"))
    return v


def apply(state, intervention: Intervention, *, strict: bool = True):
    """Estado nuevo con la intervencion aplicada. No muta el original.

    Con `strict` (por defecto) una intervencion invalida levanta ValueError. El
    modo permisivo existe solo para inspeccionar que HABRIA hecho una propuesta
    mala, nunca para operar.
    """
    problemas = validate(intervention, state)
    if problemas and strict:
        detalle = "\n  - ".join(f"{p.code}: {p.detail}" for p in problemas)
        raise ValueError(f"intervencion invalida en la GW{intervention.gw}:\n  - {detalle}")

    nuevo = state
    if intervention.xp_multiplier:
        nuevo = replace(nuevo,
                        candidates=_escalar_candidatos(nuevo.candidates, intervention.xp_multiplier),
                        horizon_xp=_escalar_horizonte(nuevo.horizon_xp, intervention.xp_multiplier))

    permitidos = dict(nuevo.chips_allowed or {})
    del_gw = set(permitidos.get(state.gw, frozenset())) | set(intervention.allow_chips)
    del_gw -= set(intervention.block_chips)
    if del_gw:
        permitidos[state.gw] = frozenset(del_gw)
    else:
        permitidos.pop(state.gw, None)

    return replace(nuevo,
                   chips_allowed=permitidos,
                   lock_in=frozenset(nuevo.lock_in) | intervention.lock_in,
                   lock_out=frozenset(nuevo.lock_out) | intervention.lock_out)


def merge(a: Intervention, b: Intervention) -> Intervention:
    """Combina dos intervenciones de la misma jornada. La segunda tiene prioridad.

    Sirve para apilar fuentes: el planificador propone chips, el agente de
    noticias ajusta minutos, y Julian veta a alguien a mano.
    """
    if a.gw != b.gw:
        raise ValueError(f"no se pueden combinar intervenciones de GW{a.gw} y GW{b.gw}")
    mult = {**a.xp_multiplier, **b.xp_multiplier}
    return Intervention(
        gw=a.gw,
        author=f"{a.author}+{b.author}",
        rationale="; ".join(x for x in (a.rationale, b.rationale) if x),
        xp_multiplier=mult,
        allow_chips=(a.allow_chips | b.allow_chips) - b.block_chips,
        block_chips=a.block_chips | b.block_chips,
        lock_in=(a.lock_in | b.lock_in) - b.lock_out,
        lock_out=a.lock_out | b.lock_out,
        risk_lambda=b.risk_lambda if b.risk_lambda is not None else a.risk_lambda,
    )


def describe(intervention: Intervention) -> str:
    """Una linea legible para el acta. Lo que un humano tiene que poder revisar."""
    if intervention.is_empty():
        return f"{intervention.author}: sin intervencion"
    partes = []
    if intervention.xp_multiplier:
        bajadas = sum(1 for m in intervention.xp_multiplier.values() if m < 1)
        subidas = sum(1 for m in intervention.xp_multiplier.values() if m > 1)
        partes.append(f"xp ajustado en {len(intervention.xp_multiplier)} jugadores "
                      f"({bajadas} a la baja, {subidas} al alza)")
    if intervention.allow_chips:
        partes.append(f"chips propuestos: {', '.join(sorted(intervention.allow_chips))}")
    if intervention.block_chips:
        partes.append(f"chips vetados: {', '.join(sorted(intervention.block_chips))}")
    if intervention.lock_in:
        partes.append(f"{len(intervention.lock_in)} protegidos")
    if intervention.lock_out:
        partes.append(f"{len(intervention.lock_out)} vetados")
    if intervention.risk_lambda is not None:
        partes.append(f"riesgo lambda={intervention.risk_lambda}")
    cuerpo = " · ".join(partes)
    return f"{intervention.author}: {cuerpo} — {intervention.rationale}"


def _escalar_candidatos(candidates, mult: dict):
    return tuple(replace(c, xp=c.xp * float(mult[c.element])) if c.element in mult else c
                 for c in candidates)


def _escalar_horizonte(horizon_xp: dict, mult: dict) -> dict:
    """El ajuste se propaga a TODO el horizonte, no solo a la jornada que se decide.

    Si un jugador esta lesionado, no lo esta solo hoy. Un agente que quiera
    matizar una sola jornada tiene que decirlo con un multiplicador por jornada,
    que hoy no existe: seria la primera extension natural de este contrato.
    """
    if not horizon_xp:
        return horizon_xp
    return {g: {e: (v * float(mult[e]) if e in mult else v) for e, v in fila.items()}
            for g, fila in horizon_xp.items()}
