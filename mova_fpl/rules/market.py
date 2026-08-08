"""Precios, banco y transferencias. Puro."""
from __future__ import annotations

import math


def transfer_cost(n_transfers: int, free_transfers: int, hit_cost: int = 4) -> int:
    """Penalizacion por exceder las transferencias libres."""
    return max(0, int(n_transfers) - int(free_transfers)) * hit_cost


def accumulate_free_transfers(free_transfers: int, used: int, maximum: int = 5) -> int:
    """FPL acumula transferencias libres hasta un tope."""
    restantes = max(0, int(free_transfers) - int(used))
    return min(maximum, restantes + 1)


def selling_price(purchase_price: float, current_price: float) -> float:
    """Precio de venta FPL: solo se recupera la mitad de la subida, redondeando
    hacia abajo a 0.1M. Las bajadas se asumen completas."""
    if current_price <= purchase_price:
        return round(current_price, 1)
    subida = round(current_price - purchase_price, 1)
    ganancia = math.floor(round(subida * 10) / 2) / 10
    return round(purchase_price + ganancia, 1)


def squad_value(players, use_selling_price: bool = True) -> float:
    total = 0.0
    for p in players:
        if use_selling_price and p.purchase_price is not None:
            total += selling_price(p.purchase_price, p.price)
        else:
            total += p.price
    return round(total, 1)
