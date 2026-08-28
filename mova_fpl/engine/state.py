"""Tipos del ciclo de decision.

`State` es un VALOR: contiene cuanto la decision necesita. Por eso el simulador
y el runner en vivo pueden alimentar la misma `decide()` (ADR-004).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from mova_fpl.rules.base import Position, Squad
from mova_fpl.rules.chips import ChipCatalogue, ChipUse


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
    bank: float = 0.0
    rules: dict = field(default_factory=dict)
    #: historia de chips ya gastados, con su jornada. Define inventario y ventana.
    chips_used: tuple[ChipUse, ...] = ()
    #: reglas de chips de la temporada. None = los chips no se modelan en esta corrida.
    chips: ChipCatalogue | None = None
    #: chips AUTORIZADOS por jornada del horizonte: {gw: frozenset(nombres)}.
    #: Lo llena el planificador (o un agente); el optimizador decide si le conviene
    #: usarlos. Vacio = el optimizador no puede jugar ningun chip. Autorizar no es
    #: obligar: la separacion entre "puedes" y "debes" es lo que mantiene medible
    #: la intervencion de quien autoriza.
    chips_allowed: dict = field(default_factory=dict)
    #: restricciones blandas que un agente puede imponer sobre la jornada actual.
    #: `lock_in`: jugadores que no se pueden vender (p. ej. sube de precio manana).
    #: `lock_out`: jugadores que no se pueden tener (p. ej. lesion no confirmada aun).
    lock_in: frozenset = frozenset()
    lock_out: frozenset = frozenset()
    #: calendario VISIBLE: {(equipo, gw): n_partidos}. Lo llena el entorno, capado
    #: al lookahead declarado, no a la temporada entera: cuanta estructura se
    #: considera anunciada es una decision de honestidad, no de conveniencia (L-01).
    schedule: dict = field(default_factory=dict)
    #: xp proyectado por jornada para el horizonte: {gw: {element: xp}}. La jornada
    #: actual incluida. Vacio = solo se decide con `candidates` (horizonte 1).
    #: Lo llena el proveedor de estado (simulador o runner en vivo), nunca la politica:
    #: State sigue siendo un VALOR y decide() sigue sin tocar la base de datos.
    horizon_xp: dict = field(default_factory=dict)

    @property
    def is_cold_start(self) -> bool:
        return self.squad is None

    def chips_available(self, gw: int | None = None) -> frozenset:
        """Chips legalmente jugables en `gw` segun catalogo e inventario.

        Es distinto de `chips_allowed`: esto es lo que las REGLAS permiten; aquello
        es lo que el planificador decidio poner sobre la mesa.
        """
        if self.chips is None:
            return frozenset()
        from mova_fpl.rules.chips import available
        return available(gw if gw is not None else self.gw, self.chips_used, self.chips)

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
    hits: int = 0  # número de transferencias pagadas; cada una cuesta rules["hit_cost"]
    chip: str | None = None
    expected_points: float = 0.0
    total_cost: float = 0.0
    bank_after: float = 0.0
    policy: str = ""
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        """Contrato máquina estable; el Markdown es únicamente una vista humana."""
        return {
            "season": self.season,
            "gw": self.gw,
            "squad_15": list(self.squad_15),
            "starters": list(self.starters),
            "captain": self.captain,
            "vice_captain": self.vice_captain,
            "bench_order": list(self.bench_order),
            "transfers_in": list(self.transfers_in),
            "transfers_out": list(self.transfers_out),
            "hits": self.hits,
            "chip": self.chip,
            "expected_points": self.expected_points,
            "total_cost": self.total_cost,
            "bank_after": self.bank_after,
            "policy": self.policy,
            "notes": list(self.notes),
            "fingerprint": self.fingerprint(),
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "Decision":
        """Reconstruye una decisión para replay sin aceptar campos implícitos."""
        decision = cls(
            season=str(payload["season"]),
            gw=int(payload["gw"]),
            squad_15=tuple(int(value) for value in payload["squad_15"]),
            starters=tuple(int(value) for value in payload["starters"]),
            captain=(int(payload["captain"]) if payload.get("captain") is not None else None),
            vice_captain=(
                int(payload["vice_captain"])
                if payload.get("vice_captain") is not None else None
            ),
            bench_order=tuple(int(value) for value in payload["bench_order"]),
            transfers_in=tuple(int(value) for value in payload.get("transfers_in", ())),
            transfers_out=tuple(int(value) for value in payload.get("transfers_out", ())),
            hits=int(payload.get("hits", 0)),
            chip=payload.get("chip"),
            expected_points=float(payload.get("expected_points", 0.0)),
            total_cost=float(payload.get("total_cost", 0.0)),
            bank_after=float(payload.get("bank_after", 0.0)),
            policy=str(payload.get("policy", "")),
            notes=tuple(str(value) for value in payload.get("notes", ())),
        )
        expected = payload.get("fingerprint")
        if expected is not None and str(expected) != decision.fingerprint():
            raise ValueError("fingerprint de Decision no coincide con su contenido")
        return decision

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
