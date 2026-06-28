"""Capa de insight — más allá de "el mejor avanza".

- Valor vs mercado: dónde el modelo discrepa del consenso (edge para la polla).
- Suerte/regresión: goles reales − xG (quién sobre/infra-rinde y va a regresar).
- Camino de bracket: dificultad relativa (fuerza de rivales esperados).
"""
from __future__ import annotations

from .market import p_market_winner
from . import elo, simulate


def luck_table(conn) -> dict:
    """team → (goles_favor, xGF, dif_favor, goles_contra, xGA, dif_contra) en el torneo."""
    # goles reales por equipo (de matches jugados)
    goals = {}
    for h, a, hs, as_ in conn.execute(
            "SELECT home_team, away_team, home_score, away_score FROM matches WHERE n_events>0"):
        if hs is None:
            continue
        goals.setdefault(h, [0, 0]); goals.setdefault(a, [0, 0])
        goals[h][0] += hs; goals[h][1] += as_
        goals[a][0] += as_; goals[a][1] += hs
    # xG por equipo (de shot_xg, agregado por partido para xGA)
    xg = {}
    bym = {}
    for mid, team, s in conn.execute(
            "SELECT match_id, team, SUM(xg_model) FROM shot_xg WHERE source='whoscored' GROUP BY match_id, team"):
        bym.setdefault(mid, []).append((team, s or 0))
    for lst in bym.values():
        if len(lst) != 2:
            continue
        (ta, xa), (tb, xb) = lst
        for t, f, a in ((ta, xa, xb), (tb, xb, xa)):
            d = xg.setdefault(t, [0.0, 0.0]); d[0] += f; d[1] += a
    out = {}
    for t in goals:
        gf, ga = goals[t]
        xf, xa = xg.get(t, [0.0, 0.0])
        out[t] = dict(gf=gf, xgf=round(xf, 1), over_att=round(gf - xf, 1),
                      ga=ga, xga=round(xa, 1), over_def=round(ga - xa, 1))
    return out


def report(conn, run_id: str) -> str:
    sim = {t: dict(champ=c, final=f) for t, c, f in conn.execute(
        "SELECT team, p_champion, p_final FROM tournament_sim WHERE run_id=?", (run_id,))}
    mkt = p_market_winner(conn)
    luck = luck_table(conn)
    ranks = elo.get_ranks(conn)

    lines = ["# Insight del modelo — más allá de la fuerza\n"]
    # 1) Valor vs mercado
    lines.append("## Valor vs mercado (P campeón: modelo anclado − mercado)\n")
    lines.append("| Equipo | Modelo | Mercado | Δ valor |")
    lines.append("|---|---|---|---|")
    rows = []
    for t, d in sim.items():
        m = mkt.get(t)
        if m:
            rows.append((t, d["champ"], m, d["champ"] - m))
    for t, c, m, v in sorted(rows, key=lambda r: -abs(r[3]))[:10]:
        flag = "🟢 infravalorado" if v > 0.01 else ("🔴 caro" if v < -0.01 else "≈")
        lines.append(f"| {t} | {c*100:.1f}% | {m*100:.1f}% | {v*100:+.1f}pp {flag} |")

    # 2) Suerte / regresión
    lines.append("\n## Suerte / regresión (goles − xG en el torneo)\n")
    lines.append("| Equipo | Goles | xG | Δ ataque | GC | xGA | Δ defensa |")
    lines.append("|---|---|---|---|---|---|---|")
    for t, l in sorted(luck.items(), key=lambda kv: -abs(kv[1]["over_att"]))[:10]:
        note = " ⚠️ finaliza sobre xG (regresa)" if l["over_att"] > 2 else ""
        lines.append(f"| {t} | {l['gf']} | {l['xgf']} | {l['over_att']:+.1f}{note} "
                     f"| {l['ga']} | {l['xga']} | {l['over_def']:+.1f} |")

    # 3) Camino de bracket
    lines.append("\n## Camino de bracket (rival R32 y dificultad)\n")
    bm = {}
    for h, a in simulate.BRACKET:
        bm[h] = a; bm[a] = h
    lines.append("| Equipo | P(final) | Rival R32 | rank rival |")
    lines.append("|---|---|---|---|")
    for t in sorted(sim, key=lambda x: -sim[x]["final"])[:8]:
        opp = bm.get(t, "?")
        lines.append(f"| {t} | {sim[t]['final']*100:.0f}% | {opp} | #{ranks.get(opp,'?')} |")
    return "\n".join(lines)
