"""Calculo de puntos a partir de una actuacion. Puro y parametrizado por temporada."""
from __future__ import annotations

from mova_fpl.rules.base import PlayerStats, PointsBreakdown, Position, ScoringTable


def score(stats: PlayerStats, table: ScoringTable) -> PointsBreakdown:
    """Puntos FPL de una actuacion, desglosados por componente.

    Reglas que no son obvias y se codifican explicitamente:
    - Sin minutos no hay puntos de aparicion, pero un jugador con 0 minutos
      igual puede recibir tarjeta o autogol en teoria; FPL los aplica si ocurren.
    - Los goles encajados solo penalizan a GKP y DEF, en tramos de 2.
    - La porteria a cero exige haber jugado el umbral de minutos largo.
    - La contribucion defensiva no aplica a GKP y su umbral depende de la posicion.
    """
    pos = stats.position
    minutes = max(0, int(stats.minutes))

    if minutes <= 0:
        appearance = 0
    elif minutes >= table.minutes_for_long:
        appearance = table.appearance_long
    else:
        appearance = table.appearance_short

    goals = int(stats.goals_scored) * table.goal_points.get(pos, 0)
    assists = int(stats.assists) * table.assist_points

    cs_eligible = minutes >= table.minutes_for_long and int(stats.clean_sheets) > 0
    clean_sheet = table.clean_sheet_points.get(pos, 0) if cs_eligible else 0

    saves = 0
    if pos is Position.GKP and table.saves_per_point > 0:
        saves = int(stats.saves) // table.saves_per_point

    pens_saved = int(stats.penalties_saved) * table.penalty_save_points
    pens_missed = int(stats.penalties_missed) * table.penalty_miss_points

    conceded = 0
    if pos in (Position.GKP, Position.DEF):
        conceded = (int(stats.goals_conceded) // table.conceded_per_penalty) * table.conceded_penalty

    cards = (int(stats.yellow_cards) * table.yellow_card_points
             + int(stats.red_cards) * table.red_card_points)
    own_goals = int(stats.own_goals) * table.own_goal_points

    defcon = 0
    threshold = table.defcon_thresholds.get(pos)
    if threshold is not None and stats.defensive_contribution is not None:
        if int(stats.defensive_contribution) >= threshold:
            defcon = table.defcon_points

    return PointsBreakdown(
        appearance=appearance, goals=goals, assists=assists, clean_sheet=clean_sheet,
        saves=saves, penalties_saved=pens_saved, penalties_missed=pens_missed,
        goals_conceded=conceded, cards=cards, own_goals=own_goals,
        defensive_contribution=defcon, bonus=int(stats.bonus),
    )
