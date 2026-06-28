"""Geometría de tiro — normaliza coordenadas a metros y calcula distancia/ángulo.

Distinto grid por proveedor:
  WhoScored/Opta: 0-100 × 0-100, ataca hacia x=100, portería centro y=50.
  StatsBomb:      120 × 80,     ataca hacia x=120, portería centro y=40.
Convertimos AMBOS a metros (cancha 105×68) para que distancia/ángulo sean comparables.
"""
from __future__ import annotations

import math

from .config import PITCH_L, PITCH_W, GOAL_W


def ws_to_xy(x: float, y: float) -> tuple[float, float]:
    """WhoScored (0-100) → (dist_x_a_linea_gol, dist_lateral_al_centro) en metros."""
    gx = (100.0 - x) * PITCH_L / 100.0
    gy = abs(y - 50.0) * PITCH_W / 100.0
    return gx, gy


def sb_to_xy(x: float, y: float) -> tuple[float, float]:
    """StatsBomb (120×80) → (dist_x_a_linea_gol, dist_lateral_al_centro) en metros."""
    gx = (120.0 - x) * PITCH_L / 120.0
    gy = abs(y - 40.0) * PITCH_W / 80.0
    return gx, gy


def distance(gx: float, gy: float) -> float:
    """Distancia euclídea (m) al centro de la portería."""
    return math.hypot(gx, gy)


def angle(gx: float, gy: float) -> float:
    """Ángulo (rad) subtendido por los dos palos desde el punto del tiro.

    Ley de cosenos sobre el triángulo tiro–palo_izq–palo_der. Mayor ángulo → más xG.
    """
    if gx <= 0:
        return 0.0
    num = GOAL_W * gx
    den = gx * gx + gy * gy - (GOAL_W / 2.0) ** 2
    a = math.atan2(num, den)
    return a + math.pi if a < 0 else a
