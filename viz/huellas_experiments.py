"""Laboratorio de HUELLAS — 4 conceptos de fingerprint por equipo, datos reales.

Uso: python viz/huellas_experiments.py [flow|shots|territorio|sonar|all]
Salida: outputs/divulgacion/experiments/huella_*.png
"""
import sys, sqlite3
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
db = sqlite3.connect(ROOT / "data" / "mundial.db")

BG, PANEL, LINE, INK, MUTED = "#07090c", "#0d1117", "#2a3038", "#e8e6e3", "#8a8f98"
MINT = "#3ceb8c"
GOLD = "#ffd166"
TEAMS = ["Spain", "Argentina", "Norway", "Cabo Verde", "Paraguay", "Morocco"]
LABEL = {"Spain": "ESPAÑA", "Argentina": "ARGENTINA", "Norway": "NORUEGA",
         "Cabo Verde": "CABO VERDE", "Paraguay": "PARAGUAY", "Morocco": "MARRUECOS"}

plt.rcParams.update({"figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG,
                     "text.color": INK, "font.family": "DejaVu Sans"})


def dark_pitch(ax):
    p = Pitch(pitch_type="opta", pitch_color=BG, line_color=LINE, linewidth=0.9)
    p.draw(ax=ax)
    return p


# ---------- A. CAMPO DE FLUJO: todos los pases como limaduras ----------
def flow():
    fig, axes = plt.subplots(2, 3, figsize=(17, 11))
    fig.suptitle("HUELLA A — CAMPO DE FLUJO (cada línea = un pase real del torneo)",
                 fontsize=15, fontweight="bold", color=INK)
    for ax, team in zip(axes.flat, TEAMS):
        dark_pitch(ax)
        P = pd.read_sql("""SELECT x, y, end_x, end_y FROM events WHERE team_name=?
            AND event_type='Pass' AND outcome='Successful' AND end_x IS NOT NULL
            AND period != 'PenaltyShootout'""", db, params=(team,))
        # capa glow (gruesa, casi invisible) + capa fina
        for lw, al in [(1.8, 0.018), (0.45, 0.055)]:
            ax.plot([P.x, P.end_x], [P.y, P.end_y], color=MINT, lw=lw, alpha=al,
                    solid_capstyle="round")
        ax.set_title(f"{LABEL[team]}  ·  {len(P):,} pases".replace(",", "."),
                     fontsize=12, color=INK, fontweight="bold", pad=5)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(OUT / "huella_A_flow.png", dpi=150)
    print("→ huella_A_flow.png")


# ---------- B. MANCHA DE DISPAROS ----------
def shots():
    fig, axes = plt.subplots(2, 3, figsize=(15, 13))
    fig.suptitle("HUELLA B — LA MANCHA DE DISPAROS (desde dónde remata cada uno)",
                 fontsize=15, fontweight="bold", color=INK)
    cmap = LinearSegmentedColormap.from_list("s", [BG, "#1d5c3b", MINT])
    for ax, team in zip(axes.flat, TEAMS):
        vp = VerticalPitch(pitch_type="opta", half=True, pitch_color=BG, line_color=LINE,
                           linewidth=0.9)
        vp.draw(ax=ax)
        S = pd.read_sql("""SELECT x, y FROM events WHERE team_name=? AND event_type IN
            ('Goal','MissedShots','SavedShot','ShotOnPost') AND period!='PenaltyShootout'
            AND qualifiers NOT LIKE '%OwnGoal%'""", db, params=(team,))
        vp.kdeplot(S.x, S.y, ax=ax, fill=True, levels=60, thresh=.06, cut=2, cmap=cmap)
        vp.scatter(S.x, S.y, s=14, color=MINT, alpha=.5, ax=ax, zorder=3)
        d = np.hypot(100 - S.x, 50 - S.y).mean() * 1.05  # ~metros aprox en escala opta
        ax.set_title(f"{LABEL[team]}  ·  dist. media {d:.0f}", fontsize=12,
                     color=INK, fontweight="bold", pad=5)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(OUT / "huella_B_shots.png", dpi=150)
    print("→ huella_B_shots.png")


# ---------- C. TERRITORIO (KDE de todos los toques) ----------
def territorio():
    fig, axes = plt.subplots(2, 3, figsize=(17, 11))
    fig.suptitle("HUELLA C — EL TERRITORIO (dónde vive cada equipo con el balón)",
                 fontsize=15, fontweight="bold", color=INK)
    cmap = LinearSegmentedColormap.from_list("t", [BG, "#14532d", MINT, "#d9ffe9"])
    for ax, team in zip(axes.flat, TEAMS):
        dark_pitch(ax)
        T = pd.read_sql("""SELECT x, y FROM events WHERE team_name=? AND is_touch=1
            AND x IS NOT NULL AND period != 'PenaltyShootout'""", db, params=(team,))
        if len(T) < 100:
            T = pd.read_sql("""SELECT x, y FROM events WHERE team_name=? AND event_type='Pass'
                AND period != 'PenaltyShootout'""", db, params=(team,))
        p = Pitch(pitch_type="opta")
        ax_kde = ax
        Pitch(pitch_type="opta", pitch_color=BG, line_color=LINE).kdeplot(
            T.x, T.y, ax=ax_kde, fill=True, levels=80, thresh=.05, cut=2, cmap=cmap)
        ax.set_title(f"{LABEL[team]}", fontsize=12, color=INK, fontweight="bold", pad=5)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(OUT / "huella_C_territorio.png", dpi=150)
    print("→ huella_C_territorio.png")


# ---------- D. SONAR-IRIS (radial, marco de escáner) ----------
def sonar():
    fig = plt.figure(figsize=(16, 11))
    fig.suptitle("HUELLA D — EL IRIS (dirección y largo de todos los pases)",
                 fontsize=15, fontweight="bold", color=INK)
    n_bins = 24
    cmap = LinearSegmentedColormap.from_list("i", ["#155e43", MINT, "#d9ffe9"])
    for i, team in enumerate(TEAMS):
        ax = fig.add_subplot(2, 3, i + 1, projection="polar")
        ax.set_facecolor(BG)
        P = pd.read_sql("""SELECT x, y, end_x, end_y FROM events WHERE team_name=?
            AND event_type='Pass' AND outcome='Successful' AND end_x IS NOT NULL""",
                        db, params=(team,))
        ang = np.arctan2(P.end_y - P.y, P.end_x - P.x)
        ln = np.hypot(P.end_x - P.x, P.end_y - P.y)
        bins = np.linspace(-np.pi, np.pi, n_bins + 1)
        idx = np.digitize(ang, bins) - 1
        cnt = np.array([(idx == k).sum() for k in range(n_bins)], float)
        mln = np.array([ln[idx == k].mean() if (idx == k).any() else 0 for k in range(n_bins)])
        theta = (bins[:-1] + bins[1:]) / 2
        # doble anillo: barras (volumen) + anillo exterior de escáner
        ax.bar(theta, cnt / cnt.max(), width=2 * np.pi / n_bins * .9,
               color=cmap((mln - 8) / 20), alpha=.95, zorder=3)
        ax.bar(theta, np.ones(n_bins) * 1.18, width=2 * np.pi / n_bins,
               bottom=1.12, color=MINT, alpha=.10, zorder=1)
        ax.set_theta_zero_location("E")
        ax.set_xticks([]); ax.set_yticks([])
        ax.spines["polar"].set_color(LINE)
        ax.set_title(LABEL[team], fontsize=12, color=INK, fontweight="bold", pad=12)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(OUT / "huella_D_sonar.png", dpi=150)
    print("→ huella_D_sonar.png")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    fns = dict(flow=flow, shots=shots, territorio=territorio, sonar=sonar)
    for k, fn in fns.items():
        if which in ("all", k):
            fn()
