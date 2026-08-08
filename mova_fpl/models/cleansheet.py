"""Porteria a cero y goles encajados. Poisson sobre el marcador del rival.

Se modela el PARTIDO, no al jugador: la porteria a cero es un suceso del equipo.
El jugador solo aporta la condicion de haber jugado 60 minutos, que viene del
modelo de minutos.

Los goles encajados restan -1 cada dos para GKP y DEF. No es -lambda/2: es
E[floor(X/2)] con X de Poisson, que no coincide con la mitad de la media. Se
calcula exacto sumando la masa, porque la aproximacion se equivoca justo en el
rango de lambdas que importa (0,8 a 2,0).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from mova_fpl.rules.base import Position

#: cola de la Poisson que se suma antes de truncar. Con lambda < 6 el resto es < 1e-9
MAX_GOLES = 25          # cubre tambien las paradas de un portero desbordado


def p_cero(lam: np.ndarray) -> np.ndarray:
    """P(el equipo no encaja) = P(X = 0) con X ~ Poisson(lambda)."""
    return np.exp(-np.asarray(lam, dtype=float))


def esperanza_division(lam: np.ndarray, divisor: int, maximo: int = MAX_GOLES) -> np.ndarray:
    """E[floor(X / divisor)] con X ~ Poisson(lambda).

    FPL redondea HACIA ABAJO en dos sitios: -1 por cada 2 goles encajados y +1 por
    cada 3 paradas. Dividir la media por el divisor sobreestima ambos, porque el
    resto se pierde en cada partido y no se acumula entre jornadas. Con lambda = 1
    y divisor 2, la esperanza real es 0,28 y la mitad de la media seria 0,50.
    """
    lam = np.asarray(lam, dtype=float)
    total = np.zeros_like(lam)
    for k in range(divisor, maximo + 1):
        pmf = np.exp(-lam + k * np.log(np.maximum(lam, 1e-12)) - math.lgamma(k + 1))
        total += (k // divisor) * pmf
    return total


def esperanza_mitades(lam: np.ndarray) -> np.ndarray:
    """E[floor(X/2)]: la penalizacion esperada por goles encajados."""
    return esperanza_division(lam, 2)


@dataclass
class CleanSheetModel:
    """Traduce el lambda de goles encajados a puntos esperados por posicion."""

    def project(self, lam_encajados: np.ndarray, posiciones, tabla) -> dict:
        """`tabla` es la ScoringTable de la temporada: los puntos no se hardcodean."""
        lam = np.asarray(lam_encajados, dtype=float)
        pcs = p_cero(lam)
        pts_cs = np.array([tabla.clean_sheet_points.get(_pos(p), 0) for p in posiciones],
                          dtype=float)
        penaliza = np.array([1.0 if _pos(p) in (Position.GKP, Position.DEF) else 0.0
                             for p in posiciones], dtype=float)
        return {
            "p_porteria_cero": pcs,
            "puntos_cs": pcs * pts_cs,
            "puntos_encajados": -esperanza_mitades(lam) * penaliza,
            "lambda_encajados": lam,
        }


def _pos(p):
    return p if isinstance(p, Position) else Position.parse(p)
