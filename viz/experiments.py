"""Laboratorio de gráficos para divulgación — prototipos de grillas y cards.

Uso: python viz/experiments.py [e1|e2|e3|e4|e5|all]
Salidas: outputs/divulgacion/experiments/*.png
"""
import sys, json, sqlite3, collections
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from mplsoccer import Pitch, VerticalPitch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "divulgacion" / "experiments"
OUT.mkdir(parents=True, exist_ok=True)

BG = "#0a0a0a"
PANEL = "#111318"
LINE = "#3a3f4a"
INK = "#e8e6e3"
MUTED = "#8a8f98"
ACCENT = "#00d4a3"          # acento Orbital (verde-teal)
HEAT = "#ff5c39"            # hue secuencial para densidades
TEAM_COLORS = {
    "Spain": "#e4353f", "Argentina": "#7cc0e8", "France": "#4361ee", "England": "#c9c9c9",
    "Morocco": "#2e8b57", "Belgium": "#ffd166", "Norway": "#ef476f", "Switzerland": "#d1495b",
    "Brazil": "#ffe066", "Germany": "#9aa0a6", "Paraguay": "#e07a5f", "Cabo Verde": "#118ab2",
}

db = sqlite3.connect(ROOT / "data" / "mundial.db")
QF8 = ["Spain", "France", "Argentina", "England", "Morocco", "Belgium", "Norway", "Switzerland"]
SET12 = QF8 + ["Brazil", "Germany", "Paraguay", "Cabo Verde"]

plt.rcParams.update({
    "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG,
    "text.color": INK, "axes.edgecolor": LINE, "font.family": "DejaVu Sans",
})


def mini_pitch(ax):
    p = Pitch(pitch_type="opta", pitch_color=PANEL, line_color=LINE, linewidth=0.8)
    p.draw(ax=ax)
    return p


def footer(fig, note):
    fig.text(0.01, 0.008, f"{note} · datos: 163.688 eventos Opta · modelos propios · MOVA — Orbital Lab",
             fontsize=8, color=MUTED, ha="left")


# ---------- E1: pass networks grid (8 cuartofinalistas) ----------
def load_network(team, min_edge=8, top_players=11):
    ev = pd.read_sql("""SELECT match_id, id, event_type, outcome, team_name, player_name,
        x, y, expanded_minute*60+COALESCE(second,0) t
        FROM events WHERE team_name=? AND period!='PenaltyShootout'
        AND event_type IN ('Pass','TakeOn','Goal','MissedShots','SavedShot','ShotOnPost','BallTouch','Dispossessed')
        ORDER BY match_id, id""", db, params=(team,))
    passes = ev[(ev.event_type == "Pass") & (ev.outcome == "Successful")]
    top = passes.player_name.value_counts().head(top_players).index
    pos = passes[passes.player_name.isin(top)].groupby("player_name")[["x", "y"]].mean()
    edges = collections.Counter()
    prev = None
    for r in ev.itertuples():
        if prev is not None and r.match_id == prev.match_id and prev.event_type == "Pass" \
           and prev.outcome == "Successful" and r.player_name and prev.player_name \
           and r.player_name != prev.player_name and r.t - prev.t < 20 \
           and r.player_name in pos.index and prev.player_name in pos.index:
            edges[(prev.player_name, r.player_name)] += 1
        prev = r
    vol = passes[passes.player_name.isin(top)].player_name.value_counts()
    return pos, edges, vol


def e1_networks():
    fig, axes = plt.subplots(2, 4, figsize=(16, 10))
    fig.suptitle("LAS ARQUITECTURAS DEL MUNDIAL — redes de pases (torneo completo)", fontsize=17,
                 fontweight="bold", color=INK, y=0.98)
    for ax, team in zip(axes.flat, QF8):
        mini_pitch(ax)
        pos, edges, vol = load_network(team)
        col = TEAM_COLORS.get(team, ACCENT)
        if len(edges):
            mx = max(edges.values())
            for (a, b), w in edges.items():
                if w < 8: continue
                ax.plot([pos.loc[a, "x"], pos.loc[b, "x"]], [pos.loc[a, "y"], pos.loc[b, "y"]],
                        color=col, lw=0.4 + 4.5 * w / mx, alpha=0.18 + 0.55 * w / mx,
                        solid_capstyle="round", zorder=2)
        s = 60 + 800 * (vol / vol.max())
        ax.scatter(pos.x, pos.y, s=s.reindex(pos.index).fillna(60), color=PANEL, edgecolor=col,
                   linewidth=1.6, zorder=3)
        hub = vol.idxmax()
        ax.annotate(hub.split()[-1], (pos.loc[hub, "x"], pos.loc[hub, "y"]),
                    xytext=(0, -14), textcoords="offset points", ha="center",
                    fontsize=9, color=INK, fontweight="bold", zorder=4)
        ax.set_title(team, fontsize=13, color=col, fontweight="bold", pad=4)
    footer(fig, "nodos = posición media (tamaño ∝ volumen) · aristas = conexiones ≥8")
    fig.tight_layout(rect=[0, 0.02, 1, 0.96])
    fig.savefig(OUT / "e1_networks_grid.png", dpi=150)
    print("→ e1_networks_grid.png")


# ---------- E2: bloques defensivos ordenados por altura ----------
def e2_defensive():
    teams_h = pd.read_sql("""SELECT team_name, AVG(x) h FROM events
        WHERE event_type IN ('Tackle','Interception','BallRecovery','Clearance','BlockedPass','Challenge')
        GROUP BY team_name HAVING COUNT(*)>400""", db).set_index("team_name").h
    sel = sorted(SET12, key=lambda t: teams_h.get(t, 0))
    fig, axes = plt.subplots(3, 4, figsize=(16, 13))
    fig.suptitle("DÓNDE DEFIENDE CADA UNO — ordenados del búnker a la línea alta", fontsize=17,
                 fontweight="bold", color=INK, y=0.985)
    cmap = LinearSegmentedColormap.from_list("d", [PANEL, HEAT])
    for ax, team in zip(axes.flat, sel):
        p = mini_pitch(ax)
        da = pd.read_sql("""SELECT x, y FROM events WHERE team_name=? AND
            event_type IN ('Tackle','Interception','BallRecovery','Clearance','BlockedPass','Challenge')""",
                         db, params=(team,))
        p.kdeplot(da.x, da.y, ax=ax, fill=True, levels=60, thresh=0.05, cut=3, cmap=cmap, zorder=1)
        h = teams_h[team]
        ax.axvline(h, color=ACCENT, lw=1.6, ls="--", alpha=.9, zorder=3)
        ax.text(h + 1.5, 96, f"{h:.0f}", fontsize=10, color=ACCENT, fontweight="bold")
        ax.set_title(team, fontsize=13, color=INK, fontweight="bold", pad=4)
    footer(fig, "densidad de acciones defensivas · línea = altura defensiva media (x̄)")
    fig.tight_layout(rect=[0, 0.02, 1, 0.965])
    fig.savefig(OUT / "e2_defensive_grid.png", dpi=150)
    print("→ e2_defensive_grid.png")


# ---------- E3: pass sonars ----------
def e3_sonars():
    fig = plt.figure(figsize=(16, 13))
    fig.suptitle("LAS FIRMAS DE PASE — sonar: dirección, volumen y largo de cada equipo", fontsize=17,
                 fontweight="bold", color=INK, y=0.985)
    n_bins = 14
    cmap = LinearSegmentedColormap.from_list("s", ["#2a6f97", HEAT])
    for i, team in enumerate(SET12):
        ax = fig.add_subplot(3, 4, i + 1, projection="polar")
        ax.set_facecolor(PANEL)
        P = pd.read_sql("""SELECT x, y, end_x, end_y FROM events WHERE team_name=? AND event_type='Pass'
            AND outcome='Successful' AND end_x IS NOT NULL""", db, params=(team,))
        ang = np.arctan2(P.end_y - P.y, P.end_x - P.x)
        length = np.hypot(P.end_x - P.x, P.end_y - P.y)
        bins = np.linspace(-np.pi, np.pi, n_bins + 1)
        idx = np.digitize(ang, bins) - 1
        cnt = np.array([(idx == k).sum() for k in range(n_bins)], float)
        ln = np.array([length[idx == k].mean() if (idx == k).any() else 0 for k in range(n_bins)])
        colors = cmap((ln - 8) / 18)
        theta = (bins[:-1] + bins[1:]) / 2
        ax.bar(theta, cnt / cnt.max(), width=2 * np.pi / n_bins * 0.92, color=colors, alpha=.95)
        ax.set_theta_zero_location("E")
        ax.set_xticks([]); ax.set_yticks([]); ax.spines["polar"].set_color(LINE)
        ax.set_title(team, fontsize=13, color=TEAM_COLORS.get(team, INK), fontweight="bold", pad=10)
    footer(fig, "cada sector = dirección de pase (→ = hacia el arco rival) · largo de barra ∝ volumen · color = largo medio del pase (azul corto → rojo largo)")
    fig.tight_layout(rect=[0, 0.02, 1, 0.96])
    fig.savefig(OUT / "e3_sonars_grid.png", dpi=150)
    print("→ e3_sonars_grid.png")


# ---------- E4: España ×8 momentum ----------
def e4_spain_momentum():
    mom = json.load(open(ROOT / "outputs" / "divulgacion" / "momentum_all.json"))
    sp = [m for m in mom if m["home"] == "Spain" or m["away"] == "Spain"]
    meta = pd.read_sql("SELECT match_id, home_team, away_team, home_score, away_score, start_utc FROM matches", db).set_index("match_id")
    sp.sort(key=lambda m: str(meta.loc[m["match_id"], "start_utc"]))
    fig, axes = plt.subplots(4, 2, figsize=(14, 16))
    fig.suptitle("ESPAÑA, PARTIDO A PARTIDO — el flujo de amenaza de todo su Mundial", fontsize=17,
                 fontweight="bold", color=INK, y=0.985)
    for ax, m in zip(axes.flat, sp):
        mm = meta.loc[m["match_id"]]
        rival = mm.away_team if mm.home_team == "Spain" else mm.home_team
        sign = 1 if mm.home_team == "Spain" else -1
        w = sorted(((int(k), v * sign) for k, v in m["windows"].items()))
        xs = [k * 5 for k, _ in w]; ys = [v for _, v in w]
        ax.bar(xs, ys, width=4.4, color=[TEAM_COLORS["Spain"] if v >= 0 else MUTED for v in ys])
        ax.axhline(0, color=LINE, lw=1)
        ax.set_ylim(-0.45, 0.45); ax.set_xticks([]); ax.set_yticks([])
        for s in ax.spines.values(): s.set_visible(False)
        score = f"{mm.home_score}-{mm.away_score}" if mm.home_team == "Spain" else f"{mm.away_score}-{mm.home_score}"
        ax.set_title(f"vs {rival}  ({score})", fontsize=12, color=INK, fontweight="bold", pad=3)
        share = sum(1 for v in ys if v > 0.02) / max(1, sum(1 for v in ys if abs(v) > 0.02))
        ax.text(0.99, 0.04, f"{share*100:.0f}% dominio", transform=ax.transAxes, ha="right",
                fontsize=10, color=TEAM_COLORS["Spain"], fontweight="bold")
    footer(fig, "barras = amenaza neta por ventana de 5' (xT de pases + xG de tiros); rojo = domina España")
    fig.tight_layout(rect=[0, 0.02, 1, 0.965])
    fig.savefig(OUT / "e4_spain_momentum.png", dpi=150)
    print("→ e4_spain_momentum.png")


# ---------- E5: Messi card ----------
def e5_messi():
    xt = np.load(ROOT / "outputs" / "divulgacion" / "xt_grid.npy")
    nx_, ny_ = xt.shape
    ev = pd.read_sql("""SELECT event_type, outcome, x, y, end_x, end_y, is_goal FROM events
        WHERE player_name='Lionel Messi' AND period!='PenaltyShootout'""", db)
    fig = plt.figure(figsize=(14, 9))
    fig.suptitle("MESSI · 39 AÑOS · EL MAPA DEL MAGO", fontsize=18, fontweight="bold", color=INK, y=0.97)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.4, 1])

    ax1 = fig.add_subplot(gs[0])
    p = mini_pitch(ax1)
    touches = ev[ev.x.notna()]
    cmap = LinearSegmentedColormap.from_list("m", [PANEL, "#7cc0e8"])
    p.kdeplot(touches.x, touches.y, ax=ax1, fill=True, levels=60, thresh=0.05, cut=3, cmap=cmap, zorder=1)
    P = ev[(ev.event_type == "Pass") & (ev.outcome == "Successful") & ev.end_x.notna()].copy()
    def zv(x, y): return xt[np.clip((x / 100 * nx_).astype(int), 0, nx_ - 1), np.clip((y / 100 * ny_).astype(int), 0, ny_ - 1)]
    P["gain"] = zv(P.end_x.values, P.end_y.values) - zv(P.x.values, P.y.values)
    top = P.nlargest(12, "gain")
    for r in top.itertuples():
        p.arrows(r.x, r.y, r.end_x, r.end_y, ax=ax1, color=ACCENT, width=1.6,
                 headwidth=6, headlength=6, alpha=.85, zorder=3)
    ax1.set_title("Territorio (densidad de acciones) + sus 12 pases de mayor amenaza (xT)",
                  fontsize=11, color=MUTED, pad=6)

    ax2 = fig.add_subplot(gs[1])
    mini_pitch(ax2)
    sh = ev[ev.event_type.isin(["Goal", "MissedShots", "SavedShot", "ShotOnPost"])]
    goals = sh[ev.event_type == "Goal"]
    others = sh[ev.event_type != "Goal"]
    ax2.scatter(others.x, others.y, s=90, color=PANEL, edgecolor=MUTED, lw=1.4, zorder=3)
    ax2.scatter(goals.x, goals.y, s=160, color="#7cc0e8", edgecolor=INK, lw=1.2, zorder=4)
    ax2.set_xlim(45, 102)
    ax2.set_title("Sus tiros (celeste = gol: 8, siete de zurda)", fontsize=11, color=MUTED, pad=6)

    fig.text(0.5, 0.055, "•  #1 del Mundial en amenaza generada por pase (5.40 xT)   •   28 regates (líder)   •   20 faltas recibidas (líder)",
             ha="center", fontsize=12, color=INK, fontweight="bold")
    footer(fig, "xT: modelo propio (Markov 16×12 entrenado con el torneo)")
    fig.tight_layout(rect=[0, 0.07, 1, 0.94])
    fig.savefig(OUT / "e5_messi_card.png", dpi=150)
    print("→ e5_messi_card.png")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    fns = dict(e1=e1_networks, e2=e2_defensive, e3=e3_sonars, e4=e4_spain_momentum, e5=e5_messi)
    for k, fn in fns.items():
        if which in ("all", k):
            fn()
