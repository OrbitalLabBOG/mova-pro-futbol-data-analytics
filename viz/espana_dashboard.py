"""Cap 4 — Dashboard España: 9 gráficos crudos (sin títulos) para evaluar en grilla.

Cada gráfico se guarda individual (transparente, para composición posterior) +
una grilla de contacto para revisión.

Uso: python viz/espana_dashboard.py
Salidas: outputs/divulgacion/espana/*.png + espana_grid.png
"""
import sqlite3, collections
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from mplsoccer import Pitch, VerticalPitch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "divulgacion" / "espana"
OUT.mkdir(parents=True, exist_ok=True)
db = sqlite3.connect(ROOT / "data" / "mundial.db")

BG, LINE, INK, MUTED = "#07090c", "#2a3038", "#e8e6e3", "#6b7280"
RED, GOLD, DIMRED = "#e4353f", "#ffd166", "#7a2830"
GRAY = "#3d434d"
PATH_EFF = [pe.Stroke(linewidth=2.6, foreground=BG), pe.Normal()]
SHOTS_T = ("Goal", "MissedShots", "SavedShot", "ShotOnPost")

plt.rcParams.update({"figure.facecolor": "none", "axes.facecolor": "none",
                     "savefig.facecolor": "none", "text.color": INK,
                     "font.family": "DejaVu Sans"})

SP_M = pd.read_sql("""SELECT match_id, home_team, away_team, home_score, away_score, start_utc
    FROM matches WHERE home_team='Spain' OR away_team='Spain' ORDER BY start_utc""", db)
MIDS = tuple(SP_M.match_id.tolist())


def save(fig, name):
    fig.savefig(OUT / name, dpi=150, transparent=True)
    plt.close(fig)
    print(f"→ {name}")


# ---------- A. TIMELINE: nunca fue perdiendo ----------
def chart_timeline():
    fig, ax = plt.subplots(figsize=(12, 5.2))
    for i, m in enumerate(SP_M.itertuples()):
        rival_away = m.home_team == "Spain"
        ev = pd.read_sql("""SELECT team_name, expanded_minute m, qualifiers FROM events
            WHERE match_id=? AND event_type='Goal' AND period!='PenaltyShootout'
            ORDER BY expanded_minute""", db, params=(m.match_id,))
        ev["og"] = ev.qualifiers.str.contains("OwnGoal", na=False)
        ev["for_spain"] = (ev.team_name == "Spain") ^ ev.og
        dur = pd.read_sql("SELECT MAX(expanded_minute) mx FROM events WHERE match_id=?",
                          db, params=(m.match_id,)).mx.iloc[0]
        y = 7 - i
        # estados: empate (tenue) / ganando (vivo) — España nunca estuvo perdiendo
        boundaries = [(0, "draw")]
        sp, rv = 0, 0
        for g in ev.itertuples():
            if g.for_spain: sp += 1
            else: rv += 1
            boundaries.append((g.m, "win" if sp > rv else ("draw" if sp == rv else "lose")))
        boundaries.append((dur, None))
        for (m0, st), (m1, _) in zip(boundaries[:-1], boundaries[1:]):
            col = {"draw": DIMRED, "win": RED, "lose": "#222"}[st]
            ax.barh(y, m1 - m0, left=m0, height=0.6, color=col, edgecolor="none")
        # goles
        for g in ev.itertuples():
            if g.for_spain:
                ax.scatter(g.m, y, s=110, color=GOLD, edgecolor=BG, lw=1.2, zorder=5)
            else:
                ax.scatter(g.m, y, s=150, color="#4a4f58", edgecolor=INK, lw=1.2, zorder=5,
                           marker="X")
    ax.axvline(90, color=MUTED, lw=1, ls="--", alpha=.6)
    ax.set_xlim(-1, 132); ax.set_ylim(-0.7, 7.7)
    ax.axis("off")
    save(fig, "a_timeline.png")


# ---------- B. RED DE RODRI ----------
def chart_red():
    fig, ax = plt.subplots(figsize=(8.6, 6.2))
    p = Pitch(pitch_type="opta", pitch_color="none", line_color=LINE, linewidth=1.0)
    p.draw(ax=ax)
    ev = pd.read_sql("""SELECT match_id, event_type, outcome, player_name, x, y,
        expanded_minute*60+COALESCE(second,0) t FROM events
        WHERE team_name='Spain' AND period!='PenaltyShootout'
        AND event_type IN ('Pass','TakeOn','Goal','MissedShots','SavedShot','BallTouch','Dispossessed')
        ORDER BY match_id, id""", db)
    passes = ev[(ev.event_type == "Pass") & (ev.outcome == "Successful")]
    top = passes.player_name.value_counts().head(11).index
    pos = passes[passes.player_name.isin(top)].groupby("player_name")[["x", "y"]].mean()
    edges = collections.Counter(); prev = None
    for r in ev.itertuples():
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
        z = 4 if (a, b) == special else 2
        ax.plot([pos.loc[a, "x"], pos.loc[b, "x"]], [pos.loc[a, "y"], pos.loc[b, "y"]],
                color=col, lw=.6 + 7 * w / mx, alpha=.25 + .6 * w / mx,
                solid_capstyle="round", zorder=z)
    vol = passes[passes.player_name.isin(top)].player_name.value_counts()
    rest = pos.drop(index="Rodri")
    s = 120 + 1100 * (vol / vol.max())
    ax.scatter(rest.x, rest.y, s=s.reindex(rest.index).fillna(120), color=BG, edgecolor=RED,
               lw=2, zorder=5)
    ax.scatter([pos.loc["Rodri", "x"]], [pos.loc["Rodri", "y"]], s=float(s["Rodri"]) * 1.3,
               color="white", edgecolor=GOLD, lw=2.6, zorder=6)
    save(fig, "b_red_rodri.png")


# ---------- C. CUBARSÍ: pases de mayor amenaza ----------
def chart_cubarsi():
    fig, ax = plt.subplots(figsize=(8.6, 6.2))
    p = Pitch(pitch_type="opta", pitch_color="none", line_color=LINE, linewidth=1.0)
    p.draw(ax=ax)
    xt = np.load(ROOT / "outputs" / "divulgacion" / "xt_grid.npy")
    nx_, ny_ = xt.shape
    def zv(x, y): return xt[np.clip((np.asarray(x) / 100 * nx_).astype(int), 0, nx_ - 1),
                            np.clip((np.asarray(y) / 100 * ny_).astype(int), 0, ny_ - 1)]
    P = pd.read_sql("""SELECT x, y, end_x, end_y, qualifiers FROM events
        WHERE player_name='Pau Cubarsí' AND event_type='Pass' AND outcome='Successful'
        AND end_x IS NOT NULL AND period!='PenaltyShootout'""", db)
    P = P[~P.qualifiers.str.contains("Corner|Freekick|ThrowIn|GoalKick", na=False)].copy()
    P = P[P.x < 58].copy()
    P["gain"] = zv(P.end_x, P.end_y) - zv(P.x, P.y)
    # todos sus pases tenues + top 16 en gualda
    ax.plot([P.x, P.end_x], [P.y, P.end_y], color=RED, lw=.55, alpha=.12)
    for r in P.nlargest(16, "gain").itertuples():
        p.arrows(r.x, r.y, r.end_x, r.end_y, ax=ax, color=GOLD, width=1.7,
                 headwidth=5.5, headlength=5.5, alpha=.92, zorder=4)
    ax.scatter([P.x.mean()], [P.y.mean()], s=800, color=BG, edgecolor=GOLD, lw=2.6, zorder=5)
    save(fig, "c_cubarsi.png")


# ---------- D. PRESSING INTELIGENTE ----------
def chart_pressing():
    fig, ax = plt.subplots(figsize=(8.6, 5))
    vals = []
    for m in SP_M.itertuples():
        rival = m.away_team if m.home_team == "Spain" else m.home_team
        hp = pd.read_sql("""SELECT SUM(CASE WHEN x>50 THEN 1 ELSE 0 END)*100.0/COUNT(*) p
            FROM events WHERE match_id=? AND team_name='Spain'
            AND event_type IN ('Tackle','Interception','BallRecovery','Challenge')""",
                         db, params=(m.match_id,)).p.iloc[0]
        vals.append((rival, hp))
    xs = np.arange(len(vals))
    colors = [RED if v > 45 else DIMRED for _, v in vals]
    ax.bar(xs, [v for _, v in vals], color=colors, width=.62)
    ax.axhline(np.mean([v for _, v in vals]), color=GOLD, lw=1.4, ls="--", alpha=.8)
    for sp in ax.spines.values(): sp.set_visible(False)
    ax.set_xticks([]); ax.set_yticks([])
    save(fig, "d_pressing.png")


# ---------- E. MOMENTUM torneo ----------
def chart_momentum():
    import json
    fig, ax = plt.subplots(figsize=(12, 3.6))
    mom = json.load(open(ROOT / "outputs" / "divulgacion" / "momentum_all.json"))
    spmom = [x for x in mom if x["home"] == "Spain" or x["away"] == "Spain"]
    order = {r.match_id: str(r.start_utc) for r in SP_M.itertuples()}
    spmom.sort(key=lambda x: order[x["match_id"]])
    xoff = 0
    for x in spmom:
        mm = SP_M[SP_M.match_id == x["match_id"]].iloc[0]
        sign = 1 if mm.home_team == "Spain" else -1
        w = sorted(((int(k), v * sign) for k, v in x["windows"].items()))
        xs = [xoff + i for i, _ in enumerate(w)]
        ys = [v for _, v in w]
        ax.bar(xs, ys, width=.9, color=[RED if v >= 0 else GRAY for v in ys])
        xoff += len(w) + 2.5
        ax.axvline(xoff - 1.5, color=LINE, lw=.8, alpha=.5)
    ax.axhline(0, color=MUTED, lw=1)
    ax.axis("off")
    save(fig, "e_momentum.png")


# ---------- F. RADAR percentiles ----------
def chart_radar():
    # metricas por equipo
    teams = [r[0] for r in db.execute("""SELECT team_name FROM events GROUP BY team_name
        HAVING COUNT(*) > 3000 AND team_name IS NOT NULL""")]
    rows = {}
    xga = pd.read_sql("""SELECT m.match_id, s.team, SUM(s.xg_model) xg FROM shot_xg s
        JOIN matches m USING(match_id) GROUP BY m.match_id, s.team""", db)
    for t in teams:
        nm = pd.read_sql("SELECT COUNT(DISTINCT match_id) n FROM events WHERE team_name=?",
                         db, params=(t,)).n.iloc[0]
        passes = pd.read_sql("""SELECT COUNT(*) c FROM events WHERE team_name=? AND event_type='Pass'""",
                             db, params=(t,)).c.iloc[0]
        opp_passes = pd.read_sql("""SELECT COUNT(*) c FROM events e WHERE event_type='Pass'
            AND team_name != ? AND match_id IN (SELECT match_id FROM events WHERE team_name=? GROUP BY match_id)""",
                                 db, params=(t, t)).c.iloc[0]
        tilt = pd.read_sql("""SELECT SUM(CASE WHEN team_name=? THEN 1 ELSE 0 END)*100.0/COUNT(*) v
            FROM events WHERE event_type='Pass' AND x>66 AND match_id IN
            (SELECT match_id FROM events WHERE team_name=? GROUP BY match_id)""",
                           db, params=(t, t)).v.iloc[0]
        height = pd.read_sql("""SELECT AVG(x) h FROM events WHERE team_name=? AND
            event_type IN ('Tackle','Interception','BallRecovery','Clearance','BlockedPass','Challenge')""",
                             db, params=(t,)).h.iloc[0]
        xg_own = xga[xga.team == t].xg.sum()
        mids = pd.read_sql("SELECT DISTINCT match_id FROM events WHERE team_name=?", db, params=(t,))
        xg_opp = xga[(xga.match_id.isin(mids.match_id)) & (xga.team != t)].xg.sum()
        rows[t] = dict(pos=passes / max(1, passes + opp_passes) * 100, tilt=tilt,
                       xg=xg_own / nm, xga=-xg_opp / nm, height=height)
    df = pd.DataFrame(rows).T
    pct = df.rank(pct=True) * 100
    sp = pct.loc["Spain"]
    labels = ["POSESIÓN", "TERRITORIO", "PELIGRO\nCREADO", "SOLIDEZ", "ALTURA"]
    vals = [sp.pos, sp.tilt, sp.xg, sp.xga, sp.height]
    ang = np.linspace(0, 2 * np.pi, len(vals), endpoint=False)
    vals_c = vals + [vals[0]]; ang_c = list(ang) + [ang[0]]
    fig = plt.figure(figsize=(6.4, 6.4))
    ax = fig.add_subplot(111, projection="polar")
    ax.set_facecolor("none")
    for r_ring in [25, 50, 75, 100]:
        ax.plot(np.linspace(0, 2 * np.pi, 100), [r_ring] * 100, color=LINE, lw=.7, alpha=.6)
    ax.fill(ang_c, vals_c, color=RED, alpha=.28)
    ax.plot(ang_c, vals_c, color=RED, lw=2.4)
    ax.scatter(ang, vals, s=90, color=GOLD, edgecolor=BG, lw=1.2, zorder=5)
    ax.set_xticks(ang)
    ax.set_xticklabels(labels, fontsize=10.5, color=INK, fontweight="bold")
    ax.tick_params(pad=20)
    fig.subplots_adjust(left=.12, right=.88, top=.88, bottom=.12)
    ax.set_yticks([]); ax.set_ylim(0, 105)
    ax.spines["polar"].set_visible(False)
    ax.grid(False)
    save(fig, "f_radar.png")


# ---------- G. PASES PROGRESIVOS ----------
def chart_progresivos():
    fig, ax = plt.subplots(figsize=(8.6, 6.2))
    p = Pitch(pitch_type="opta", pitch_color="none", line_color=LINE, linewidth=1.0)
    p.draw(ax=ax)
    P = pd.read_sql("""SELECT x, y, end_x, end_y, qualifiers FROM events
        WHERE team_name='Spain' AND event_type='Pass' AND outcome='Successful'
        AND end_x IS NOT NULL AND period!='PenaltyShootout'""", db)
    P = P[~P.qualifiers.str.contains("Corner|Freekick|ThrowIn|GoalKick", na=False)]
    prog = P[((P.end_x - P.x) > 25) & (P.end_x > 66)]
    for lw_, al in [(2.0, .10), (.8, .30)]:
        ax.plot([prog.x, prog.end_x], [prog.y, prog.end_y], color=RED, lw=lw_, alpha=al,
                solid_capstyle="round")
    ends = prog[prog.end_x > 75]
    ax.scatter(ends.end_x, ends.end_y, s=10, color=GOLD, alpha=.5, zorder=4)
    save(fig, "g_progresivos.png")


# ---------- H. FÁBRICA DE OCASIONES ----------
def chart_ocasiones():
    from matplotlib import patches as mpatches
    fig, ax = plt.subplots(figsize=(8.6, 6.2))
    p = Pitch(pitch_type="opta", pitch_color="none", line_color=LINE, linewidth=1.0)
    p.draw(ax=ax)
    kp = pd.read_sql("""SELECT x, y, end_x, end_y, qualifiers FROM events
        WHERE team_name='Spain' AND event_type='Pass'
        AND qualifiers LIKE '%KeyPass%' AND period!='PenaltyShootout'""", db)
    for r in kp.itertuples():
        is_assist = "IntentionalGoalAssist" in (r.qualifiers or "")
        ax.add_patch(mpatches.FancyArrowPatch((r.x, r.y), (r.end_x, r.end_y), arrowstyle="->",
                     mutation_scale=10, color=GOLD if is_assist else RED,
                     lw=2.2 if is_assist else .9, alpha=1 if is_assist else .5, zorder=4))
    ax.set_xlim(42, 101.5)
    save(fig, "h_ocasiones.png")


# ---------- I. ROBOS ALTOS ----------
def chart_robos():
    from matplotlib import patches as mpatches
    fig, ax = plt.subplots(figsize=(8.6, 6.2))
    p = Pitch(pitch_type="opta", pitch_color="none", line_color=LINE, linewidth=1.0)
    p.draw(ax=ax)
    ht = pd.read_sql("""SELECT x, y FROM events WHERE team_name='Spain'
        AND event_type IN ('BallRecovery','Interception') AND period!='PenaltyShootout'""", db)
    ht = ht[np.hypot(100 - ht.x, 50 - ht.y) <= 40]
    circ = mpatches.Circle((100, 50), 40, color=RED, fill=True, alpha=.13, zorder=1)
    ax.add_artist(circ)
    arc = mpatches.Arc((100, 50), 80, 80, theta1=90, theta2=270, color=RED, lw=1.6, ls="--", alpha=.7)
    ax.add_artist(arc)
    ax.scatter(ht.x, ht.y, s=90, c=RED, edgecolor=BG, lw=.9, alpha=.92, zorder=3)
    save(fig, "i_robos.png")


CHARTS = [chart_timeline, chart_red, chart_cubarsi, chart_pressing, chart_momentum,
          chart_radar, chart_progresivos, chart_ocasiones, chart_robos]

if __name__ == "__main__":
    for fn in CHARTS:
        fn()
    # grilla de contacto sobre fondo oscuro
    from PIL import Image
    names = ["a_timeline", "b_red_rodri", "c_cubarsi", "d_pressing", "e_momentum",
             "f_radar", "g_progresivos", "h_ocasiones", "i_robos"]
    cols, rows = 3, 3
    cw, chh = 860, 620
    grid = Image.new("RGB", (cols * cw, rows * chh), (7, 9, 12))
    for i, n in enumerate(names):
        im = Image.open(OUT / f"{n}.png").convert("RGBA")
        r = min(cw / im.width, chh / im.height) * 0.94
        im = im.resize((int(im.width * r), int(im.height * r)), Image.LANCZOS)
        x = (i % cols) * cw + (cw - im.width) // 2
        y = (i // cols) * chh + (chh - im.height) // 2
        grid.paste(im, (x, y), im)
    grid.save(OUT / "espana_grid.png")
    print("→ espana_grid.png")
