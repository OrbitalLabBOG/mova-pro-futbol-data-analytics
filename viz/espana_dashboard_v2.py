"""Cap 4 v2 — set mejorado al nivel del dashboard de referencia: dorsales, badges,
zonas pintadas, mediciones. Datos reales España (torneo completo).

Uso: python viz/espana_dashboard_v2.py
Salidas: outputs/divulgacion/espana/v2_*.png + espana_grid_v2.png
"""
import sqlite3, collections, json
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from matplotlib import patches as mpatches
from mplsoccer import Pitch, VerticalPitch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "divulgacion" / "espana"
db = sqlite3.connect(ROOT / "data" / "mundial.db")

BG, LINE, INK, MUTED = "#07090c", "#2a3038", "#e8e6e3", "#8a8f98"
RED, GOLD, DIMRED, GRAY = "#e4353f", "#ffd166", "#7a2830", "#3d434d"
PATH_EFF = [pe.Stroke(linewidth=2.6, foreground=BG), pe.Normal()]

plt.rcParams.update({"figure.facecolor": "none", "axes.facecolor": "none",
                     "savefig.facecolor": "none", "text.color": INK,
                     "font.family": "DejaVu Sans"})

SP_M = pd.read_sql("""SELECT match_id, home_team, away_team, start_utc FROM matches
    WHERE home_team='Spain' OR away_team='Spain' ORDER BY start_utc""", db)

# dorsales de España (modal por jugador)
SP_TEAM_ID = db.execute("SELECT DISTINCT team_id FROM events WHERE team_name='Spain'").fetchone()[0]
DORSAL = pd.read_sql("""SELECT name, shirt_no FROM lineups WHERE team_id=? AND shirt_no IS NOT NULL""",
                     db, params=(SP_TEAM_ID,)).groupby("name").shirt_no.agg(
    lambda s: s.mode().iloc[0]).to_dict()


def dorsal(nombre):
    v = DORSAL.get(nombre)
    return str(int(v)) if v is not None else nombre.split()[-1][:3]


def save(fig, name):
    fig.savefig(OUT / name, dpi=150, transparent=True)
    plt.close(fig)
    print(f"→ {name}")


def open_play(df):
    return df[~df.qualifiers.str.contains("Corner|Freekick|ThrowIn|GoalKick|KickOff", na=False)]


EV = pd.read_sql("""SELECT match_id, id, event_type, outcome, player_name, x, y, end_x, end_y,
    qualifiers, expanded_minute AS minute, expanded_minute*60+COALESCE(second,0) t
    FROM events WHERE team_name='Spain' AND period!='PenaltyShootout' ORDER BY match_id, id""", db)


# ---------- 1. RED DE PASES PRO (dorsales + mediana + dupla gualda) ----------
def red_pro():
    fig, ax = plt.subplots(figsize=(9, 6.6))
    p = Pitch(pitch_type="opta", pitch_color="none", line_color=LINE, linewidth=1.0)
    p.draw(ax=ax)
    onball = EV[EV.event_type.isin(("Pass", "TakeOn", "Goal", "MissedShots", "SavedShot",
                                    "BallTouch", "Dispossessed"))]
    passes = onball[(onball.event_type == "Pass") & (onball.outcome == "Successful")]
    top = passes.player_name.value_counts().head(11).index
    pos = passes[passes.player_name.isin(top)].groupby("player_name")[["x", "y"]].mean()
    edges = collections.Counter(); prev = None
    for r in onball.itertuples():
        if prev is not None and r.match_id == prev.match_id and prev.event_type == "Pass" \
           and prev.outcome == "Successful" and r.player_name != prev.player_name \
           and r.player_name in pos.index and prev.player_name in pos.index and r.t - prev.t < 20:
            a, b = sorted([prev.player_name, r.player_name])
            edges[(a, b)] += 1
        prev = r
    mx = max(edges.values())
    special = tuple(sorted(["Aymeric Laporte", "Rodri"]))
    for (a, b), w in edges.items():
        if w < 25: continue
        col = GOLD if (a, b) == special else RED
        ax.plot([pos.loc[a, "x"], pos.loc[b, "x"]], [pos.loc[a, "y"], pos.loc[b, "y"]],
                color=col, lw=.6 + 7.5 * w / mx, alpha=.25 + .6 * w / mx,
                solid_capstyle="round", zorder=4 if col == GOLD else 2)
    vol = passes[passes.player_name.isin(top)].player_name.value_counts()
    s = 500 + 1500 * (vol / vol.max())
    for n, r in pos.iterrows():
        hub = n == "Rodri"
        ax.scatter(r.x, r.y, s=float(s[n]) * (1.25 if hub else 1),
                   color="white" if hub else BG, edgecolor=GOLD if hub else RED,
                   lw=2.6 if hub else 2, zorder=6)
        ax.text(r.x, r.y, dorsal(n), ha="center", va="center", fontsize=12,
                color=BG if hub else INK, fontweight="bold", zorder=7)
    # linea de altura mediana de pases + medida
    med = passes.x.median()
    ax.axvline(med, color=MUTED, lw=1.4, ls="--", alpha=.8)
    ax.annotate(f"{med:.1f}", xy=(med, 101.5), ha="center", fontsize=11, color=MUTED,
                fontweight="bold")
    # badge dupla top
    ax.text(2, -4.5, "Laporte → Rodri ×140", fontsize=12, color=GOLD, fontweight="bold")
    save(fig, "v2_red_pro.png")


# ---------- 2. LÍNEA DE PRESIÓN (KDE + burbujas con dorsal + altura) ----------
def presion():
    from matplotlib.colors import LinearSegmentedColormap
    fig, ax = plt.subplots(figsize=(9, 6.6))
    p = Pitch(pitch_type="opta", pitch_color="none", line_color=LINE, linewidth=1.0, line_zorder=3)
    p.draw(ax=ax)
    da = pd.read_sql("""SELECT e.player_name, e.x, e.y FROM events e
        WHERE e.team_name='Spain' AND e.period!='PenaltyShootout'
        AND e.event_type IN ('Tackle','Interception','BallRecovery','Clearance','BlockedPass','Challenge')""", db)
    # excluir portero
    da = da[da.player_name != "Unai Simón"]
    cmap = LinearSegmentedColormap.from_list("d", ["#07090c00", DIMRED, RED], N=120)
    p.kdeplot(da.x, da.y, ax=ax, fill=True, levels=60, thresh=.06, cut=2, cmap=cmap, zorder=1)
    agg = da.groupby("player_name").agg(x=("x", "median"), y=("y", "median"), c=("x", "size"))
    agg = agg.nlargest(10, "c")
    smax = agg.c.max()
    for n, r in agg.iterrows():
        ax.scatter(r.x, r.y, s=500 + 1700 * r.c / smax, color=BG, edgecolor=GOLD, lw=1.8,
                   alpha=.95, zorder=5)
        ax.text(r.x, r.y, dorsal(n), ha="center", va="center", fontsize=11.5, color=INK,
                fontweight="bold", zorder=6)
    dah = da.x.mean()
    ax.axvline(dah, color=GOLD, lw=2, ls="--", alpha=.9, zorder=4)
    ax.annotate(f"{dah:.1f}", xy=(dah, 101.5), ha="center", fontsize=12, color=GOLD,
                fontweight="bold")
    save(fig, "v2_presion.png")


# ---------- 3. SONAR / IRIS de pases ----------
def sonar():
    from matplotlib.colors import LinearSegmentedColormap
    P = open_play(EV[(EV.event_type == "Pass") & (EV.outcome == "Successful")].dropna(subset=["end_x", "end_y"]))
    ang = np.arctan2(P.end_y - P.y, P.end_x - P.x)
    ln = np.hypot(P.end_x - P.x, P.end_y - P.y)
    nb = 20
    bins = np.linspace(-np.pi, np.pi, nb + 1)
    idx = np.digitize(ang, bins) - 1
    cnt = np.array([(idx == k).sum() for k in range(nb)], float)
    mln = np.array([ln[idx == k].mean() if (idx == k).any() else 0 for k in range(nb)])
    theta = (bins[:-1] + bins[1:]) / 2
    cmap = LinearSegmentedColormap.from_list("s", [DIMRED, RED, GOLD])
    fig = plt.figure(figsize=(6.8, 6.8))
    ax = fig.add_subplot(111, projection="polar")
    ax.set_facecolor("none")
    for ring in [.33, .66, 1.0]:
        ax.plot(np.linspace(0, 2 * np.pi, 120), [ring] * 120, color=LINE, lw=.8, alpha=.7, zorder=1)
    ax.bar(theta, cnt / cnt.max(), width=2 * np.pi / nb * .88,
           color=cmap((mln - 6) / 22), alpha=.96, zorder=3)
    ax.set_theta_zero_location("E")
    ax.set_xticks([]); ax.set_yticks([])
    ax.spines["polar"].set_visible(False)
    ax.grid(False)
    ax.set_ylim(0, 1.1)
    # flecha de direccion de ataque
    ax.annotate("", xy=(0, 1.32), xytext=(np.pi, 1.32),
                arrowprops=dict(arrowstyle="->", color=MUTED, lw=1.6))
    save(fig, "v2_sonar.png")


# ---------- 4. ZONE 14 & HALF-SPACES ----------
def zonas():
    fig, ax = plt.subplots(figsize=(7, 7.6))
    vp = VerticalPitch(pitch_type="opta", half=False, pitch_color="none", line_color=LINE,
                       linewidth=1.0, line_zorder=3)
    vp.draw(ax=ax)
    ax.set_ylim(38, 104)
    P = open_play(EV[(EV.event_type == "Pass") & (EV.outcome == "Successful")].dropna(subset=["end_x", "end_y"]))
    # zonas (opta): half-spaces y∈[16.7,33.3] / [66.7,83.3] en x>50 ; zone14 x∈[66.7,83.3] central
    hs1 = P[(P.end_x > 66.6) & (P.end_y >= 16.7) & (P.end_y < 33.3)]
    hs2 = P[(P.end_x > 66.6) & (P.end_y > 66.7) & (P.end_y <= 83.3)]
    z14 = P[(P.end_x >= 66.7) & (P.end_x <= 83.3) & (P.end_y >= 33.3) & (P.end_y <= 66.7)]
    # pintar bandas (VerticalPitch: eje-x horizontal = y_opta, eje-y vertical = x_opta)
    ax.add_patch(mpatches.Rectangle((16.7, 66.6), 16.6, 33.4, color=RED, alpha=.14, zorder=1))
    ax.add_patch(mpatches.Rectangle((66.7, 66.6), 16.6, 33.4, color=RED, alpha=.14, zorder=1))
    ax.add_patch(mpatches.Rectangle((33.3, 66.7), 33.4, 16.6, color=GOLD, alpha=.16, zorder=1))
    # flechas (muestra)
    for d, col, al in [(hs1, RED, .35), (hs2, RED, .35), (z14, GOLD, .4)]:
        smp = d.sample(min(60, len(d)), random_state=3)
        for r in smp.itertuples():
            ax.add_patch(mpatches.FancyArrowPatch((r.y, r.x), (r.end_y, r.end_x),
                         arrowstyle="->", mutation_scale=7, color=col, lw=.7, alpha=al, zorder=2))
    # badges rombo con conteos
    for cx, cy, n, col in [(25, 62, len(hs1), RED), (75, 62, len(hs2), RED), (50, 59, len(z14), GOLD)]:
        ax.scatter(cx, cy, s=2400, marker="D", color=BG, edgecolor=col, lw=2.2, zorder=6)
        ax.text(cx, cy, str(n), ha="center", va="center", fontsize=14, color=col,
                fontweight="bold", zorder=7)
    save(fig, "v2_zonas.png")


# ---------- 5. ENTRADAS AL ÁREA ----------
def entradas():
    fig, ax = plt.subplots(figsize=(7, 7.6))
    vp = VerticalPitch(pitch_type="opta", pitch_color="none", line_color=LINE,
                       linewidth=1.0, line_zorder=3)
    vp.draw(ax=ax)
    ax.set_ylim(45, 104)
    P = open_play(EV[(EV.event_type == "Pass") & (EV.outcome == "Successful")].dropna(subset=["end_x", "end_y"]))
    box = P[(P.end_x >= 83) & (P.end_y >= 21.1) & (P.end_y <= 78.9) &
            ~((P.x >= 83) & (P.y >= 21.1) & (P.y <= 78.9))]
    izq = box[box.y > 66.7]; der = box[box.y < 33.3]; cen = box[(box.y >= 33.3) & (box.y <= 66.7)]
    for d, col in [(izq, RED), (der, RED), (cen, GOLD)]:
        for r in d.itertuples():
            ax.add_patch(mpatches.FancyArrowPatch((r.y, r.x), (r.end_y, r.end_x),
                         arrowstyle="->", mutation_scale=8,
                         color=col, lw=.85, alpha=.4 if col == RED else .5, zorder=2))
    for cx, cy, n, col in [(88, 78, len(izq), RED), (12, 78, len(der), RED), (50, 51.5, len(cen), GOLD)]:
        ax.scatter(cx, cy, s=2300, color=BG, edgecolor=col, lw=2.2, zorder=6)
        ax.text(cx, cy, str(n), ha="center", va="center", fontsize=14, color=col,
                fontweight="bold", zorder=7)
    save(fig, "v2_entradas.png")


# ---------- 6. MOMENTUM con goles ----------
def momentum2():
    fig, ax = plt.subplots(figsize=(12.5, 3.8))
    mom = json.load(open(ROOT / "outputs" / "divulgacion" / "momentum_all.json"))
    spmom = [x for x in mom if x["home"] == "Spain" or x["away"] == "Spain"]
    order = {r.match_id: str(r.start_utc) for r in SP_M.itertuples()}
    spmom.sort(key=lambda x: order[x["match_id"]])
    goals = pd.read_sql("""SELECT match_id, team_name, expanded_minute m, qualifiers FROM events
        WHERE event_type='Goal' AND period!='PenaltyShootout'
        AND match_id IN (SELECT match_id FROM events WHERE team_name='Spain' GROUP BY match_id)""", db)
    goals["og"] = goals.qualifiers.str.contains("OwnGoal", na=False)
    goals["for_spain"] = (goals.team_name == "Spain") ^ goals.og
    xoff = 0
    for x in spmom:
        mm = SP_M[SP_M.match_id == x["match_id"]].iloc[0]
        sign = 1 if mm.home_team == "Spain" else -1
        w = sorted(((int(k), v * sign) for k, v in x["windows"].items()))
        xs = [xoff + i for i, _ in enumerate(w)]
        ys = [v for _, v in w]
        ax.bar(xs, ys, width=.9, color=[RED if v >= 0 else GRAY for v in ys])
        g = goals[goals.match_id == x["match_id"]]
        for r in g.itertuples():
            gx = xoff + min(int(r.m // 5), len(w) - 1)
            if r.for_spain:
                ax.scatter(gx, .50, s=100, color=GOLD, edgecolor=BG, lw=1, zorder=5)
            else:
                ax.scatter(gx, -.50, s=120, color=GRAY, edgecolor=INK, lw=1, marker="X", zorder=5)
        xoff += len(w) + 2.5
        ax.axvline(xoff - 1.5, color=LINE, lw=.8, alpha=.5)
    ax.axhline(0, color=MUTED, lw=1)
    ax.set_ylim(-.62, .62)
    ax.axis("off")
    save(fig, "v2_momentum.png")


if __name__ == "__main__":
    for fn in [red_pro, presion, sonar, zonas, entradas, momentum2]:
        fn()
    # grilla v2: nuevos + los aprobados (cubarsi) + timeline opcional
    from PIL import Image
    names = ["v2_red_pro", "v2_presion", "v2_sonar", "v2_zonas", "v2_entradas",
             "c_cubarsi", "v2_momentum", "a_timeline"]
    cols, rows, cw, chh = 3, 3, 880, 660
    grid = Image.new("RGB", (cols * cw, rows * chh), (7, 9, 12))
    for i, n in enumerate(names):
        im = Image.open(OUT / f"{n}.png").convert("RGBA")
        r = min(cw / im.width, chh / im.height) * 0.94
        im = im.resize((int(im.width * r), int(im.height * r)), Image.LANCZOS)
        grid.paste(im, ((i % cols) * cw + (cw - im.width) // 2,
                        (i // cols) * chh + (chh - im.height) // 2), im)
    grid.save(OUT / "espana_grid_v2.png")
    print("→ espana_grid_v2.png")
