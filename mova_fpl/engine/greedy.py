"""Constructor voraz de plantillas, compartido por la politica y los baselines.

Estaba duplicado y ambas copias tenian el mismo defecto: el lookahead de coste
estimaba el remanente ignorando la cuota de tres por club. El greedy aceptaba
jugadores caros creyendo que podria cerrar con un suplente barato que en
realidad estaba bloqueado, y terminaba con 14 de 15. En el backtest de 2025/26
eso dejaba el baseline template en cero en 10 de las 38 jornadas.

Aqui el lookahead consume cuotas de club al estimar, y si aun asi la pasada
queda incompleta hay una reparacion acotada que libera al jugador mas caro.

Todo el dinero se maneja en DECIMAS ENTERAS (ver rules/money.py).
"""
from __future__ import annotations

from collections import Counter

from mova_fpl.rules.money import to_tenths

MAX_REPARACIONES = 8


class SquadInfeasible(ValueError):
    """No existe plantilla valida con este mercado y presupuesto."""


def _by_position_cheapest(items) -> dict:
    """Indice por posicion ordenado por PRECIO ascendente.

    El lookahead necesita a los mas baratos. Recorrer `items` (ordenado por xp)
    hacia estimar el remanente daba 127M donde la plantilla mas barata costaba
    64M, y el greedy rechazaba a todo el mundo.
    """
    idx: dict = {}
    for it in items:
        idx.setdefault(it["pos"], []).append(it)
    for pos in idx:
        idx[pos].sort(key=lambda it: it["t"])
    return idx


def _completion_cost(cheapest, faltan, usados, clubes, max_per_club):
    """Coste minimo para cerrar las plazas restantes, respetando cuotas de club.

    Consume cuotas al estimar, asi que no es una cota inferior exacta, pero
    evita el optimismo que dejaba plantillas en 14 de 15.
    """
    uso = Counter(clubes)
    total = 0
    for pos, n in sorted(faltan.items(), key=lambda kv: -kv[1]):
        if n <= 0:
            continue
        tomados = 0
        for it in cheapest.get(pos, ()):
            if it["id"] in usados or uso[it["team"]] >= max_per_club:
                continue
            total += it["t"]
            uso[it["team"]] += 1
            tomados += 1
            if tomados == n:
                break
        if tomados < n:
            return float("inf")
    return total


def _pass(items, rules, tope, bloqueados, cheapest=None):
    """Una pasada voraz. `items` ya viene ordenado por preferencia."""
    cheapest = cheapest if cheapest is not None else _by_position_cheapest(items)
    faltan = dict(rules["composition"])
    clubes: Counter = Counter()
    usados: set = set()
    gasto = 0
    maxc = rules["max_per_club"]

    for it in items:
        if it["id"] in bloqueados or faltan.get(it["pos"], 0) <= 0:
            continue
        if clubes[it["team"]] >= maxc:
            continue
        tentativo = dict(faltan)
        tentativo[it["pos"]] -= 1
        futuro = _completion_cost(cheapest, tentativo, usados | {it["id"]} | bloqueados,
                                  clubes + Counter({it["team"]: 1}), maxc)
        if gasto + it["t"] + futuro > tope:
            continue
        usados.add(it["id"])
        gasto += it["t"]
        clubes[it["team"]] += 1
        faltan = tentativo
        if sum(faltan.values()) == 0:
            return usados, gasto, usados
    return None, gasto, usados          # parcial: sirve para reparar


def build_squad(items, rules: dict, budget: float) -> list:
    """Selecciona la plantilla. `items` = dicts con id, pos, team, price y key de orden.

    Devuelve la lista de ids. Lanza SquadInfeasible si no hay solucion.
    """
    ordenados = sorted(items, key=lambda it: (-it["key"], it["t"]))
    tope = to_tenths(budget)
    bloqueados: set = set()

    por_id = {it["id"]: it for it in ordenados}
    cheapest = _by_position_cheapest(ordenados)
    for _ in range(MAX_REPARACIONES + 1):
        elegidos, _gasto, parcial = _pass(ordenados, rules, tope, bloqueados, cheapest)
        if elegidos is not None:
            return [it["id"] for it in ordenados if it["id"] in elegidos]
        # La pasada se quedo corta: gasto de mas en alguien. Se veta al jugador
        # MAS CARO QUE ESA PASADA FICHO, no al mas caro del mercado, y se
        # reintenta. Vetar por precio global no libera presupuesto y no converge.
        if not parcial:
            break
        caro = max(parcial, key=lambda i: por_id[i]["t"])
        bloqueados.add(caro)

    raise SquadInfeasible(
        f"sin plantilla valida con {budget}M sobre {len(items)} candidatos "
        f"tras {MAX_REPARACIONES} reparaciones"
    )


def as_items(rows, id_key, pos_key, team_key, price_key, order_key) -> list[dict]:
    """Normaliza cualquier fuente (Candidate o dict de pandas) al formato interno."""
    out = []
    for r in rows:
        get = (lambda k: r[k]) if isinstance(r, dict) else (lambda k: getattr(r, k))
        out.append({"id": int(get(id_key)), "pos": get(pos_key), "team": str(get(team_key)),
                    "t": to_tenths(get(price_key)), "key": float(get(order_key))})
    return out
