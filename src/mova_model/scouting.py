"""Scouting táctico por matchup desde eventos WhoScored del WC2026.

Capa de INSIGHT (no de predicción): perfil de cada equipo (zonas de ataque,
balón parado, finalización vs xG, vulnerabilidad defensiva por zona) y la lectura
del cruce. Da intuición para los picks; no pretende mover la probabilidad agregada.
"""
from __future__ import annotations

import json


def _zone(y):
    """WhoScored y: 0=derecha, 100=izquierda (vista atacante)."""
    return "der" if y < 33 else ("centro" if y < 67 else "izq")


def team_profile(conn, team: str) -> dict:
    # partidos del equipo en WC2026
    mids = [r[0] for r in conn.execute(
        "SELECT match_id FROM matches WHERE (home_team=? OR away_team=?) AND n_events>0",
        (team, team))]
    if not mids:
        return {}
    qmarks = ",".join("?" * len(mids))

    # tiros propios: zona, gol, set-piece
    atk = {"der": [0, 0], "centro": [0, 0], "izq": [0, 0]}   # [tiros, goles]
    sp_shots = 0
    own = conn.execute(
        f"""SELECT y, is_goal, qualifiers FROM events
            WHERE is_shot=1 AND team_name=? AND match_id IN ({qmarks})""",
        (team, *mids)).fetchall()
    for y, g, q in own:
        z = _zone(y); atk[z][0] += 1; atk[z][1] += (g or 0)
        qn = {(x.get("type") or {}).get("displayName") for x in json.loads(q or "[]")}
        if qn & {"SetPiece", "FromCorner", "DirectFreekick"}:
            sp_shots += 1

    # tiros concedidos: zona (vulnerabilidad defensiva)
    dfd = {"der": 0, "centro": 0, "izq": 0}
    conc = conn.execute(
        f"""SELECT y FROM events
            WHERE is_shot=1 AND team_name!=? AND match_id IN ({qmarks})""",
        (team, *mids)).fetchall()
    for (y,) in conc:
        dfd[_zone(y)] += 1

    # xG y finalización (team_features últimas + goles reales)
    fr = conn.execute(
        "SELECT xgf_per_match, xga_per_match FROM team_features WHERE team=? ORDER BY run_id DESC LIMIT 1",
        (team,)).fetchone() or (None, None)
    return {"team": team, "n": len(mids), "attack": atk, "sp_shots": sp_shots,
            "defense_conceded": dfd, "xgf": fr[0], "xga": fr[1],
            "total_shots": sum(v[0] for v in atk.values())}


def _goals(conn, team):
    gf = ga = 0
    for h, a, hs, as_ in conn.execute(
            "SELECT home_team,away_team,home_score,away_score FROM matches WHERE n_events>0 AND (home_team=? OR away_team=?)",
            (team, team)):
        if hs is None:
            continue
        if h == team:
            gf += hs; ga += as_
        else:
            gf += as_; ga += hs
    return gf, ga


def matchup(conn, a: str, b: str) -> str:
    """Lectura por dimensiones que DISCRIMINAN (no la zona de tiro, que siempre da centro)."""
    pa, pb = team_profile(conn, a), team_profile(conn, b)
    if not pa or not pb:
        return f"Sin datos para {a} o {b}"
    L = [f"# Scouting {a} vs {b}  (eventos WC2026)\n",
         "| Dimensión | %s | %s |" % (a, b), "|---|---|---|"]
    for key, lab, fmt in [("xgf", "Ataque (xGF/p)", "{:.2f}"),
                          ("xga", "Defensa (xGA/p, ↓mejor)", "{:.2f}")]:
        L.append(f"| {lab} | {fmt.format(pa[key])} | {fmt.format(pb[key])} |")
    for p, other in ((pa, "a"), (pb, "b")):
        pass
    # balón parado: % de tiros de ABP
    spa = pa["sp_shots"] * 100 // (pa["total_shots"] or 1)
    spb = pb["sp_shots"] * 100 // (pb["total_shots"] or 1)
    L.append(f"| Dependencia ABP (% tiros) | {spa}% | {spb}% |")
    # finalización vs xG (regresión)
    gfa, _ = _goals(conn, a); gfb, _ = _goals(conn, b)
    fina = gfa - pa["xgf"] * pa["n"]; finb = gfb - pb["xgf"] * pb["n"]
    L.append(f"| Finalización (goles − xG) | {fina:+.1f} | {finb:+.1f} |")
    L.append(f"| Tiros/partido | {pa['total_shots']/pa['n']:.0f} | {pb['total_shots']/pb['n']:.0f} |")

    L.append("\n## Lectura accionable")
    # goles proyectados = promedio(ataque propio, defensa que concede el rival)
    ga_proj = (pa["xgf"] + pb["xga"]) / 2     # goles esperados de A
    gb_proj = (pb["xgf"] + pa["xga"]) / 2     # goles esperados de B
    if ga_proj >= gb_proj:
        L.append(f"- **{a}** tiene la ventaja de matchup (goles proyectados {ga_proj:.2f} vs {gb_proj:.2f}): "
                 f"su ataque {pa['xgf']:.2f} + la defensa de {b} ({pb['xga']:.2f} concedidos).")
    else:
        L.append(f"- **{b}** tiene la ventaja de matchup (goles proyectados {gb_proj:.2f} vs {ga_proj:.2f}): "
                 f"su ataque {pb['xgf']:.2f} + la defensa de {a} ({pa['xga']:.2f} concedidos).")
    for nm, fin in ((a, fina), (b, finb)):
        if fin > 2:
            L.append(f"- ⚠️ **{nm}** finaliza +{fin:.1f} sobre xG → caliente, riesgo de regresión (no sobre-confiar).")
    if abs(spa - spb) >= 8:
        dep = a if spa > spb else b
        L.append(f"- **{dep}** depende más del balón parado ({max(spa,spb)}%) → clave su ABP / la defensa de ABP rival.")
    L.append(f"\n> Scouting = intuición para el pick, NO ajuste de probabilidad "
             f"(la señal de 3 partidos ya está en el mercado anclado; el backtest mostró que no mejora el RPS).")
    return "\n".join(L)
