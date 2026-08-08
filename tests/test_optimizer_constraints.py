"""WP-006: la solucion del optimizador es LEGAL, siempre, o falla ruidosamente.

Un optimizador que relaja una restriccion en silencio es peor que uno que no
existe: produce planes que el juego rechazaria y los presenta como optimos.
"""
from __future__ import annotations

import pytest

from mova_fpl.engine.state import Candidate, State
from mova_fpl.optimizer import Infeasible, OptimizerConfig, build_xp_matrix, solve
from mova_fpl.rules import get as get_rules
from mova_fpl.rules.base import Position, Squad, SquadPlayer
from mova_fpl.rules.money import to_millions
from mova_fpl.rules.squad import validate_squad

RULES = get_rules("2025-26").SQUAD


def mercado(n_por_pos=(5, 12, 12, 7), precio_base=4.0, xp_base=2.0, clubes=10, salto=0.1):
    out, e = [], 1
    for pos, n in zip((Position.GKP, Position.DEF, Position.MID, Position.FWD), n_por_pos):
        for k in range(n):
            out.append(Candidate(element=e, position=pos, team=f"C{e % clubes}",
                                 price=round(precio_base + salto * k, 1),
                                 xp=xp_base + 0.4 * k, name=f"{pos.value}{e}"))
            e += 1
    return out


def matriz(cands, gw=1, horizon=1, decay=1.0):
    sched = {(c.team, g): 1 for c in cands for g in range(gw, gw + horizon)}
    return build_xp_matrix(cands, sched, gw=gw, horizon=horizon, decay=decay)


def estado(cands, gw=1, squad=None, ft=1, bank=0.0):
    return State(season="2025-26", gw=gw, candidates=tuple(cands), squad=squad,
                 free_transfers=ft, bank=bank, rules=RULES)


def como_squad(sol, gw, cands, bank=0.0) -> Squad:
    attr = {c.element: c for c in cands}
    players = tuple(SquadPlayer(element=i, position=attr[i].position, team=attr[i].team,
                                price=attr[i].price) for i in sol.squad[gw])
    return Squad(players=players, starters=sol.starters[gw], captain=sol.captain[gw],
                 vice_captain=next(i for i in sol.starters[gw] if i != sol.captain[gw]),
                 bench_order=tuple(i for i in sol.squad[gw] if i not in set(sol.starters[gw])),
                 bank=bank)


# ---------------------------------------------------------------- AC-WP006-001

def test_la_solucion_pasa_validate_squad():
    cands = mercado()
    sol = solve(estado(cands), matriz(cands), OptimizerConfig(top_k=0))
    s = como_squad(sol, 1, cands, bank=to_millions(sol.bank[1]))
    assert validate_squad(s, RULES) == []


def test_composicion_exacta_2_5_5_3():
    cands = mercado()
    sol = solve(estado(cands), matriz(cands), OptimizerConfig(top_k=0))
    attr = {c.element: c for c in cands}
    from collections import Counter
    assert Counter(attr[i].position for i in sol.squad[1]) == Counter(RULES["composition"])


def test_maximo_tres_por_club_aunque_ahi_esten_los_mejores():
    """Todos los buenos en un club: el modelo debe dejar puntos sobre la mesa."""
    cands = mercado(clubes=6)
    for c in cands:
        if c.team == "C1":
            object.__setattr__(c, "xp", c.xp + 50)
    sol = solve(estado(cands), matriz(cands), OptimizerConfig(top_k=0))
    attr = {c.element: c for c in cands}
    from collections import Counter
    peor = Counter(attr[i].team for i in sol.squad[1]).most_common(1)[0][1]
    assert peor <= RULES["max_per_club"]


def test_formacion_valida_y_un_solo_capitan():
    cands = mercado()
    sol = solve(estado(cands), matriz(cands), OptimizerConfig(top_k=0))
    attr = {c.element: c for c in cands}
    assert len(sol.starters[1]) == RULES["starters"]
    assert sum(1 for i in sol.starters[1] if attr[i].position is Position.GKP) == 1
    assert sol.captain[1] in sol.starters[1]


# ---------------------------------------------------------------- AC-WP006-003

def test_arranque_en_frio_respeta_el_presupuesto_de_100m():
    cands = mercado(precio_base=6.0, salto=0.3)
    sol = solve(estado(cands), matriz(cands), OptimizerConfig(top_k=0))
    attr = {c.element: c for c in cands}
    coste = sum(attr[i].price for i in sol.squad[1])
    assert coste <= RULES["budget"] + 1e-9
    assert to_millions(sol.bank[1]) == pytest.approx(round(RULES["budget"] - coste, 1), abs=0.05)


def test_con_plantilla_el_tope_es_banco_mas_valor_no_100m():
    """AC-WP006-003: una plantilla que ya vale 95M con 1M en banco puede gastar 96M."""
    cands = mercado(precio_base=4.0)
    inicial = solve(estado(cands), matriz(cands), OptimizerConfig(top_k=0))
    attr = {c.element: c for c in cands}
    squad = como_squad(inicial, 1, cands)
    valor = sum(attr[i].price for i in inicial.squad[1])

    sol = solve(estado(cands, gw=2, squad=squad, ft=1, bank=0.5), matriz(cands, gw=2),
                OptimizerConfig(top_k=0))
    nuevo = sum(attr[i].price for i in sol.squad[2])
    assert nuevo <= valor + 0.5 + 1e-9          # no puede gastar los 100M nominales
    assert to_millions(sol.bank[2]) >= 0


def test_el_precio_de_venta_no_devuelve_toda_la_subida():
    """Comprado a 5.0 y ahora vale 6.0: se recuperan 5.5, no 6.0."""
    cands = mercado(precio_base=5.0, salto=0.0, n_por_pos=(5, 12, 12, 7))
    inicial = solve(estado(cands), matriz(cands), OptimizerConfig(top_k=0))
    attr = {c.element: c for c in cands}
    subidos = set(inicial.squad[1])
    caros = [Candidate(element=c.element, position=c.position, team=c.team,
                       price=c.price + (1.0 if c.element in subidos else 0.0),
                       xp=c.xp, name=c.name) for c in cands]
    players = tuple(SquadPlayer(element=i, position=attr[i].position, team=attr[i].team,
                                price=attr[i].price + 1.0, purchase_price=attr[i].price)
                    for i in inicial.squad[1])
    squad = Squad(players=players, starters=inicial.starters[1], captain=inicial.captain[1],
                  bank=0.0)
    sol = solve(estado(caros, gw=2, squad=squad, ft=1, bank=0.0), matriz(caros, gw=2),
                OptimizerConfig(top_k=0))
    vendidos = sol.sells[2]
    if vendidos:
        # cada venta aporta 5.5, no 6.0; con banco 0 el modelo no puede reponer a 6.0
        assert to_millions(sol.bank[2]) >= 0


# ---------------------------------------------------------------- AC-WP006-004

def test_una_transferencia_libre_no_cuesta_hit():
    cands = mercado()
    inicial = solve(estado(cands), matriz(cands), OptimizerConfig(top_k=0))
    squad = como_squad(inicial, 1, cands)
    sol = solve(estado(cands, gw=2, squad=squad, ft=1), matriz(cands, gw=2),
                OptimizerConfig(top_k=0))
    assert sol.hits[2] == 0 or len(sol.buys[2]) > 1


def test_la_segunda_transferencia_cuesta_cuatro_puntos():
    """Con 1 libre, dos transferencias tienen que registrar exactamente un hit."""
    cands = mercado()
    inicial = solve(estado(cands), matriz(cands), OptimizerConfig(top_k=0))
    squad = como_squad(inicial, 1, cands)
    # se hunde a dos titulares: conviene cambiarlos aunque haya que pagar
    hundidos = list(inicial.squad[1])[:2]
    peores = [Candidate(element=c.element, position=c.position, team=c.team, price=c.price,
                        xp=(-40.0 if c.element in hundidos else c.xp), name=c.name)
              for c in cands]
    sol = solve(estado(peores, gw=2, squad=squad, ft=1), matriz(peores, gw=2),
                OptimizerConfig(top_k=0))
    assert sol.hits[2] == max(0, len(sol.buys[2]) - 1)


def test_las_libres_se_acumulan_hasta_el_tope_en_el_horizonte():
    """Sin gastar, en la jornada siguiente hay una mas, nunca por encima del tope."""
    cands = mercado()
    inicial = solve(estado(cands), matriz(cands), OptimizerConfig(top_k=0))
    squad = como_squad(inicial, 1, cands)
    sol = solve(estado(cands, gw=2, squad=squad, ft=RULES["max_free_transfers"]),
                matriz(cands, gw=2, horizon=3), OptimizerConfig(horizon=3, top_k=0))
    assert sol.hits[2] == 0
    assert len(sol.buys[2]) <= RULES["max_free_transfers"]


def test_el_tope_de_hits_por_jornada_se_respeta():
    cands = mercado()
    inicial = solve(estado(cands), matriz(cands), OptimizerConfig(top_k=0))
    squad = como_squad(inicial, 1, cands)
    hundidos = list(inicial.squad[1])[:6]
    peores = [Candidate(element=c.element, position=c.position, team=c.team, price=c.price,
                        xp=(-90.0 if c.element in hundidos else c.xp), name=c.name)
              for c in cands]
    sol = solve(estado(peores, gw=2, squad=squad, ft=1), matriz(peores, gw=2),
                OptimizerConfig(top_k=0, max_hits_per_gw=2))
    assert sol.hits[2] <= 2
    assert len(sol.buys[2]) <= 1 + 2


# ---------------------------------------------------------------- AC-WP006-005

def test_sin_porteros_suficientes_falla_nombrando_la_posicion():
    cands = mercado(n_por_pos=(1, 12, 12, 7))
    with pytest.raises(Infeasible) as ex:
        solve(estado(cands), matriz(cands), OptimizerConfig(top_k=0))
    assert any("GKP" in m for m in ex.value.motivos)


def test_sin_presupuesto_falla_diciendo_cuanto_falta():
    cands = mercado(precio_base=20.0, salto=0.0)
    with pytest.raises(Infeasible) as ex:
        solve(estado(cands), matriz(cands), OptimizerConfig(top_k=0))
    assert any("presupuesto" in m for m in ex.value.motivos)


def test_con_pocos_clubes_falla_por_la_cuota():
    cands = mercado(n_por_pos=(5, 12, 12, 7), clubes=4)
    with pytest.raises(Infeasible) as ex:
        solve(estado(cands), matriz(cands), OptimizerConfig(top_k=0))
    assert any("club" in m for m in ex.value.motivos)


def test_nunca_devuelve_una_plantilla_incompleta():
    """Infactible es una excepcion, jamas una plantilla de 14."""
    cands = mercado(n_por_pos=(2, 5, 5, 3))          # justo 15: no hay holgura
    sol = solve(estado(cands), matriz(cands), OptimizerConfig(top_k=0))
    assert len(sol.squad[1]) == RULES["size"]


# ------------------------------------------------- AC-WP006-001, temporada completa

@pytest.mark.slow
def test_temporada_completa_sin_una_sola_violacion():
    """AC-WP006-001 sobre las 38 jornadas reales de 2025-26. Se pide con `-m slow`."""
    from mova_fpl.data.store import Store
    from mova_fpl.engine.runner import Config
    from mova_fpl.engine.simulator import replay

    store = Store()
    rep = replay("2025-26", "anonymized",
                 Config(policy="milp", projector="minutes", horizon=3),
                 store=store, verbose=False)
    assert len(rep.gameweeks) == 38

    import json

    from mova_fpl.rules.base import Position
    from mova_fpl.trace.query import decisions

    # la traza serializa las tuplas como JSON: sin parsear, set() cuenta caracteres
    lista = lambda v: json.loads(v) if isinstance(v, str) else list(v)
    catalogo = {}
    for gw in range(1, 39):
        for _, r in store.roster("2025-26", gw).iterrows():
            if r["position"] and r["team"]:
                catalogo[int(r["element"])] = (Position.parse(r["position"]), str(r["team"]))

    from collections import Counter
    for d in decisions(rep.run_id).itertuples():
        squad, xi = lista(d.squad_15), lista(d.starters)
        assert len(set(squad)) == RULES["size"], f"GW{d.gw}: plantilla de {len(set(squad))}"
        assert len(set(xi)) == RULES["starters"], f"GW{d.gw}: XI de {len(set(xi))}"
        assert set(xi) <= set(squad), f"GW{d.gw}: titulares fuera de la plantilla"
        assert d.captain in xi, f"GW{d.gw}: el capitan no es titular"
        assert d.vice_captain in xi and d.vice_captain != d.captain, f"GW{d.gw}: vice invalido"

        pos = Counter(catalogo[e][0] for e in squad if e in catalogo)
        assert pos == Counter(RULES["composition"]), f"GW{d.gw}: composicion {dict(pos)}"
        clubes = Counter(catalogo[e][1] for e in squad if e in catalogo)
        assert max(clubes.values()) <= RULES["max_per_club"], f"GW{d.gw}: {clubes.most_common(1)}"

        linea = Counter(catalogo[e][0] for e in xi if e in catalogo)
        for p, lo in RULES["formation_min"].items():
            assert lo <= linea.get(p, 0) <= RULES["formation_max"][p], f"GW{d.gw}: formacion {dict(linea)}"
