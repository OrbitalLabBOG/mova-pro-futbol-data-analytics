"""Aritmetica de dinero en decimas enteras. Puro.

FPL opera en unidades de 0.1M: `value=42` significa 4.2M. Convertir a float y
sumar quince veces acumula error suficiente para que 95.8 + 4.2 de
100.00000000000001 y una plantilla valida se rechace por presupuesto.

Ese bug se observo en la primera corrida del harness: el baseline template
devolvia 0 en 14 de 38 jornadas porque se quedaba en 14/15 jugadores.

Regla: el dinero se compara y se acumula SIEMPRE en decimas enteras.
"""
from __future__ import annotations


def to_tenths(millions: float) -> int:
    """4.2 -> 42. Redondeo al entero mas cercano, no truncamiento."""
    return int(round(float(millions) * 10))


def to_millions(tenths: int) -> float:
    return round(int(tenths) / 10.0, 1)
