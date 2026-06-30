"""Simulación del bracket → P(avance/campeón) por equipo.

Cada cruce de eliminación se colapsa a P(avance) determinista (reg → prórroga ⅓ →
penales ~56% al favorito). Con eso, la propagación por el cuadro fijo es EXACTA por
convolución/DP (sin ruido). Monte Carlo disponible como validación.
"""
from __future__ import annotations

import datetime as dt

import numpy as np

from .config import ET_STRENGTH, PK_FAV, SEED
from . import match_model, elo

# Bracket fijo WC2026 (orden de slots; pares adyacentes → R16). Nombres canónicos.
BRACKET = [
    ("South Africa", "Canada"), ("Netherlands", "Morocco"),
    ("Germany", "Paraguay"), ("France", "Sweden"),
    ("Brazil", "Japan"), ("Ivory Coast", "Norway"),
    ("Mexico", "Ecuador"), ("England", "DR Congo"),
    ("Portugal", "Croatia"), ("Spain", "Austria"),
    ("USA", "Bosnia and Herzegovina"), ("Belgium", "Senegal"),
    ("Australia", "Egypt"), ("Argentina", "Cabo Verde"),
    ("Switzerland", "Algeria"), ("Colombia", "Ghana"),
]
ROUNDS = ["p_r16", "p_qf", "p_sf", "p_final", "p_champion"]   # 32→1 = 5 rondas


def advance_prob(ra: float, rb: float, params: dict) -> float:
    """P(equipo A avanza) en eliminación (neutral): reg → ET(⅓) → penales."""
    dr = elo.dr(ra, rb, neutral=True)
    pa, pd, pb = match_model.predict_1x2(dr, params)            # regulación
    # prórroga: mismas fuerzas, ⅓ de goles
    lh, la = match_model.lambdas(dr, params)
    M = match_model.score_matrix(lh * ET_STRENGTH, la * ET_STRENGTH, params["rho"])
    ea, ed, eb = match_model.p_1x2(M)
    pk_a = PK_FAV if ra >= rb else (1 - PK_FAV)
    return pa + pd * (ea + ed * pk_a)


def _adv_from_1x2(ph, pd, pa, ra, rb):
    """1X2 (regulación) → P(avance) repartiendo el empate con penales por favorito."""
    pk = PK_FAV if ra >= rb else (1 - PK_FAV)
    return ph + pd * pk


def inplay_advance(ra, rb, params, hs, as_, minute) -> float:
    """P(equipo local avanza | marcador actual hs-as_ y minuto). Poisson de tiempo restante."""
    import numpy as np
    frac = max(0.0, (90 - minute)) / 90.0
    dr = elo.dr(ra, rb, neutral=True)
    lh, la = match_model.lambdas(dr, params)
    M = match_model.score_matrix(lh * frac, la * frac, params["rho"])   # goles RESTANTES
    ph = pd = pa = 0.0
    for x in range(M.shape[0]):
        for y in range(M.shape[1]):
            fh, fa = hs + x, as_ + y
            if fh > fa: ph += M[x, y]
            elif fh == fa: pd += M[x, y]
            else: pa += M[x, y]
    return _adv_from_1x2(ph, pd, pa, ra, rb)


def market_advance(conn, run_id: str) -> dict:
    """{frozenset(par): (local, P(local avanza))} desde match_predictions con mercado."""
    out = {}
    for h, a, ph, pdr, pa in conn.execute(
            """SELECT home_team, away_team, p_home, p_draw, p_away FROM match_predictions
               WHERE run_id=? AND p_home_mkt IS NOT NULL""", (run_id,)):
        out[frozenset((h, a))] = (h, _adv_from_1x2(ph, pdr, pa, 1, 1))   # pk 50/50 (no rating aquí)
    return out


def live_advance_map(live_rows, eff_ratings, params, resolve) -> dict:
    """{frozenset(par): (local, P(local avanza | en vivo))} para partidos status-3."""
    out = {}
    for m in live_rows:
        h, a = resolve(m["home"]), resolve(m["away"])
        if not h or not a or h not in eff_ratings or a not in eff_ratings:
            continue
        if m["home_score"] is None or m["away_score"] is None:
            continue
        p = inplay_advance(eff_ratings[h], eff_ratings[a], params,
                           m["home_score"], m["away_score"], m["minute"])
        out[frozenset((h, a))] = (h, p)
    return out


def _slots(eff_ratings):
    """Aplana el bracket a 32 equipos en orden de slot."""
    teams = []
    for h, a in BRACKET:
        teams += [h, a]
    return teams


def decided_matches(conn) -> dict:
    """Resultados de eliminación YA finalizados (FT) → {frozenset(par): ganador}.

    Solo partidos realmente terminados (is_finished=1). Los EN VIVO no se congelan.
    """
    out = {}
    for h, a, hs, as_, pk in conn.execute(
            """SELECT home_team, away_team, home_score, away_score, pk_score
               FROM matches WHERE round='knockout' AND is_finished=1
               AND home_score IS NOT NULL"""):
        if hs > as_:
            w = h
        elif as_ > hs:
            w = a
        else:                            # empate → definido por penales
            try:
                ph, pa_ = (pk or "0:0").split(":")
                w = h if int(ph) > int(pa_) else a
            except (ValueError, AttributeError):
                continue
        out[frozenset((h, a))] = w
    return out


def run_dp(conn, eff_ratings: dict, params: dict, decided: dict | None = None,
           live: dict | None = None, market: dict | None = None) -> dict:
    """Probabilidades EXACTAS de avance por convolución sobre el bracket fijo.

    Jerarquía de info por partido: FT(real) > en vivo > mercado h2h > modelo.
      decided: {frozenset: ganador} (FT). live/market: {frozenset: (local, P(local avanza))}.
    """
    decided = decided or {}
    live = live or {}
    market = market or {}
    teams = _slots(eff_ratings)
    cache = {}
    def adv(a, b):
        pair = frozenset((a, b))
        if pair in decided:              # 1) partido FT → resultado real
            return 1.0 if decided[pair] == a else 0.0
        for src in (live, market):       # 2) en vivo  3) mercado h2h
            if pair in src:
                ref, p = src[pair]
                return p if ref == a else 1.0 - p
        if (a, b) not in cache:          # 4) modelo
            cache[(a, b)] = advance_prob(eff_ratings[a], eff_ratings[b], params)
        return cache[(a, b)]

    reach = {t: [0.0] * (len(ROUNDS) + 1) for t in teams}
    for t in teams:
        reach[t][0] = 1.0                # todos entran a R32
    n_rounds = len(ROUNDS)               # 5
    for r in range(n_rounds):
        block = 2 ** (r + 1)
        for i, t in enumerate(teams):
            blk_start = (i // block) * block
            half = blk_start + (block // 2)
            opp_slots = range(blk_start, half) if i >= half else range(half, blk_start + block)
            p = 0.0
            for j in opp_slots:
                o = teams[j]
                if reach[o][r] > 0:
                    p += reach[o][r] * adv(t, o)
            reach[t][r + 1] = reach[t][r] * p
    return {t: reach[t][1:] for t in teams}   # [p_r16,p_qf,p_sf,p_final,p_champion]


def anchor_to_market(conn, eff_ratings, params, market_champ: dict,
                     w: float = 0.65, iters: int = 40, step: float = 70.0,
                     decided: dict | None = None, live: dict | None = None,
                     market: dict | None = None) -> tuple[dict, dict]:
    """Ajusta fuerzas para que la simulación reproduzca log-pool(modelo, mercado).

    Mantiene consistencia entre rondas (todo sale de UNA simulación con las fuerzas
    ajustadas) y ancla el campeón al mercado. Devuelve (ratings_anclados, target).
    """
    import math
    teams = _slots(eff_ratings)
    base = run_dp(conn, eff_ratings, params, decided, live, market)
    model_c = {t: max(base[t][4], 1e-6) for t in teams}
    # objetivo = log-pool por equipo, renormalizado
    tgt = {}
    for t in teams:
        mc = market_champ.get(t)
        tgt[t] = model_c[t] if mc is None else (model_c[t] ** (1 - w)) * (max(mc, 1e-6) ** w)
    s = sum(tgt.values())
    tgt = {t: v / s for t, v in tgt.items()}

    r = dict(eff_ratings)
    logit = lambda p: math.log(min(max(p, 1e-6), 1 - 1e-6) / (1 - min(max(p, 1e-6), 1 - 1e-6)))
    for _ in range(iters):
        probs = run_dp(conn, r, params, decided, live, market)
        for t in teams:
            r[t] += step * (logit(tgt[t]) - logit(probs[t][4]))
    return r, tgt


def fill_bracket(eff_ratings, params, decided=None, live=None, market=None):
    """Bracket más probable: en cada cruce elige el favorito (o el ganador real si FT).

    Devuelve (rondas, campeón). Cada ronda = lista de ((a,b), ganador, prob_ganador).
    Jerarquía: FT real > en vivo > mercado h2h > modelo.
    """
    decided = decided or {}; live = live or {}; market = market or {}

    def pick(a, b):
        pair = frozenset((a, b))
        if pair in decided:
            w = decided[pair]; return w, 1.0
        for src in (live, market):
            if pair in src:
                ref, p = src[pair]
                p_a = p if ref == a else 1 - p
                return (a, p_a) if p_a >= 0.5 else (b, 1 - p_a)
        p_a = advance_prob(eff_ratings[a], eff_ratings[b], params)
        return (a, p_a) if p_a >= 0.5 else (b, 1 - p_a)

    rounds = []
    pairs = list(BRACKET)
    labels = ["16vos", "Octavos", "Cuartos", "Semifinal", "Final"]
    teams_pairs = pairs
    for lab in labels:
        res = [(ab[0], ab[1], *pick(ab[0], ab[1])) for ab in teams_pairs]
        rounds.append((lab, res))
        winners = [r[2] for r in res]
        if len(winners) <= 1:
            break
        teams_pairs = [(winners[i], winners[i + 1]) for i in range(0, len(winners), 2)]
    champion = rounds[-1][1][0][2]
    return rounds, champion


def run_mc(conn, eff_ratings, params, n_sims=10000, seed=SEED) -> dict:
    """Monte Carlo (validación del DP)."""
    rng = np.random.default_rng(seed)
    teams0 = _slots(eff_ratings)
    counts = {t: [0] * len(ROUNDS) for t in teams0}
    padv = {}
    def adv(a, b):
        if (a, b) not in padv:
            padv[(a, b)] = advance_prob(eff_ratings[a], eff_ratings[b], params)
        return padv[(a, b)]
    for _ in range(n_sims):
        alive = list(teams0)
        for r in range(len(ROUNDS)):
            nxt = []
            for k in range(0, len(alive), 2):
                a, b = alive[k], alive[k + 1]
                w = a if rng.random() < adv(a, b) else b
                nxt.append(w)
                counts[w][r] += 1
            alive = nxt
    return {t: [counts[t][r] / n_sims for r in range(len(ROUNDS))] for t in teams0}


def write(conn, run_id: str, probs: dict, n_sims: int, seed: int, method="dp"):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    rows = [(t, run_id, n_sims, *probs[t], 1.0, seed, now) for t in probs]
    conn.executemany(
        """INSERT OR REPLACE INTO tournament_sim
           (team, run_id, n_sims, p_r16, p_qf, p_sf, p_final, p_champion,
            p_group_adv, seed, generated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""", rows)
    conn.commit()
    return {"teams": len(rows), "method": method}
