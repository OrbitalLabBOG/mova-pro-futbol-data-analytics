"""Métricas avanzadas para divulgación: xT propio, momentum, PPDA, cadenas, grafos, clustering.

Uso: python scripts/divulgacion_advanced.py [seccion]
Secciones: chains | ppda | xt | networks | cluster | all
Salidas: prints + artefactos JSON en outputs/divulgacion/
"""
import sys, json, sqlite3, collections
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "divulgacion"
OUT.mkdir(parents=True, exist_ok=True)

db = sqlite3.connect(ROOT / "data" / "mundial.db")
EV = pd.read_sql("""SELECT match_id, id, event_type, outcome, team_name, player_name, minute, second,
 expanded_minute, period, x, y, end_x, end_y, is_shot, is_goal, qualifiers
 FROM events WHERE period != 'PenaltyShootout' ORDER BY match_id, id""", db)
EV["t"] = EV.expanded_minute * 60 + EV.second.fillna(0)
MATCHES = pd.read_sql("SELECT match_id, home_team, away_team, home_score, away_score, round, start_utc FROM matches", db)
XG = pd.read_sql("SELECT match_id, team, minute, xg_model, is_goal FROM shot_xg WHERE play_type != 'own_goal'", db)

ONBALL = {"Pass", "TakeOn", "Goal", "MissedShots", "SavedShot", "ShotOnPost", "BallTouch",
          "Dispossessed", "KeeperPickup", "Claim", "CornerAwarded", "GoodSkill", "ChanceMissed"}
SHOTS = {"Goal", "MissedShots", "SavedShot", "ShotOnPost"}
DEFACT = {"Tackle", "Interception", "Challenge", "BlockedPass", "BallRecovery", "Clearance"}


def build_chains():
    """Cadenas de posesión: secuencias de eventos on-ball del mismo equipo."""
    chains = []
    for mid, g in EV.groupby("match_id"):
        g = g[g.event_type.isin(ONBALL)].sort_values("id")
        cur = None
        for r in g.itertuples():
            if cur is None or r.team_name != cur["team"] or r.period != cur["period"] or r.t - cur["t_end"] > 45:
                if cur: chains.append(cur)
                cur = dict(match_id=mid, team=r.team_name, period=r.period, t0=r.t, n_pass=0,
                           n_ev=0, shot=0, goal=0, x0=r.x, t_end=r.t, x_end=r.x)
            cur["n_ev"] += 1
            cur["t_end"], cur["x_end"] = r.t, (r.end_x if r.event_type == "Pass" and pd.notna(r.end_x) else r.x)
            if r.event_type == "Pass": cur["n_pass"] += 1
            if r.event_type in SHOTS: cur["shot"] = 1
            if r.event_type == "Goal": cur["goal"] = 1
        if cur: chains.append(cur)
    return pd.DataFrame(chains)


def sec_chains():
    ch = build_chains()
    ch["dur"] = (ch.t_end - ch.t0).clip(lower=1)
    ch["speed"] = (ch.x_end - ch.x0) / ch.dur  # avance vertical por segundo (% cancha/s)
    print("\n========== CADENAS DE POSESIÓN ==========")
    agg = ch.groupby("team").agg(chains=("n_ev", "size"), avg_pass=("n_pass", "mean"),
                                 shot_rate=("shot", "mean"), speed=("speed", "mean")).round(2)
    agg = agg[agg.chains > 200]
    print("\n-- Pases promedio por cadena (paciencia) --")
    print(agg.sort_values("avg_pass", ascending=False).head(6).to_string())
    print(agg.sort_values("avg_pass").head(4).to_string())
    print("\n-- Velocidad de avance (directness, %cancha/seg) --")
    print(agg.sort_values("speed", ascending=False).head(6).to_string())
    # goles por longitud de cadena
    ch["bucket"] = pd.cut(ch.n_pass, [-1, 3, 9, 99], labels=["0-3 pases", "4-9", "10+"])
    gd = ch[ch.goal == 1].groupby("bucket", observed=True).size()
    print("\n-- Goles del torneo por longitud de la cadena --\n", gd.to_string())
    g10 = ch[(ch.goal == 1) & (ch.n_pass >= 10)].groupby("team").size().sort_values(ascending=False)
    print("\n-- Goles tras cadenas de 10+ pases (orfebrería) --\n", g10.head(6).to_string())
    ch.to_json(OUT / "chains.json.gz", orient="records", compression="gzip")


def sec_ppda():
    print("\n========== PPDA REAL + ALTURA DEFENSIVA + RECOVERY ==========")
    rows = []
    for mid, g in EV.groupby("match_id"):
        teams = g.team_name.dropna().unique()
        if len(teams) != 2: continue
        for tm in teams:
            opp = [t for t in teams if t != tm][0]
            opp_pass = g[(g.team_name == opp) & (g.event_type == "Pass") & (g.x < 60)].shape[0]
            defs = g[(g.team_name == tm) & (g.event_type.isin({"Tackle", "Interception", "Challenge"})) & (g.x > 40)].shape[0]
            fouls = g[(g.team_name == tm) & (g.event_type == "Foul") & (g.outcome == "Unsuccessful") & (g.x > 40)].shape[0]
            rows.append(dict(match_id=mid, team=tm, ppda=opp_pass / max(1, defs + fouls),
                             def_h=g[(g.team_name == tm) & g.event_type.isin(DEFACT)].x.mean()))
    df = pd.DataFrame(rows)
    agg = df.groupby("team").agg(ppda=("ppda", "mean"), def_h=("def_h", "mean"), pj=("ppda", "size")).round(2)
    agg = agg[agg.pj >= 4]
    print("\n-- PPDA (menor = pressing más intenso) --")
    print(agg.sort_values("ppda").head(8).to_string())
    print("...bloques bajos:")
    print(agg.sort_values("ppda", ascending=False).head(4).to_string())
    print("\n-- Altura defensiva media (x de acciones defensivas) --")
    print(agg.sort_values("def_h", ascending=False).head(6).to_string())
    # recovery time: tiempo medio en recuperar tras perderla
    ch = build_chains()
    rec = []
    for (mid, per), g in ch.groupby(["match_id", "period"]):
        g = g.sort_values("t0").reset_index()
        for i in range(len(g) - 1):
            lost, nxt = g.loc[i], g.loc[i + 1]
            gap = nxt.t0 - lost.t_end
            if 0 <= gap <= 40:
                rec.append(dict(team=lost.team, secs=gap + (nxt.t_end - nxt.t0) * 0))
    rt = pd.DataFrame(rec).groupby("team").agg(mean_s=("secs", "mean"), n=("secs", "size")).round(1)
    rt = rt[rt.n > 300].sort_values("mean_s")
    print("\n-- Ball recovery time aprox (seg fuera de posesión por pérdida) --")
    print(rt.head(6).to_string())
    agg.to_json(OUT / "ppda.json")


def train_xt(n_iter=6, nx=16, ny=12):
    """xT propio entrenado con los 104 partidos (Markov iterativo)."""
    P = EV[(EV.event_type == "Pass") & (EV.outcome == "Successful")].dropna(subset=["x", "y", "end_x", "end_y"])
    S = EV[EV.event_type.isin(SHOTS)].dropna(subset=["x", "y"])
    def zone(x, y): return (np.clip((x / 100 * nx).astype(int), 0, nx - 1), np.clip((y / 100 * ny).astype(int), 0, ny - 1))
    pz = zone(P.x.values, P.y.values); pze = zone(P.end_x.values, P.end_y.values)
    sz = zone(S.x.values, S.y.values)
    shots = np.zeros((nx, ny)); goals = np.zeros((nx, ny)); moves = np.zeros((nx, ny))
    np.add.at(shots, sz, 1); np.add.at(goals, (sz[0], sz[1]), S.is_goal.values)
    np.add.at(moves, pz, 1)
    total = shots + moves
    p_shot = np.divide(shots, total, out=np.zeros_like(shots), where=total > 0)
    p_goal = np.divide(goals, shots, out=np.zeros_like(goals), where=shots > 0)
    T = collections.defaultdict(collections.Counter)
    for (zx, zy, ex, ey) in zip(*pz, *pze):
        T[(zx, zy)][(ex, ey)] += 1
    xt = np.zeros((nx, ny))
    for _ in range(n_iter):
        new = np.zeros((nx, ny))
        for i in range(nx):
            for j in range(ny):
                move_val = 0.0
                tot = sum(T[(i, j)].values())
                if tot:
                    move_val = sum(c / tot * xt[a, b] for (a, b), c in T[(i, j)].items())
                new[i, j] = p_shot[i, j] * p_goal[i, j] + (1 - p_shot[i, j]) * move_val
        xt = new
    np.save(OUT / "xt_grid.npy", xt)
    return xt, nx, ny


def sec_xt():
    print("\n========== xT PROPIO (entrenado con el torneo) ==========")
    xt, nx, ny = train_xt()
    P = EV[(EV.event_type == "Pass") & (EV.outcome == "Successful")].dropna(subset=["x", "y", "end_x", "end_y"]).copy()
    def zval(x, y): return xt[np.clip((x / 100 * nx).astype(int), 0, nx - 1), np.clip((y / 100 * ny).astype(int), 0, ny - 1)]
    P["xt_gain"] = (zval(P.end_x.values, P.end_y.values) - zval(P.x.values, P.y.values)).clip(0)
    top = P.groupby(["player_name", "team_name"]).xt_gain.sum().sort_values(ascending=False).head(12).round(2)
    print("\n-- TOP 12 generadores de amenaza por pase (xT sumado, el ranking de los 'motores') --")
    print(top.to_string())
    tp = P.groupby("team_name").xt_gain.sum().sort_values(ascending=False).head(8).round(1)
    print("\n-- Equipos por xT generado --\n", tp.to_string())
    # España: quién es el motor oculto
    sp = P[P.team_name == "Spain"].groupby("player_name").xt_gain.sum().sort_values(ascending=False).head(8).round(2)
    print("\n-- España: motores por xT --\n", sp.to_string())
    # MOMENTUM: xT + xG por ventana de 5' por partido → % de minutos con momentum
    P["win5"] = (P.expanded_minute // 5).astype(int)
    xgw = XG.copy(); xgw["win5"] = (xgw.minute // 5).astype(int)
    mom_rows = []
    for mid, g in P.groupby("match_id"):
        m = MATCHES[MATCHES.match_id == mid].iloc[0]
        thr = g.groupby(["team_name", "win5"]).xt_gain.sum().unstack(fill_value=0)
        xg_m = xgw[xgw.match_id == mid].groupby(["team", "win5"]).xg_model.sum().unstack(fill_value=0)
        thr = thr.add(xg_m, fill_value=0)
        if m.home_team not in thr.index or m.away_team not in thr.index: continue
        diff = thr.loc[m.home_team] - thr.loc[m.away_team]
        mom_rows.append(dict(match_id=int(mid), home=m.home_team, away=m.away_team,
                             windows=diff.round(3).to_dict()))
        if m.home_team == "Spain" and m.away_team == "Argentina":
            print("\n-- MOMENTUM DE LA FINAL (xT+xG por ventana de 5', + = España) --")
            print({int(k): round(v, 2) for k, v in diff.items()})
    json.dump(mom_rows, open(OUT / "momentum_all.json", "w"))
    # % de ventanas con momentum a favor por equipo
    dom = collections.Counter(); tot = collections.Counter()
    for row in mom_rows:
        for w, v in row["windows"].items():
            if abs(v) < 0.02: continue
            winner = row["home"] if v > 0 else row["away"]
            loser = row["away"] if v > 0 else row["home"]
            dom[winner] += 1; tot[winner] += 1; tot[loser] += 1
    share = {t: dom[t] / tot[t] for t in tot if tot[t] >= 30}
    print("\n-- %% de ventanas de 5' con momentum a favor (torneo, top 8) --")
    for t, v in sorted(share.items(), key=lambda kv: -kv[1])[:8]: print(f"  {t:<14} {v*100:.0f}%")


def sec_networks():
    print("\n========== REDES DE PASES (teoría de grafos) ==========")
    import networkx as nx_
    # inferir receptor: siguiente evento on-ball del mismo equipo en la misma cadena
    results = {}
    for team in ["Spain", "Argentina", "France", "England", "Morocco", "Brazil", "Norway"]:
        edges = collections.Counter()
        g = EV[EV.team_name == team].sort_values(["match_id", "id"])
        g = g[g.event_type.isin(ONBALL)]
        prev = None
        for r in g.itertuples():
            if prev is not None and r.match_id == prev.match_id and prev.event_type == "Pass" \
               and prev.outcome == "Successful" and r.player_name and prev.player_name \
               and r.player_name != prev.player_name and r.t - prev.t < 20:
                edges[(prev.player_name, r.player_name)] += 1
            prev = r
        G = nx_.DiGraph()
        for (a, b), w in edges.items():
            if w >= 3: G.add_edge(a, b, weight=w)
        if not G.nodes: continue
        bet = nx_.betweenness_centrality(G, weight=lambda u, v, d: 1 / d["weight"])
        deg = dict(G.degree(weight="weight"))
        tot_w = sum(deg.values())
        top_deg = sorted(deg.items(), key=lambda kv: -kv[1])[:3]
        # centralización: peso del jugador top / total (cuán 'estrella' es la red)
        central = top_deg[0][1] / tot_w if tot_w else 0
        top_bet = sorted(bet.items(), key=lambda kv: -kv[1])[:2]
        dupla = edges.most_common(1)[0]
        results[team] = dict(centralizacion=round(central * 100, 1), hub=top_deg[0][0],
                             betweenness=[b[0] for b in top_bet], dupla=f"{dupla[0][0]}→{dupla[0][1]} ({dupla[1]})")
        print(f"\n  {team}: hub={top_deg[0][0]} ({central*100:.1f}% del peso de la red) | "
              f"conectores(betweenness)={[b[0] for b in top_bet]} | dupla top={results[team]['dupla']}")
    json.dump(results, open(OUT / "networks.json", "w"), ensure_ascii=False)


def sec_cluster():
    print("\n========== CLUSTERING DE ESTILOS (KMeans + PCA) ==========")
    from sklearn.preprocessing import StandardScaler
    from sklearn.cluster import KMeans
    from sklearn.decomposition import PCA
    # vector de estilo por equipo
    feats = {}
    for team, g in EV.groupby("team_name"):
        passes = g[g.event_type == "Pass"]
        if len(passes) < 800: continue
        succ = passes[passes.outcome == "Successful"]
        shots_df = g[g.event_type.isin(SHOTS)]
        feats[team] = dict(
            possession=len(passes),
            pass_acc=len(succ) / len(passes),
            long_share=(np.hypot(succ.end_x - succ.x, succ.end_y - succ.y) > 35).mean(),
            press_h=(g[g.event_type.isin({"Tackle", "Interception", "BallRecovery"})].x > 50).mean(),
            width=passes.y.std(),
            shot_dist=np.hypot(100 - shots_df.x, 50 - shots_df.y).mean(),
            cross_share=passes.qualifiers.str.contains("Cross").mean(),
            prog_share=((succ.end_x - succ.x) > 20).mean(),
        )
    df = pd.DataFrame(feats).T
    # normalizar posesión por partidos jugados
    pj = EV.groupby("team_name").match_id.nunique()
    df["possession"] = df.possession / pj
    Xs = StandardScaler().fit_transform(df)
    km = KMeans(n_clusters=5, n_init=10, random_state=42).fit(Xs)
    df["cluster"] = km.labels_
    pca = PCA(2).fit_transform(Xs)
    df["pc1"], df["pc2"] = pca[:, 0], pca[:, 1]
    for c in sorted(df.cluster.unique()):
        members = df[df.cluster == c].index.tolist()
        print(f"  Cluster {c}: {members}")
    df.round(3).to_json(OUT / "style_clusters.json", orient="index")
    print("\n  (coordenadas PCA guardadas para scatter en outputs/divulgacion/style_clusters.json)")


if __name__ == "__main__":
    sec = sys.argv[1] if len(sys.argv) > 1 else "all"
    fns = dict(chains=sec_chains, ppda=sec_ppda, xt=sec_xt, networks=sec_networks, cluster=sec_cluster)
    for name, fn in fns.items():
        if sec in ("all", name): fn()
