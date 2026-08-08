"""Tipos del ciclo de decision.

`State` es un VALOR: contiene cuanto la decision necesita. Por eso el simulador
y el runner en vivo pueden alimentar la misma `decide()` (ADR-004).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from mova_fpl.rules.base import Position, Squad


@dataclass(frozen=True, slots=True)
class Candidate:
    """Un jugador disponible en el mercado para una gameweek."""
    element: int
    position: Position
    team: str
    price: float
    xp: float                      # puntos esperados segun el modelo vigente
    breakdown: dict = field(default_factory=dict)
    name: str = ""


@dataclass(frozen=True, slots=True)
class State:
    """Estado completo previo a decidir. Sin referencias a base de datos."""
    season: str
    gw: int
    candidates: tuple[Candidate, ...]
    squad: Squad | None = None            # None en GW1: no hay plantilla previa
    free_transfers: int = 1
    chips_used: frozenset = frozenset()
    bank: float = 0.0
    rules: dict = field(default_factory=dict)
    #: xp proyectado por jornada para el horizonte: {gw: {element: xp}}. La jornada
    #: actual incluida. Vacio = solo se decide con `candidates` (horizonte 1).
    #: Lo llena el proveedor de estado (simulador o runner en vivo), nunca la politica:
    #: State sigue siendo un VALOR y decide() sigue sin tocar la base de datos.
    horizon_xp: dict = field(default_factory=dict)

    @property
    def is_cold_start(self) -> bool:
        return self.squad is None

    def by_id(self) -> dict:
        return {c.element: c for c in self.candidates}


@dataclass(frozen=True, slots=True)
class Decision:
    """Salida de decide(). Serializable y comparable byte a byte."""
    season: str
    gw: int
    squad_15: tuple[int, ...]
    starters: tuple[int, ...]
    captain: int | None
    vice_captain: int | None
    bench_order: tuple[int, ...]
    transfers_in: tuple[int, ...] = ()
    transfers_out: tuple[int, ...] = ()
    hits: int = 0
    chip: str | None = None
    expected_points: float = 0.0
    total_cost: float = 0.0
    bank_after: float = 0.0
    policy: str = ""
    notes: tuple[str, ...] = ()

    def fingerprint(self) -> str:
        """Huella estable para comparar decisiones entre caminos de ejecucion."""
        import hashlib
        import json
        payload = {
            "season": self.season, "gw": self.gw,
            "squad_15": sorted(self.squad_15), "starters": sorted(self.starters),
            "captain": self.captain, "vice_captain": self.vice_captain,
            "bench_order": list(self.bench_order),
            "transfers_in": sorted(self.transfers_in),
            "transfers_out": sorted(self.transfers_out),
            "hits": self.hits, "chip": self.chip,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class GwOutcome:
    """Resultado real de una decision, una vez jugada la jornada."""
    gw: int
    points: int
    points_before_hits: int
    hits: int
    captain_points: int
    auto_subs: tuple[tuple[int, int], ...]
    effective_captain: int | None
    players_played: int
