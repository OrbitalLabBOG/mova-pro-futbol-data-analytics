"""C3-03 — El reloj del Mundial: dial semicircular 0'→120'+ con los goles reales.

Todos los goles como puntos tenues; los del 90'+ como chispas incendiadas.
Sin texto (solo marcas 0/45/90/120 como ticks visuales mínimos).
Salida: outputs/divulgacion/experiments/reloj_dial.png (fondo transparente-oscuro)
"""
import sqlite3
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "divulgacion" / "experiments"
db = sqlite3.connect(ROOT / "data" / "mundial.db")

BG = "#0b0710"
FUCSIA = "#ff2d96"
ROSA = "#ff82d2"
MUTED = "#6b5563"
INK = "#f0e8ee"

G = pd.read_sql("""SELECT expanded_minute m FROM events WHERE event_type='Goal'
    AND period != 'PenaltyShootout' AND qualifiers NOT LIKE '%OwnGoal%'""", db)
G = pd.concat([G, pd.read_sql("""SELECT expanded_minute m FROM events WHERE event_type='Goal'
    AND period != 'PenaltyShootout' AND qualifiers LIKE '%OwnGoal%'""", db)])  # autogoles también cuentan al drama
G["m"] = G.m.clip(upper=130)

fig, ax = plt.subplots(figsize=(12, 7), subplot_kw=dict(projection="polar"))
fig.patch.set_facecolor(BG)
ax.set_facecolor(BG)

# dial semicircular: 0' a la izquierda, 120'+ a la derecha
ax.set_theta_zero_location("W")
ax.set_theta_direction(-1)
ax.set_thetamin(0)
ax.set_thetamax(180)

def m2th(m): return np.deg2rad(np.clip(m, 0, 130) / 130 * 180)

rng = np.random.default_rng(3)
# todos los goles: puntos tenues con jitter radial
early = G[G.m < 90]
late = G[G.m >= 90]
r_e = 0.78 + rng.uniform(-0.1, 0.1, len(early))
ax.scatter(m2th(early.m.values), r_e, s=26, color=MUTED, alpha=.5, lw=0, zorder=3)
# goles 90+: chispas incendiadas en capas
r_l = 0.78 + rng.uniform(-0.12, 0.12, len(late))
th_l = m2th(late.m.values)
ax.scatter(th_l, r_l, s=300, color=FUCSIA, alpha=.12, lw=0, zorder=4)
ax.scatter(th_l, r_l, s=110, color=FUCSIA, alpha=.45, lw=0, zorder=5)
ax.scatter(th_l, r_l, s=34, color=ROSA, alpha=.95, lw=0, zorder=6)

# arco base del dial
th = np.linspace(0, np.pi, 300)
ax.plot(th, np.full_like(th, 0.60), color="#3a2f3c", lw=2.2, zorder=2)
# zona 90+ resaltada sobre el arco
th_hot = np.linspace(m2th(90), m2th(130), 80)
ax.plot(th_hot, np.full_like(th_hot, 0.60), color=FUCSIA, lw=4, alpha=.9, zorder=3)

# ticks minimos (0, 45, 90, 120) — lineas, sin numeros (texto va por codigo/copy)
for m in [0, 45, 90, 120]:
    t = m2th(m)
    ax.plot([t, t], [0.54, 0.66], color=INK if m >= 90 else MUTED, lw=2.4 if m >= 90 else 1.6, zorder=7)

# 4 estrellas = tandas de penales, al final del dial
ax.scatter([m2th(128)] * 4, [1.02, 0.95, 0.88, 0.81], s=140, marker="*",
           color=ROSA, edgecolor=FUCSIA, lw=.5, zorder=8)

ax.set_ylim(0, 1.12)
ax.set_xticks([]); ax.set_yticks([])
ax.spines["polar"].set_visible(False)
ax.grid(False)
fig.tight_layout(pad=0.5)
fig.savefig(OUT / "reloj_dial.png", dpi=170, facecolor=BG)
print(f"→ reloj_dial.png  (goles totales {len(G)}, en 90'+: {len(late)})")
