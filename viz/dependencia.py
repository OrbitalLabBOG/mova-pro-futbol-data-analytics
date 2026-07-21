"""C3-04 — La dependencia goleadora: 3 equipos-estrella + España coral (todos sus goleadores).

Grid limpio sin título (el montaje final lo hace codex sobre el fondo de la serie).
Uso: python viz/dependencia.py
Salida: outputs/divulgacion/experiments/dependencia_v1.png
"""
import sqlite3
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from mplsoccer import VerticalPitch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "divulgacion" / "experiments"
db = sqlite3.connect(ROOT / "data" / "mundial.db")

BG, LINE, INK, MUTED = "#07090c", "#2a3038", "#e8e6e3", "#6b7280"
GRAY = "#3d434d"
PATH_EFF = [pe.Stroke(linewidth=2.8, foreground=BG), pe.Normal()]
SHOTS_T = ("Goal", "MissedShots", "SavedShot", "ShotOnPost")

STARS = [("Norway", "Erling Haaland", "#ef476f", "NORUEGA"),
         ("France", "Kylian Mbappé", "#4361ee", "FRANCIA"),
         ("Argentina", "Lionel Messi", "#7cc0e8", "ARGENTINA")]
SPAIN_C = "#e4353f"

plt.rcParams.update({"figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG,
                     "text.color": INK, "font.family": "DejaVu Sans"})


def shots_df(team):
    return pd.read_sql(f"""SELECT player_name, event_type, x, y FROM events
        WHERE team_name=? AND event_type IN {SHOTS_T} AND period!='PenaltyShootout'
        AND qualifiers NOT LIKE '%OwnGoal%' AND x IS NOT NULL""", db, params=(team,))


def team_goals(team):
    return pd.read_sql("""SELECT player_name, COUNT(*) g FROM events
        WHERE team_name=? AND event_type='Goal' AND period!='PenaltyShootout'
        AND qualifiers NOT LIKE '%OwnGoal%' GROUP BY player_name ORDER BY g DESC""",
                       db, params=(team,))


fig = plt.figure(figsize=(13.2, 12.8))
gs = fig.add_gridspec(2, 2, wspace=.08, hspace=.30, left=.03, right=.97, top=.94, bottom=.06)

# ---- fila 1: los dependientes ----
for i, (team, star, col, label) in enumerate(STARS):
    ax = fig.add_subplot(gs[i // 2, i % 2])
    vp = VerticalPitch(pitch_type="opta", half=True, pitch_color="none", line_color=LINE,
                       linewidth=1.0, pad_bottom=2)
    vp.draw(ax=ax)
    S = shots_df(team)
    others = S[S.player_name != star]
    mine = S[S.player_name == star]
    # tiros del resto: gris tenue · tiros estrella: color abierto
    vp.scatter(others[others.event_type != "Goal"].x, others[others.event_type != "Goal"].y,
               s=52, c="None", edgecolors=GRAY, lw=1.1, alpha=.75, ax=ax, zorder=2)
    vp.scatter(mine[mine.event_type != "Goal"].x, mine[mine.event_type != "Goal"].y,
               s=70, c="None", edgecolors=col, lw=1.5, ax=ax, zorder=3)
    # goles: llenos (resto gris / estrella color, mas grande)
    og = others[others.event_type == "Goal"]
    mg = mine[mine.event_type == "Goal"]
    vp.scatter(og.x, og.y, s=130, c=GRAY, edgecolors=INK, lw=.8, ax=ax, zorder=4)
    vp.scatter(mg.x, mg.y, s=260, c=col, edgecolors="white", lw=1.6, ax=ax, zorder=5)
    gdf = team_goals(team)
    tot = gdf.g.sum(); stg = int(gdf[gdf.player_name == star].g.iloc[0])
    pct = stg / tot * 100
    ax.set_title(label, fontsize=22, color=col, fontweight="bold", pad=9)
    ax.text(.5, .015, f"{pct:.0f}%", transform=ax.transAxes, ha="center", fontsize=46,
            color=col, fontweight="bold", path_effects=PATH_EFF)
    ax.text(.5, -.045, f"de sus goles son de {star.split()[-1]}  ({stg} de {tot})",
            transform=ax.transAxes, ha="center", fontsize=13.5, color=MUTED)

# ---- fila 2: España coral ----
ax = fig.add_subplot(gs[1, 1])
vp = VerticalPitch(pitch_type="opta", half=True, pitch_color="none", line_color=LINE,
                   linewidth=1.2)
vp.draw(ax=ax)
ax.set_ylim(57, 104)
S = shots_df("Spain")
S = S[S.x >= 58]
vp.scatter(S[S.event_type != "Goal"].x, S[S.event_type != "Goal"].y,
           s=42, c="None", edgecolors=GRAY, lw=1.1, alpha=.7, ax=ax, zorder=2)
G = S[S.event_type == "Goal"].copy()
vp.scatter(G.x, G.y, s=200, c=SPAIN_C, edgecolors="white", lw=1.8, ax=ax, zorder=5)
# chip por goleador en el centroide de sus goles (adjust_text separa choques)
from adjustText import adjust_text
texts = []
for name, grp in sorted(G.groupby(G.player_name.str.split().str[-1]), key=lambda kv: -len(kv[1])):
    label = f"{name} ×{len(grp)}" if len(grp) > 1 else name
    texts.append(ax.text(grp.y.mean(), grp.x.mean() - 2.8, label, ha="center", va="center",
                 fontsize=12, color=INK, fontweight="bold", zorder=7,
                 bbox=dict(boxstyle="round,pad=0.32", facecolor="#12161d",
                           edgecolor=SPAIN_C, linewidth=1.3)))
adjust_text(texts, ax=ax, expand=(1.5, 2.2),
            arrowprops=dict(arrowstyle="-", color="#5a616c", lw=.9))
ax.set_title("ESPAÑA", fontsize=22, color=SPAIN_C, fontweight="bold", pad=9)
ax.set_ylim(48, 104.5)
ax.text(.5, .015, "38%", transform=ax.transAxes, ha="center", fontsize=46,
        color=SPAIN_C, fontweight="bold", path_effects=PATH_EFF)
ax.text(.5, -.045, "su máximo (Oyarzabal) — 7 goleadores distintos",
        transform=ax.transAxes, ha="center", fontsize=13.5, color=MUTED)

fig.savefig(OUT / "dependencia_strip.png", dpi=150, transparent=True)
print("→ dependencia_strip.png")
