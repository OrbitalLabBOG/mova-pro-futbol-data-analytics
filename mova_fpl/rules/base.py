"""Tipos del motor de reglas. Puro: sin pandas, sin numpy, sin sqlite3.

Cualquier import de una libreria de datos aqui hace fallar
tests/test_architecture_boundaries.py::test_rules_es_puro_cuando_exista.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Position(str, Enum):
    GKP = "GKP"
    DEF = "DEF"
    MID = "MID"
    FWD = "FWD"

    @classmethod
    def parse(cls, raw) -> "Position":
        s = str(raw).strip().upper()
        alias = {"GK": "GKP", "GOALKEEPER": "GKP", "G": "GKP", "1": "GKP",
                 "D": "DEF", "DEFENDER": "DEF", "2": "DEF",
                 "M": "MID", "MIDFIELDER": "MID", "3": "MID",
                 "F": "FWD", "FORWARD": "FWD", "STRIKER": "FWD", "4": "FWD"}
        return cls(alias.get(s, s))


@dataclass(frozen=True, slots=True)
class PlayerStats:
    """Actuacion observada de un jugador en un partido.

    `bonus` entra como dato porque depende del BPS de los 22 jugadores del
    partido, no del rendimiento individual aislado. Proyectarlo es tarea del
    modelo (WP-005), no del motor de reglas.
    """
    position: Position
    minutes: int = 0
    goals_scored: int = 0
    assists: int = 0
    clean_sheets: int = 0
    goals_conceded: int = 0
    own_goals: int = 0
    penalties_saved: int = 0
    penalties_missed: int = 0
    yellow_cards: int = 0
    red_cards: int = 0
    saves: int = 0
    bonus: int = 0
    defensive_contribution: int | None = None   # conteo crudo CBIT/CBIRT; None = regla inexistente


@dataclass(frozen=True, slots=True)
class PointsBreakdown:
    """Puntos por componente. El total nunca se calcula aparte de las partes."""
    appearance: int = 0
    goals: int = 0
    assists: int = 0
    clean_sheet: int = 0
    saves: int = 0
    penalties_saved: int = 0
    penalties_missed: int = 0
    goals_conceded: int = 0
    cards: int = 0
    own_goals: int = 0
    defensive_contribution: int = 0
    bonus: int = 0

    @property
    def total(self) -> int:
        return (self.appearance + self.goals + self.assists + self.clean_sheet
                + self.saves + self.penalties_saved + self.penalties_missed
                + self.goals_conceded + self.cards + self.own_goals
                + self.defensive_contribution + self.bonus)

    def as_dict(self) -> dict:
        return {f: getattr(self, f) for f in self.__slots__} | {"total": self.total}


@dataclass(frozen=True, slots=True)
class SquadPlayer:
    element: int
    position: Position
    team: str
    price: float          # en millones
    purchase_price: float | None = None


@dataclass(frozen=True, slots=True)
class Squad:
    players: tuple[SquadPlayer, ...]
    starters: tuple[int, ...] = ()      # element ids del XI
    captain: int | None = None
    vice_captain: int | None = None
    bench_order: tuple[int, ...] = ()   # orden de prioridad tras el GKP suplente
    bank: float = 0.0


@dataclass(frozen=True, slots=True)
class Violation:
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class ScoringTable:
    """Parametros de puntuacion. Congelados por temporada."""
    goal_points: dict = field(default_factory=dict)
    clean_sheet_points: dict = field(default_factory=dict)
    assist_points: int = 3
    appearance_short: int = 1           # 1..59 minutos
    appearance_long: int = 2            # 60+ minutos
    minutes_for_long: int = 60
    saves_per_point: int = 3
    penalty_save_points: int = 5
    penalty_miss_points: int = -2
    conceded_per_penalty: int = 2       # -1 por cada 2 encajados
    conceded_penalty: int = -1
    yellow_card_points: int = -1
    red_card_points: int = -3
    own_goal_points: int = -2
    defcon_points: int = 2
    defcon_thresholds: dict = field(default_factory=dict)   # Position -> umbral; ausente = no elegible
