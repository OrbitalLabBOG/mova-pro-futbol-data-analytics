"""Dashboards estilo match-report (ref: bariscanyeksin) a nivel TORNEO — España y Messi.

Uso: python viz/dashboards.py [spain|messi|all]
Salidas: outputs/divulgacion/dash_spain.png, dash_messi.png
"""
import sys, json, sqlite3, collections
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from matplotlib.colors import LinearSegmentedColormap
from matplotlib import patches
from mplsoccer import Pitch, VerticalPitch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "divulgacion"
db = sqlite3.connect(ROOT / "data" / "mundial.db")

BG, PANEL, LINE, INK, MUTED = "#0a0a0a", "#101319", "#39404c", "#e8e6e3", "#8a8f98"
SPAIN, RIVAL, ACCENT, GOLD = "#e4353f", "#5b6472", "#00d4a3", "#ffd166"
MESSI = "#7cc0e8"
PATH_EFF = [pe.Stroke(linewidth=2.5, foreground=BG), pe.Normal()]

plt.rcParams.update({
    "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG,
    "text.color": INK, "font.family": "DejaVu Sans",
})

EV = pd.read_sql("""SELECT match_id, id, event_type, outcome, team_name, player_name, x, y,
    end_x, end_y, goal_mouth_y, goal_mouth_z, is_shot, is_goal, qualifiers, period,
    expanded_minute AS minute, expanded_minute*60+COALESCE(second,0) AS t
    FROM events WHERE period != 'PenaltyShootout' ORDER BY match_id, id""", db)
MATCHES = pd.read_sql("SELECT match_id, home_team, away_team, home_score, away_score, start_utc FROM matches", db)
SHOTS_T = {"Goal", "MissedShots", "SavedShot", "ShotOnPost"}


def pitch_ax(ax, panel=PANEL):
    p = Pitch(pitch_type="opta", pitch_color=panel, line_color=LINE, linewidth=1.1,
              goal_type="box", corner_arcs=True, line_zorder=2)
    p.draw(ax=ax)
    return p


def ptitle(ax, txt, sub=None, color=INK):
    ax.set_title(txt, color=color, fontsize=15, fontweight="bold", pad=26 if sub else 8,
                 path_effects=PATH_EFF)
    if sub:
        ax.text(0.5, 1.022, sub, transform=ax.transAxes, ha="center", fontsize=9.5, color=MUTED)


def chips(fig, y, items, color):
    xs = np.linspace(0.06, 0.94, len(items))
    for x, (big, small) in zip(xs, items):
        fig.text(x, y, big, ha="center", fontsize=21, fontweight="bold", color=color)
        fig.text(x, y - 0.0165, small, ha="center", fontsize=9.5, color=MUTED)


def open_play(df):
    return df[~df.qualifiers.str.contains("Corner|Freekick|ThrowIn|GoalKick|KickOff", na=False)]


# ================= ESPAÑA =================
def dash_spain():
    sp_m = MATCHES[(MATCHES.home_team == "Spain") | (MATCHES.away_team == "Spain")].sort_values("start_utc")
    mids = sp_m.match_id.tolist()
    ev = EV[EV.match_id.isin(mids)]
    mine = ev[ev.team_name == "Spain"]
    theirs = ev[(ev.team_name != "Spain") & ev.team_name.notna()]

    fig = plt.figure(figsize=(19, 24))
    gs = fig.add_gridspec(4, 3, left=.035, right=.965, top=.855, bottom=.085,
                          hspace=.33, wspace=.14, height_ratios=[1.15, 1, 1, .62])

    # header
    fig.text(.5, .966, "ESPAÑA — EL MUNDIAL ENTERO EN UN TABLERO", ha="center",
             fontsize=30, fontweight="bold", color=INK)
    fig.text(.5, .948, "8 partidos · campeona · datos y modelos propios sobre 163.688 eventos Opta",
             ha="center", fontsize=12, color=MUTED)
    chips(fig, .922, [("770'", "sin ir perdiendo"), ("1", "gol encajado"), ("8/8", "batalla xG ganada"),
                      ("78%", "momentum del torneo"), ("7", "goleadores distintos"), ("41.6", "altura defensiva (líder)")], SPAIN)

    # (1,1) pass network
    ax = fig.add_subplot(gs[0, 0]); p = pitch_ax(ax)
    passes = mine[(mine.event_type == "Pass") & (mine.outcome == "Successful")]
    top = passes.player_name.value_counts().head(11).index
    pos = passes[passes.player_name.isin(top)].groupby("player_name")[["x", "y"]].mean()
    edges = collections.Counter(); prev = None
    onball = mine[mine.event_type.isin({"Pass", "TakeOn", "Goal", "MissedShots", "SavedShot", "BallTouch", "Dispossessed"})]
    for r in onball.itertuples():
        if prev is not None and r.match_id == prev.match_id and prev.event_type == "Pass" and \
           prev.outcome == "Successful" and r.player_name != prev.player_name and \
           r.player_name in pos.index and prev.player_name in pos.index and r.t - prev.t < 20:
            edges[(prev.player_name, r.player_name)] += 1
        prev = r
    mx = max(edges.values())
    for (a, b), w in edges.items():
        if w < 15: continue
        ax.plot([pos.loc[a, "x"], pos.loc[b, "x"]], [pos.loc[a, "y"], pos.loc[b, "y"]],
                color=SPAIN, lw=.5 + 6 * w / mx, alpha=.15 + .6 * w / mx, solid_capstyle="round", zorder=3)
    vol = passes[passes.player_name.isin(top)].player_name.value_counts()
    ax.scatter(pos.x, pos.y, s=(180 + 1300 * (vol / vol.max())).reindex(pos.index), color=PANEL,
               edgecolor=SPAIN, lw=2, zorder=4)
    for n, r in pos.iterrows():
        ax.annotate(n.split()[-1], (r.x, r.y), ha="center", va="center", fontsize=7.5,
                    color=INK, fontweight="bold", zorder=5, path_effects=PATH_EFF)
    avgh = passes.x.mean()
    ax.axvline(avgh, color=ACCENT, ls="--", lw=1.4, alpha=.8)
    ptitle(ax, "La red — Rodri como centro de gravedad", "nodos = posición media (tamaño ∝ pases) · Laporte→Rodri = la dupla del torneo (140)")

    # (1,2-3) shot duel map
    ax = fig.add_subplot(gs[0, 1:]); p = pitch_ax(ax)
    smine = mine[mine.event_type.isin(SHOTS_T)]
    sth = theirs[theirs.event_type.isin(SHOTS_T)]
    def scatter_shots(df, xs, ys, col):
        big = df.qualifiers.str.contains("BigChance", na=False)
        for mask, kind in [(df.event_type == "Goal", "goal"), (df.event_type == "SavedShot", "saved"),
                           (df.event_type == "MissedShots", "miss"), (df.event_type == "ShotOnPost", "post")]:
            for b in [False, True]:
                d = df[mask & (big == b)]
                if not len(d): continue
                s = 300 if b else 130
                if kind == "goal":
                    p.scatter(xs(d), ys(d), s=s * 1.6, marker="football", edgecolors=ACCENT, c="None", ax=ax, zorder=4)
                elif kind == "saved":
                    p.scatter(xs(d), ys(d), s=s, marker="o", c="None", edgecolors=col, hatch="/////", ax=ax, zorder=3)
                elif kind == "post":
                    p.scatter(xs(d), ys(d), s=s, marker="o", c=col, edgecolors=col, ax=ax, zorder=3)
                else:
                    p.scatter(xs(d), ys(d), s=s, marker="o", c="None", edgecolors=col, ax=ax, zorder=3)
    scatter_shots(smine, lambda d: d.x, lambda d: d.y, SPAIN)               # España ataca →
    scatter_shots(sth, lambda d: 100 - d.x, lambda d: 100 - d.y, RIVAL)     # rivales atacan ←
    stats = [("Goles", 13, 1), ("xG", 15.8, 4.9), ("Tiros", len(smine), len(sth)),
             ("A puerta", int((smine.event_type.isin(["Goal", "SavedShot"])).sum()),
              int((sth.event_type.isin(["Goal", "SavedShot"])).sum())),
             ("Dist. media", 16.6, 20.1)]
    y0 = 88
    for i, (lab, hv, av) in enumerate(stats):
        tot = hv + av
        hw, aw = 16 * hv / tot, 16 * av / tot
        y = y0 - i * 7.5
        ax.barh(y, hw, left=50 - hw, height=3.4, color=SPAIN, zorder=5)
        ax.barh(y, aw, left=50, height=3.4, color=RIVAL, zorder=5)
        ax.text(50, y + 2.6, lab, ha="center", fontsize=10, color=INK, zorder=6, path_effects=PATH_EFF)
        ax.text(50 - hw - 1, y, f"{hv:g}", ha="right", va="center", fontsize=10.5, color=SPAIN, fontweight="bold", zorder=6)
        ax.text(50 + aw + 1, y, f"{av:g}", ha="left", va="center", fontsize=10.5, color=RIVAL, fontweight="bold", zorder=6)
    ptitle(ax, "Todos los tiros del torneo — España (rojo, →) vs sus 8 rivales (gris, ←)",
           "⚽=gol · rayado=atajado · vacío=fuera · tamaño grande = ocasión clara · 122 tiros a favor, 47 en contra")

    # (2,1) defensive block
    ax = fig.add_subplot(gs[1, 0]); p = pitch_ax(ax)
    da = mine[mine.event_type.isin({"Tackle", "Interception", "BallRecovery", "Clearance", "BlockedPass", "Challenge"})]
    cmap = LinearSegmentedColormap.from_list("d", [PANEL, SPAIN])
    p.kdeplot(da.x, da.y, ax=ax, fill=True, levels=60, thresh=.05, cut=3, cmap=cmap)
    h = da.x.mean()
    ax.axvline(h, color=ACCENT, ls="--", lw=1.6)
    ax.text(h + 1.5, 95, f"altura {h:.1f} — la más alta del Mundial", fontsize=9.5, color=ACCENT, fontweight="bold")
    ptitle(ax, "Dónde defendió — la línea más alta del torneo", "densidad de acciones defensivas · 24 offsides provocados (líder)")

    # (2,2) pass end zones (positional)
    ax = fig.add_subplot(gs[1, 1]); p = pitch_ax(ax)
    pz = passes.dropna(subset=["end_x", "end_y"])
    bs = p.bin_statistic_positional(pz.end_x, pz.end_y, statistic="count", positional="full", normalize=True)
    cmap2 = LinearSegmentedColormap.from_list("z", [PANEL, SPAIN])
    p.heatmap_positional(bs, ax=ax, cmap=cmap2, edgecolors=BG)
    p.label_heatmap(bs, color=INK, fontsize=11, ax=ax, ha="center", va="center",
                    str_format="{:.0%}", path_effects=PATH_EFF)
    ptitle(ax, "A dónde llegó cada pase", "distribución posicional (juego de posición) — 5.681 pases")

    # (2,3) chance creation
    ax = fig.add_subplot(gs[1, 2]); p = pitch_ax(ax)
    kp = mine[(mine.event_type == "Pass") & mine.qualifiers.str.contains("KeyPass", na=False)]
    bs = p.bin_statistic_positional(kp.x, kp.y, statistic="count", positional="full", normalize=False)
    p.heatmap_positional(bs, ax=ax, cmap=cmap2, edgecolors=BG)
    for r in kp.itertuples():
        is_assist = "IntentionalGoalAssist" in (r.qualifiers or "")
        ax.add_patch(patches.FancyArrowPatch((r.x, r.y), (r.end_x, r.end_y), arrowstyle="->",
                     mutation_scale=9, color=ACCENT if is_assist else MUTED,
                     lw=1.5 if is_assist else .8, alpha=.95 if is_assist else .5, zorder=4))
    ptitle(ax, f"Fábrica de ocasiones — {len(kp)} pases clave", "verde = asistencia (8 asistidores distintos) · gris = pase clave")

    # (3,1) high turnovers
    ax = fig.add_subplot(gs[2, 0]); p = pitch_ax(ax)
    ht = mine[mine.event_type.isin({"BallRecovery", "Interception"})].copy()
    ht["dist"] = np.hypot(100 - ht.x, 50 - ht.y)
    htf = ht[ht.dist <= 40]
    circ = patches.Circle((100, 50), 40, color=SPAIN, fill=True, alpha=.14, zorder=1)
    ax.add_artist(circ)
    p.scatter(htf.x, htf.y, s=110, c=SPAIN, edgecolor=BG, lw=.8, ax=ax, zorder=3, alpha=.9)
    ax.text(3, 92, f"{len(htf)} robos en zona de peligro", fontsize=11, color=SPAIN, fontweight="bold")
    ptitle(ax, "El pressing convertido en robos altos", "recuperaciones a ≤40 del arco rival (8 partidos)")

    # (3,2) goal mouth — Unai
    ax = fig.add_subplot(gs[2, 1]); ax.set_facecolor(PANEL)
    ax.set_xlim(-6, 106); ax.set_ylim(-8, 60); ax.axis("off")
    for x0 in [(50 - 36.6), ]: pass
    gx0, gx1, gz = 15, 85, 38
    ax.plot([gx0, gx0], [0, gz], color=LINE, lw=5); ax.plot([gx1, gx1], [0, gz], color=LINE, lw=5)
    ax.plot([gx0, gx1], [gz, gz], color=LINE, lw=5); ax.plot([gx0 - 8, gx1 + 8], [0, 0], color=MUTED, lw=2)
    faced = sth[sth.event_type.isin({"Goal", "SavedShot"}) &
                ~sth.qualifiers.str.contains("OwnGoal", na=False)].dropna(subset=["goal_mouth_y", "goal_mouth_z"])
    gy = gx0 + (faced.goal_mouth_y - 45) / 10 * (gx1 - gx0)  # goal mouth y ~45-55 → ancho
    gzz = faced.goal_mouth_z / 46 * gz
    sv = faced.event_type == "SavedShot"
    ax.scatter(gy[sv], gzz[sv], s=380, marker="o", c="None", edgecolor=SPAIN, hatch="/////", lw=1.4)
    ax.scatter(gy[~sv], gzz[~sv], s=520, marker="o", c="None", edgecolor=GOLD, lw=2.5)
    ax.text(50, 52, "el arco de Unai Simón en TODO el Mundial", ha="center", fontsize=12, color=INK, fontweight="bold")
    ax.text(50, -6, "rayado = atajada (10) · dorado = el ÚNICO gol encajado (De Ketelaere, 40' de cuartos)",
            ha="center", fontsize=9.5, color=MUTED)

    # (3,3) zone dominance
    ax = fig.add_subplot(gs[2, 2]); p = pitch_ax(ax)
    tm = mine[mine.is_touch == 1] if "is_touch" in mine else mine[mine.event_type == "Pass"]
    tt = theirs[theirs.event_type == "Pass"].copy()
    tt["x"], tt["y"] = 100 - tt.x, 100 - tt.y
    bs_m = p.bin_statistic(mine[mine.event_type == "Pass"].x, mine[mine.event_type == "Pass"].y, bins=(6, 5))
    bs_t = p.bin_statistic(tt.x, tt.y, bins=(6, 5))
    dom = bs_m.copy()
    tot = bs_m["statistic"] + bs_t["statistic"]
    dom["statistic"] = np.where(tot > 0, bs_m["statistic"] / np.maximum(tot, 1) * 100, 50)
    cmap3 = LinearSegmentedColormap.from_list("dom", [RIVAL, PANEL, SPAIN])
    p.heatmap(dom, ax=ax, cmap=cmap3, vmin=20, vmax=80, edgecolors=BG)
    p.label_heatmap(dom, color=INK, fontsize=10, ax=ax, ha="center", va="center",
                    str_format="{:.0f}%", path_effects=PATH_EFF)
    ptitle(ax, "Dominio territorial por zona", "% de pases de España vs TODOS sus rivales (field tilt medio: 71%)")

    # (4, full) momentum whole tournament
    ax = fig.add_subplot(gs[3, :])
    mom = json.load(open(OUT / "momentum_all.json"))
    spmom = [m for m in mom if m["home"] == "Spain" or m["away"] == "Spain"]
    order = {r.match_id: str(r.start_utc) for r in sp_m.itertuples()}
    spmom.sort(key=lambda m: order[m["match_id"]])
    xoff = 0; ticks = []
    for m in spmom:
        mm = sp_m[sp_m.match_id == m["match_id"]].iloc[0]
        rival = mm.away_team if mm.home_team == "Spain" else mm.home_team
        sign = 1 if mm.home_team == "Spain" else -1
        w = sorted(((int(k), v * sign) for k, v in m["windows"].items()))
        xs = [xoff + i for i, _ in enumerate(w)]; ys = [v for _, v in w]
        ax.bar(xs, ys, width=.92, color=[SPAIN if v >= 0 else RIVAL for v in ys])
        ticks.append((xoff + len(w) / 2, rival))
        xoff += len(w) + 3
        ax.axvline(xoff - 2, color=LINE, lw=.8, alpha=.6)
    ax.axhline(0, color=LINE, lw=1.2)
    for x, t in ticks:
        ax.text(x, -.5, t, ha="center", fontsize=10.5, color=INK, fontweight="bold")
    ax.set_ylim(-.55, .58); ax.axis("off")
    ax.set_title("EL FLUJO DE TODO SU MUNDIAL — amenaza neta por ventanas de 5' (rojo = domina España)",
                 fontsize=15, fontweight="bold", color=INK, pad=8, path_effects=PATH_EFF)

    fig.text(.5, .045, "La final en una línea: 20 tiros a 2 · xG 2.09-0.14 · momentum 24/29 ventanas",
             ha="center", fontsize=13, color=SPAIN, fontweight="bold")
    fig.text(.01, .012, "xG/xT/momentum: modelos propios (Markov 16×12 · 462K tiros de entrenamiento) · datos: WhoScored/Opta · MOVA — Orbital Lab · @jzuluaga",
             fontsize=9, color=MUTED)
    fig.savefig(OUT / "dash_spain.png", dpi=140)
    print("→ dash_spain.png")


# ================= MESSI =================
def dash_messi():
    me = EV[EV.player_name == "Lionel Messi"]
    arg_m = MATCHES[(MATCHES.home_team == "Argentina") | (MATCHES.away_team == "Argentina")].sort_values("start_utc")
    xt = np.load(OUT / "xt_grid.npy"); nx_, ny_ = xt.shape
    def zv(x, y): return xt[np.clip((np.asarray(x) / 100 * nx_).astype(int), 0, nx_ - 1),
                            np.clip((np.asarray(y) / 100 * ny_).astype(int), 0, ny_ - 1)]

    fig = plt.figure(figsize=(19, 22))
    gs = fig.add_gridspec(3, 3, left=.035, right=.965, top=.83, bottom=.10,
                          hspace=.34, wspace=.15, height_ratios=[1.2, 1, .9])

    fig.text(.5, .965, "MESSI · 39 AÑOS · LA ÚLTIMA FUNCIÓN", ha="center", fontsize=32,
             fontweight="bold", color=INK)
    fig.text(.5, .946, "todo su Mundial 2026 en datos — el modelo lo pone #1 en amenaza generada por pase",
             ha="center", fontsize=12.5, color=MUTED)
    chips(fig, .918, [("5.40", "xT — #1 del Mundial"), ("8", "goles (7 de zurda)"), ("4", "asistencias"),
                      ("28", "regates — líder"), ("20", "faltas recibidas — líder"), ("12/18", "goles ARG con su sello")], MESSI)

    # (1,1-2) territory + open play xT passes
    ax = fig.add_subplot(gs[0, :2]); p = pitch_ax(ax)
    cmap = LinearSegmentedColormap.from_list("m", [PANEL, MESSI])
    acts = me[me.x.notna()]
    p.kdeplot(acts.x, acts.y, ax=ax, fill=True, levels=70, thresh=.04, cut=3, cmap=cmap)
    P = open_play(me[(me.event_type == "Pass") & (me.outcome == "Successful")].dropna(subset=["end_x", "end_y"])).copy()
    P["gain"] = zv(P.end_x, P.end_y) - zv(P.x, P.y)
    for r in P.nlargest(14, "gain").itertuples():
        p.arrows(r.x, r.y, r.end_x, r.end_y, ax=ax, color=ACCENT, width=1.8, headwidth=5.5,
                 headlength=5.5, alpha=.9, zorder=4)
    ptitle(ax, "El territorio del mago + sus 14 pases más letales (solo juego abierto)",
           "densidad de TODAS sus acciones — la media cancha derecha de siempre · flechas = mayor ganancia de amenaza (xT propio)")

    # (1,3) shots half pitch
    ax = fig.add_subplot(gs[0, 2])
    vp = VerticalPitch(pitch_type="opta", half=True, pitch_color=PANEL, line_color=LINE,
                       linewidth=1.1, goal_type="box", corner_arcs=True)
    vp.draw(ax=ax)
    sh = me[me.event_type.isin(SHOTS_T)]
    big = sh.qualifiers.str.contains("BigChance", na=False)
    pen = sh.qualifiers.str.contains('"Penalty"', na=False)
    goals = sh.event_type == "Goal"
    vp.scatter(sh[~goals & ~pen].x, sh[~goals & ~pen].y, s=130 + 170 * big[~goals & ~pen], marker="o",
               c="None", edgecolors=MUTED, ax=ax, zorder=3)
    vp.scatter(sh[goals].x, sh[goals].y, s=420, marker="football", c="None", edgecolors=MESSI, ax=ax, zorder=4)
    vp.scatter(sh[pen & ~goals].x, sh[pen & ~goals].y, s=300, marker="X", c="#e4353f", ax=ax, zorder=5)
    ptitle(ax, "Sus tiros", "balón = gol (8) · X rojo = los 2 penales fallados · tamaño = ocasión clara")

    # (2,1) chance creation
    ax = fig.add_subplot(gs[1, 0]); p = pitch_ax(ax)
    kp = me[(me.event_type == "Pass") & me.qualifiers.str.contains("KeyPass", na=False)]
    for r in kp.itertuples():
        is_assist = "IntentionalGoalAssist" in (r.qualifiers or "")
        ax.add_patch(patches.FancyArrowPatch((r.x, r.y), (r.end_x, r.end_y), arrowstyle="->",
                     mutation_scale=10, color=ACCENT if is_assist else MUTED,
                     lw=1.8 if is_assist else .9, alpha=1 if is_assist else .55, zorder=4))
    ptitle(ax, f"Ocasiones creadas — {len(kp)} pases clave", "verde = sus 4 asistencias")

    # (2,2) take-ons
    ax = fig.add_subplot(gs[1, 1]); p = pitch_ax(ax)
    to = me[me.event_type == "TakeOn"]
    ok = to.outcome == "Successful"
    p.scatter(to[ok].x, to[ok].y, s=160, c=MESSI, edgecolor=BG, lw=.8, ax=ax, zorder=4)
    p.scatter(to[~ok].x, to[~ok].y, s=110, c="None", edgecolor=MUTED, lw=1.2, ax=ax, zorder=3)
    ax.text(3, 92, f"{ok.sum()}/{len(to)} regates — líder del torneo", fontsize=11, color=MESSI, fontweight="bold")
    ptitle(ax, "El 1v1 sigue vivo", "celeste = regate exitoso · gris = fallido")

    # (2,3) goal mouth of his shots
    ax = fig.add_subplot(gs[1, 2]); ax.set_facecolor(PANEL)
    ax.set_xlim(-6, 106); ax.set_ylim(-8, 60); ax.axis("off")
    gx0, gx1, gz = 15, 85, 38
    ax.plot([gx0, gx0], [0, gz], color=LINE, lw=5); ax.plot([gx1, gx1], [0, gz], color=LINE, lw=5)
    ax.plot([gx0, gx1], [gz, gz], color=LINE, lw=5); ax.plot([gx0 - 8, gx1 + 8], [0, 0], color=MUTED, lw=2)
    ont = sh[sh.event_type.isin({"Goal", "SavedShot"})].dropna(subset=["goal_mouth_y", "goal_mouth_z"])
    gy = gx0 + (ont.goal_mouth_y - 45) / 10 * (gx1 - gx0)
    gzz = ont.goal_mouth_z / 46 * gz
    g = ont.event_type == "Goal"
    ax.scatter(gy[~g], gzz[~g], s=340, marker="o", c="None", edgecolor=MUTED, hatch="/////", lw=1.2)
    ax.scatter(gy[g], gzz[g], s=500, marker="o", c="None", edgecolor=MESSI, lw=2.6)
    ax.text(50, 52, "dónde puso cada tiro a puerta", ha="center", fontsize=12, color=INK, fontweight="bold")
    ax.text(50, -6, "celeste = sus 8 goles · rayado = atajados", ha="center", fontsize=9.5, color=MUTED)

    # (3, full) involvement timeline
    ax = fig.add_subplot(gs[2, :])
    ax.set_facecolor(BG); ax.axis("off")
    ax.set_xlim(-.5, len(arg_m) - .2); ax.set_ylim(-1.6, 2.1)
    for i, r in enumerate(arg_m.itertuples()):
        rival = r.away_team if r.home_team == "Argentina" else r.home_team
        score = f"{r.home_score}-{r.away_score}" if r.home_team == "Argentina" else f"{r.away_score}-{r.home_score}"
        mm = me[me.match_id == r.match_id]
        g = int(((mm.event_type == "Goal") & ~mm.qualifiers.str.contains("OwnGoal", na=False)).sum())
        a = int(mm.qualifiers.str.contains("IntentionalGoalAssist", na=False).sum())
        pen_f = int((mm.qualifiers.str.contains('"Penalty"', na=False) & (mm.event_type != "Goal") & (mm.is_shot == 1)).sum())
        won = (r.home_score > r.away_score) if r.home_team == "Argentina" else (r.away_score > r.home_score)
        final = rival == "Spain"
        col = MESSI if won else ("#e4353f" if final else MUTED)
        ax.scatter(i, 0, s=2600, c=PANEL, edgecolor=col, lw=2.5, zorder=3)
        ax.text(i, 0, f"{g}G" + (f" {a}A" if a else ""), ha="center", va="center", fontsize=11,
                color=col, fontweight="bold", zorder=4)
        ax.text(i, -.75, rival, ha="center", fontsize=10, color=INK)
        ax.text(i, -1.05, score, ha="center", fontsize=9, color=MUTED)
        if pen_f: ax.text(i, .62, "✕ penal fallado", ha="center", fontsize=9, color="#e4353f", fontweight="bold")
    ax.set_title("PARTIDO A PARTIDO — goles y asistencias hasta la final perdida (rojo)",
                 fontsize=14, fontweight="bold", color=INK, pad=6, path_effects=PATH_EFF)

    fig.text(.5, .062, "En la final: 2 tiros de todo su equipo, 0.14 xG — y 11 atajadas de Dibu. Los datos también escriben tragedias.",
             ha="center", fontsize=13, color=MUTED, fontstyle="italic")
    fig.text(.01, .012, "xT: modelo propio (Markov 16×12 entrenado con los 104 partidos) · datos: WhoScored/Opta · MOVA — Orbital Lab",
             fontsize=9, color=MUTED)
    fig.savefig(OUT / "dash_messi.png", dpi=140)
    print("→ dash_messi.png")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("all", "spain"): dash_spain()
    if which in ("all", "messi"): dash_messi()
