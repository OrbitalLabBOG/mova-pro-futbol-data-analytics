"""Explora la red de pases de las 48 selecciones y encuentra los arquetipos más dispares.

Uso: python viz/redes_48.py [metrics|draw equipo1,equipo2,...]
"""
import sys, sqlite3, collections
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mplsoccer import Pitch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "divulgacion" / "experiments"
db = sqlite3.connect(ROOT / "data" / "mundial.db")

BG, LINE, INK, MUTED, MINT = "#07090c", "#2a3038", "#e8e6e3", "#8a8f98", "#3ceb8c"
HUB_C = "#ffffff"
TEAM_COLORS = {"Spain": "#e4353f", "Paraguay": "#8e2438", "Netherlands": "#ff7f2a",
               "Morocco": "#2e9e63", "Argentina": "#7cc0e8", "Colombia": "#ffd166"}
plt.rcParams.update({"figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG,
                     "text.color": INK, "font.family": "DejaVu Sans"})

ONBALL = ("Pass", "TakeOn", "Goal", "MissedShots", "SavedShot", "BallTouch", "Dispossessed")


def network(team):
    ev = pd.read_sql(f"""SELECT match_id, id, event_type, outcome, player_name, x, y,
        expanded_minute*60+COALESCE(second,0) t FROM events
        WHERE team_name=? AND period!='PenaltyShootout'
        AND event_type IN {ONBALL} ORDER BY match_id, id""", db, params=(team,))
    n_matches = ev.match_id.nunique()
    passes = ev[(ev.event_type == "Pass") & (ev.outcome == "Successful")]
    top = passes.player_name.value_counts().head(11).index
    pos = passes[passes.player_name.isin(top)].groupby("player_name")[["x", "y"]].mean()
    edges = collections.Counter(); deg_full = collections.Counter(); prev = None
    for r in ev.itertuples():
        if prev is not None and r.match_id == prev.match_id and prev.event_type == "Pass" \
           and prev.outcome == "Successful" and r.player_name and prev.player_name \
           and r.player_name != prev.player_name and r.t - prev.t < 20:
            deg_full[prev.player_name] += 1; deg_full[r.player_name] += 1
            if r.player_name in pos.index and prev.player_name in pos.index:
                a, b = sorted([prev.player_name, r.player_name])
                edges[(a, b)] += 1
        prev = r
    vol = passes[passes.player_name.isin(top)].player_name.value_counts()
    return pos, edges, vol, n_matches, len(passes), deg_full


def metrics():
    teams = [r[0] for r in db.execute("""SELECT team_name FROM events
        GROUP BY team_name HAVING COUNT(*) > 3000 AND team_name IS NOT NULL""")]
    rows = []
    for team in teams:
        pos, edges, vol, nm, npass, deg_full = network(team)
        if not edges or nm == 0: continue
        w = pd.Series(edges)
        wpm = w / nm                                   # peso por partido
        strong = (wpm >= 4).sum()                      # conexiones fuertes
        tot = sum(deg_full.values())
        hub, hubw = max(deg_full.items(), key=lambda kv: kv[1])
        # largo geometrico medio de las conexiones fuertes
        lens = [np.hypot(*(pos.loc[a] - pos.loc[b])) for (a, b), c in edges.items() if c / nm >= 4]
        rows.append(dict(team=team, matches=nm, passes_pm=round(npass / nm),
                         central=round(hubw / tot * 100, 1), hub=hub,
                         hub_x=round(pos.loc[hub, "x"], 1),
                         strong_links=strong, link_len=round(np.mean(lens), 1) if lens else 0,
                         height=round(pos.x.mean(), 1), spread=round(pos.y.std(), 1)))
    df = pd.DataFrame(rows).set_index("team")
    df.to_csv(OUT / "redes_metrics.csv")
    pd.set_option("display.width", 150)
    print("== MAS CENTRALIZADAS (dependen de un hub) ==\n", df.nlargest(5, "central")[["central", "hub", "hub_x", "strong_links"]])
    print("\n== MAS REPARTIDAS ==\n", df.nsmallest(5, "central")[["central", "hub", "strong_links"]])
    print("\n== MAS DENSAS (conexiones fuertes/partido) ==\n", df.nlargest(5, "strong_links")[["strong_links", "passes_pm", "hub"]])
    print("\n== MAS ROTAS (pocas conexiones) ==\n", df.nsmallest(5, "strong_links")[["strong_links", "passes_pm", "hub"]])
    print("\n== HUB MAS ADELANTADO ==\n", df.nlargest(4, "hub_x")[["hub", "hub_x", "central"]])
    print("\n== HUB MAS RETRASADO ==\n", df.nsmallest(4, "hub_x")[["hub", "hub_x", "central"]])
    print("\n== RED MAS ALTA / MAS BAJA ==")
    print(df.nlargest(3, "height")[["height", "hub"]]); print(df.nsmallest(3, "height")[["height", "hub"]])
    print("\n== CONEXIONES MAS LARGAS (red estirada) ==\n", df.nlargest(4, "link_len")[["link_len", "hub"]])


def draw(teams):
    n = len(teams)
    fig, axes = plt.subplots(2, 3, figsize=(17, 11))
    for ax, team in zip(axes.flat, teams):
        import matplotlib.patheffects as pe
        col = TEAM_COLORS.get(team, MINT)
        p = Pitch(pitch_type="opta", pitch_color=BG, line_color=LINE, linewidth=0.9)
        p.draw(ax=ax)
        pos, edges, vol, nm, _, deg_full = network(team)
        if not edges: continue
        mx = max(edges.values())
        for (a, b), w in edges.items():
            if w / nm < 3: continue
            ax.plot([pos.loc[a, "x"], pos.loc[b, "x"]], [pos.loc[a, "y"], pos.loc[b, "y"]],
                    color=col, lw=.4 + 5 * w / mx, alpha=.15 + .6 * w / mx, solid_capstyle="round", zorder=2)
        hub = max((p for p in deg_full if p in pos.index), key=lambda p: deg_full[p])
        rest = pos.drop(index=hub)
        s = 60 + 900 * (vol / vol.max())
        ax.scatter(rest.x, rest.y, s=s.reindex(rest.index).fillna(60), color=BG, edgecolor=col, lw=1.6, zorder=3)
        # hub resaltado: nodo blanco relleno + halo
        ax.scatter([pos.loc[hub, "x"]], [pos.loc[hub, "y"]], s=float(s.get(hub, 500)) * 1.25,
                   color=HUB_C, edgecolor=col, lw=2.4, zorder=5)
        ax.annotate(hub.split()[-1], (pos.loc[hub, "x"], pos.loc[hub, "y"]), xytext=(0, -19),
                    textcoords="offset points", ha="center", fontsize=11, color=HUB_C,
                    fontweight="bold", zorder=6,
                    path_effects=[pe.Stroke(linewidth=3.2, foreground=BG), pe.Normal()])
        ax.set_title(team, fontsize=12.5, color=col, fontweight="bold", pad=5)
    fig.tight_layout()
    fig.savefig(OUT / "redes_candidatos.png", dpi=150)
    print("→ redes_candidatos.png")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "metrics"
    if mode == "metrics":
        metrics()
    else:
        draw(sys.argv[2].split(","))
