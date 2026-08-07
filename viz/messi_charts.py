"""Capítulo 5 — gráficos independientes para la infografía de Messi.

Genera piezas PNG transparentes y una grilla de revisión. No compone todavía la
lámina final: cada gráfico queda listo para escalar, rotar o superponer alrededor
del protagonista.

Uso:
    python viz/messi_charts.py

Salidas:
    outputs/divulgacion/messi/*.png
    outputs/divulgacion/messi/messi_grid_v1.png
"""

from pathlib import Path
import sqlite3

import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
from matplotlib import patches
from matplotlib.colors import LinearSegmentedColormap
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
from mplsoccer import Pitch, VerticalPitch


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "divulgacion" / "messi"
OUT.mkdir(parents=True, exist_ok=True)

FONT_DIR = ROOT / "ig" / "assets" / "fonts"
FONT_REG = fm.FontProperties(fname=FONT_DIR / "Barlow-Regular.ttf")
FONT_SEMI = fm.FontProperties(fname=FONT_DIR / "Barlow-SemiBold.ttf")
FONT_COND = fm.FontProperties(fname=FONT_DIR / "BarlowCondensed-Bold.ttf")

BG = "#050D19"
PANEL = "#0A1C30"
CYAN = "#75AADB"
ELECTRIC = "#82DDFF"
WHITE = "#F4F8FB"
MUTED = "#8DA3B8"
TURQUOISE = "#25DFC4"
CORAL = "#F04B5F"
GOLD = "#E8C56A"
PATH_EFF = [pe.Stroke(linewidth=3.2, foreground=BG), pe.Normal()]

plt.rcParams.update(
    {
        "figure.facecolor": "none",
        "axes.facecolor": "none",
        "savefig.facecolor": "none",
        "text.color": WHITE,
        "axes.labelcolor": MUTED,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
    }
)

DB = sqlite3.connect(ROOT / "data" / "mundial.db")
EV = pd.read_sql(
    """SELECT match_id, id, event_type, outcome, team_name, player_name,
              x, y, end_x, end_y, goal_mouth_y, goal_mouth_z, is_shot,
              is_goal, qualifiers, period, expanded_minute AS minute,
              expanded_minute*60+COALESCE(second,0) AS t
       FROM events
       WHERE period != 'PenaltyShootout'
       ORDER BY match_id, id""",
    DB,
)
MATCHES = pd.read_sql(
    """SELECT match_id, home_team, away_team, home_score, away_score, start_utc
       FROM matches""",
    DB,
)
MESSI = EV[EV.player_name == "Lionel Messi"].copy()
SHOTS_T = {"Goal", "MissedShots", "SavedShot", "ShotOnPost"}

XT = np.load(ROOT / "outputs" / "divulgacion" / "xt_grid.npy")
NX, NY = XT.shape


def zvalue(x, y):
    """Valor xT de la celda, siguiendo exactamente el modelo del proyecto."""
    xx = np.clip((np.asarray(x) / 100 * NX).astype(int), 0, NX - 1)
    yy = np.clip((np.asarray(y) / 100 * NY).astype(int), 0, NY - 1)
    return XT[xx, yy]


def open_play(df):
    return df[
        ~df.qualifiers.str.contains(
            "Corner|Freekick|ThrowIn|GoalKick|KickOff", na=False
        )
    ]


def save(fig, name, dpi=190):
    path = OUT / name
    fig.savefig(path, dpi=dpi, transparent=True, bbox_inches="tight", pad_inches=0.16)
    plt.close(fig)
    print(f"→ {path.relative_to(ROOT)}")


def title(fig, main, sub, x=0.05, y=0.965, align="left"):
    fig.text(
        x,
        y,
        main,
        ha=align,
        va="top",
        color=WHITE,
        fontsize=24,
        fontproperties=FONT_COND,
        path_effects=PATH_EFF,
    )
    fig.text(
        x,
        y - 0.055,
        sub,
        ha=align,
        va="top",
        color=MUTED,
        fontsize=10.5,
        fontproperties=FONT_REG,
    )


def chart_territory():
    """Huella de acciones + pases de mayor ganancia xT."""
    fig, ax = plt.subplots(figsize=(10, 7.2))
    fig.subplots_adjust(left=0.03, right=0.97, bottom=0.03, top=0.82)
    pitch = Pitch(
        pitch_type="opta",
        pitch_color="none",
        line_color=ELECTRIC,
        linewidth=1.35,
        goal_type="box",
        corner_arcs=True,
        line_alpha=0.72,
        line_zorder=3,
    )
    pitch.draw(ax=ax)

    actions = MESSI.dropna(subset=["x", "y"])
    cmap = LinearSegmentedColormap.from_list(
        "messi_density", ["#050D1900", "#174D76AA", "#75AADBDD", "#82DDFFFF"]
    )
    pitch.kdeplot(
        actions.x,
        actions.y,
        ax=ax,
        fill=True,
        levels=70,
        thresh=0.035,
        cut=3,
        cmap=cmap,
        zorder=1,
    )

    passes = open_play(
        MESSI[
            (MESSI.event_type == "Pass") & (MESSI.outcome == "Successful")
        ].dropna(subset=["x", "y", "end_x", "end_y"])
    ).copy()
    passes["xt_gain"] = (
        zvalue(passes.end_x, passes.end_y) - zvalue(passes.x, passes.y)
    ).clip(0)
    top = passes.nlargest(14, "xt_gain")
    for rank, row in enumerate(top.itertuples()):
        color = GOLD if rank < 3 else TURQUOISE
        alpha = 1.0 if rank < 3 else 0.74
        pitch.arrows(
            row.x,
            row.y,
            row.end_x,
            row.end_y,
            ax=ax,
            color=color,
            width=2.0 if rank < 3 else 1.35,
            headwidth=5.5,
            headlength=5.5,
            alpha=alpha,
            zorder=5,
        )

    ax.scatter(
        76,
        50,
        s=3400,
        facecolor="none",
        edgecolor=ELECTRIC,
        lw=0.8,
        alpha=0.16,
        zorder=2,
    )
    ax.text(
        98,
        4,
        "ATAQUE >",
        ha="right",
        va="bottom",
        color=ELECTRIC,
        fontsize=9,
        fontproperties=FONT_SEMI,
    )
    title(
        fig,
        "EL MAPA DEL MAGO",
        "todas sus acciones · 14 pases de mayor amenaza · dorado = top 3",
    )
    fig.text(
        0.95,
        0.95,
        "5.40 xT",
        ha="right",
        va="top",
        color=GOLD,
        fontsize=22,
        fontproperties=FONT_COND,
        path_effects=PATH_EFF,
    )
    save(fig, "01_territorio_xt.png")


def chart_efficiency():
    """Volumen vs amenaza por pase entre jugadores con muestra robusta."""
    all_passes = EV[
        (EV.event_type == "Pass") & (EV.outcome == "Successful")
    ].dropna(subset=["x", "y", "end_x", "end_y"])
    all_passes = open_play(all_passes).copy()
    all_passes["xt_gain"] = (
        zvalue(all_passes.end_x, all_passes.end_y)
        - zvalue(all_passes.x, all_passes.y)
    ).clip(0)
    data = (
        all_passes.groupby(["player_name", "team_name"])
        .agg(passes=("xt_gain", "size"), xt=("xt_gain", "sum"))
        .reset_index()
    )
    data = data[data.passes >= 120].copy()
    data["xt_per_pass"] = data.xt / data.passes

    fig, ax = plt.subplots(figsize=(8.3, 7.2))
    fig.subplots_adjust(left=0.12, right=0.96, bottom=0.12, top=0.80)
    ax.scatter(
        data.passes,
        data.xt_per_pass * 100,
        s=34 + data.xt * 30,
        color=CYAN,
        alpha=0.24,
        edgecolor="none",
        zorder=2,
    )

    med_x = data.passes.median()
    med_y = data.xt_per_pass.median() * 100
    ax.axvline(med_x, color=ELECTRIC, lw=0.8, alpha=0.22, ls="--")
    ax.axhline(med_y, color=ELECTRIC, lw=0.8, alpha=0.22, ls="--")

    me = data[data.player_name == "Lionel Messi"].iloc[0]
    ax.scatter(
        me.passes,
        me.xt_per_pass * 100,
        s=720,
        color=GOLD,
        edgecolor=WHITE,
        lw=1.6,
        zorder=8,
    )
    ax.scatter(
        me.passes,
        me.xt_per_pass * 100,
        s=1350,
        facecolor="none",
        edgecolor=GOLD,
        lw=1.1,
        alpha=0.45,
        zorder=7,
    )
    ax.annotate(
        "MESSI\n306 PASES · 1.77 xT/100",
        (me.passes, me.xt_per_pass * 100),
        xytext=(38, -6),
        textcoords="offset points",
        color=WHITE,
        fontsize=12,
        fontproperties=FONT_COND,
        path_effects=PATH_EFF,
        arrowprops=dict(arrowstyle="-", color=GOLD, lw=1.2),
        zorder=9,
    )

    # Contexto: etiquetar solamente referentes que explican los extremos.
    label_names = {
        "Rodri",
        "Vitinha",
        "Pedri",
        "Alistair Johnston",
        "Leandro Trossard",
        "Kylian Mbappé",
    }
    for row in data[data.player_name.isin(label_names)].itertuples():
        ax.annotate(
            row.player_name.split()[-1].upper(),
            (row.passes, row.xt_per_pass * 100),
            xytext=(5, 5),
            textcoords="offset points",
            color=MUTED,
            fontsize=7.5,
            fontproperties=FONT_SEMI,
        )

    ax.text(
        0.98,
        0.96,
        "MÁS VALOR POR TOQUE",
        transform=ax.transAxes,
        ha="right",
        va="top",
        color=TURQUOISE,
        fontsize=9,
        fontproperties=FONT_SEMI,
    )
    ax.set_xlabel("PASES COMPLETADOS", fontproperties=FONT_SEMI, fontsize=9)
    ax.set_ylabel("xT POR 100 PASES", fontproperties=FONT_SEMI, fontsize=9)
    ax.grid(color=ELECTRIC, lw=0.55, alpha=0.10)
    for spine in ax.spines.values():
        spine.set_color(ELECTRIC)
        spine.set_alpha(0.24)
    ax.tick_params(labelsize=8, length=0)
    title(
        fig,
        "TOCA MENOS. VALE MÁS.",
        "jugadores con 120+ pases completados · tamaño = xT total",
    )
    save(fig, "02_eficiencia_xt.png")


def chart_shots():
    """Mapa de remates con énfasis en goles y penales fallados."""
    fig, ax = plt.subplots(figsize=(7.2, 8.4))
    fig.subplots_adjust(left=0.03, right=0.97, bottom=0.025, top=0.82)
    pitch = VerticalPitch(
        pitch_type="opta",
        half=True,
        pitch_color="none",
        line_color=ELECTRIC,
        linewidth=1.35,
        goal_type="box",
        corner_arcs=True,
        line_alpha=0.72,
        line_zorder=2,
    )
    pitch.draw(ax=ax)
    shots = MESSI[MESSI.event_type.isin(SHOTS_T)].copy()
    goals = shots.event_type.eq("Goal") & ~shots.qualifiers.str.contains(
        "OwnGoal", na=False
    )
    penalties = shots.qualifiers.str.contains('"Penalty"', na=False)
    big = shots.qualifiers.str.contains("BigChance", na=False)

    misses = ~goals & ~penalties
    pitch.scatter(
        shots[misses].x,
        shots[misses].y,
        s=95 + 120 * big[misses].astype(int),
        marker="o",
        facecolor="none",
        edgecolor=CYAN,
        linewidth=1.25,
        alpha=0.66,
        ax=ax,
        zorder=4,
    )
    pitch.scatter(
        shots[goals].x,
        shots[goals].y,
        s=390,
        marker="football",
        c=GOLD,
        edgecolors=WHITE,
        ax=ax,
        zorder=6,
    )
    failed_pen = penalties & ~goals
    pen_x = shots.loc[failed_pen, "x"].to_numpy(copy=True)
    pen_y = shots.loc[failed_pen, "y"].to_numpy(copy=True)
    # Los dos lanzamientos parten del punto penal; separarlos apenas evita que
    # una X tape por completo a la otra sin falsear la zona del remate.
    if len(pen_y) == 2:
        pen_y = pen_y + np.array([-1.8, 1.8])
    pitch.scatter(
        pen_x,
        pen_y,
        s=330,
        marker="X",
        c=CORAL,
        edgecolors=BG,
        linewidth=1.0,
        ax=ax,
        zorder=7,
    )

    title(
        fig,
        "OCHO GOLES. DOS CICATRICES.",
        "balón = gol · círculo = remate · X coral = penal fallado",
    )
    fig.text(
        0.93,
        0.95,
        "8",
        ha="right",
        va="top",
        color=GOLD,
        fontsize=42,
        fontproperties=FONT_COND,
        path_effects=PATH_EFF,
    )
    fig.text(
        0.93,
        0.885,
        "GOLES",
        ha="right",
        color=WHITE,
        fontsize=10,
        fontproperties=FONT_SEMI,
    )
    save(fig, "03_mapa_tiros.png")


def chart_timeline():
    """Arco partido a partido: producción, penales fallados y derrota final."""
    arg_matches = MATCHES[
        (MATCHES.home_team == "Argentina") | (MATCHES.away_team == "Argentina")
    ].sort_values("start_utc")

    fig, ax = plt.subplots(figsize=(14.5, 4.5))
    fig.subplots_adjust(left=0.025, right=0.98, bottom=0.08, top=0.72)
    ax.set_xlim(-0.6, len(arg_matches) - 0.4)
    ax.set_ylim(-1.25, 1.25)
    ax.axis("off")

    xs = np.arange(len(arg_matches))
    ax.plot(xs, np.zeros_like(xs), color=ELECTRIC, lw=1.4, alpha=0.35, zorder=1)

    for i, match in enumerate(arg_matches.itertuples()):
        rival = (
            match.away_team if match.home_team == "Argentina" else match.home_team
        )
        gf = match.home_score if match.home_team == "Argentina" else match.away_score
        ga = match.away_score if match.home_team == "Argentina" else match.home_score
        mine = MESSI[MESSI.match_id == match.match_id]
        goals = int(
            (
                mine.event_type.eq("Goal")
                & ~mine.qualifiers.str.contains("OwnGoal", na=False)
            ).sum()
        )
        assists = int(
            mine.qualifiers.str.contains("IntentionalGoalAssist", na=False).sum()
        )
        failed_pen = int(
            (
                mine.qualifiers.str.contains('"Penalty"', na=False)
                & mine.event_type.ne("Goal")
                & mine.is_shot.eq(1)
            ).sum()
        )
        final = rival == "Spain"
        color = CORAL if final else (GOLD if goals + assists else CYAN)
        size = 980 if final else 720 + 120 * (goals + assists)
        ax.scatter(
            i,
            0,
            s=size,
            color=BG,
            edgecolor=color,
            lw=2.0,
            zorder=3,
        )
        ax.scatter(i, 0, s=45, color=color, zorder=4)
        ax.text(
            i,
            0.50,
            f"{goals}G" + (f" · {assists}A" if assists else ""),
            ha="center",
            va="bottom",
            color=color,
            fontsize=11,
            fontproperties=FONT_COND,
            path_effects=PATH_EFF,
        )
        if failed_pen:
            ax.text(
                i,
                0.84,
                "✕ PENAL" if failed_pen == 1 else f"✕ {failed_pen} PENALES",
                ha="center",
                color=CORAL,
                fontsize=8,
                fontproperties=FONT_SEMI,
            )
        ax.text(
            i,
            -0.48,
            rival.upper(),
            ha="center",
            va="top",
            color=WHITE,
            fontsize=8.5,
            fontproperties=FONT_SEMI,
        )
        ax.text(
            i,
            -0.72,
            f"{gf}—{ga}",
            ha="center",
            va="top",
            color=color,
            fontsize=13,
            fontproperties=FONT_COND,
        )

    ax.annotate(
        "",
        xy=(len(xs) - 1, 0),
        xytext=(len(xs) - 2, 0),
        arrowprops=dict(arrowstyle="->", color=CORAL, lw=1.8),
        zorder=2,
    )
    title(
        fig,
        "LA ÚLTIMA FUNCIÓN",
        "ocho partidos · goles y asistencias · el recorrido termina ante España",
        x=0.025,
    )
    fig.text(
        0.975,
        0.955,
        "12/18",
        ha="right",
        va="top",
        color=GOLD,
        fontsize=28,
        fontproperties=FONT_COND,
        path_effects=PATH_EFF,
    )
    fig.text(
        0.975,
        0.885,
        "GOLES ARG CON SU SELLO",
        ha="right",
        color=MUTED,
        fontsize=8,
        fontproperties=FONT_SEMI,
    )
    save(fig, "04_timeline.png")


def kpi_asset(value, label, detail, name, color=GOLD, progress=0.78):
    """Módulo orbital tipográfico; funciona solo o como satélite del protagonista."""
    fig, ax = plt.subplots(figsize=(4.2, 4.2))
    fig.subplots_adjust(0, 0, 1, 1)
    ax.set_xlim(-1.2, 1.2)
    ax.set_ylim(-1.2, 1.2)
    ax.set_aspect("equal")
    ax.axis("off")

    ax.add_patch(
        patches.Circle((0, 0), 0.83, fill=False, edgecolor=ELECTRIC, lw=1.0, alpha=0.22)
    )
    ax.add_patch(
        patches.Arc(
            (0, 0),
            1.78,
            1.78,
            theta1=92,
            theta2=92 + progress * 305,
            color=color,
            lw=5.2,
            capstyle="round",
        )
    )
    angle = np.deg2rad(92 + progress * 305)
    ax.scatter(
        0.89 * np.cos(angle),
        0.89 * np.sin(angle),
        s=95,
        color=WHITE,
        edgecolor=color,
        lw=1.5,
        zorder=4,
    )
    ax.text(
        0,
        0.14,
        value,
        ha="center",
        va="center",
        color=color,
        fontsize=50 if len(value) <= 3 else 40,
        fontproperties=FONT_COND,
        path_effects=PATH_EFF,
    )
    ax.text(
        0,
        -0.25,
        label,
        ha="center",
        va="center",
        color=WHITE,
        fontsize=12,
        fontproperties=FONT_COND,
    )
    ax.text(
        0,
        -0.46,
        detail,
        ha="center",
        va="center",
        color=MUTED,
        fontsize=8,
        fontproperties=FONT_REG,
    )
    save(fig, name, dpi=190)


def make_kpis():
    kpi_asset(
        "39",
        "AÑOS",
        "FINALISTA MÁS VETERANO",
        "05_kpi_39.png",
        color=CYAN,
        progress=0.84,
    )
    kpi_asset(
        "21",
        "GOLES",
        "RÉCORD EN MUNDIALES",
        "06_kpi_21.png",
        color=GOLD,
        progress=1.0,
    )
    kpi_asset(
        "5.40",
        "xT GENERADO",
        "#1 DEL TORNEO",
        "07_kpi_xt.png",
        color=TURQUOISE,
        progress=0.93,
    )
    kpi_asset(
        "12/18",
        "GOLES CON SU SELLO",
        "8 GOLES · 4 ASISTENCIAS",
        "08_kpi_influencia.png",
        color=GOLD,
        progress=12 / 18,
    )


def _contain(path, size):
    image = Image.open(path).convert("RGBA")
    scale = min(size[0] / image.width, size[1] / image.height)
    return image.resize(
        (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
        Image.Resampling.LANCZOS,
    )


def make_grid():
    """Contact sheet editorial para revisar el sistema antes de componer la lámina."""
    width, height = 2400, 2630
    canvas = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(canvas)
    reg = ImageFont.truetype(str(FONT_DIR / "Barlow-Regular.ttf"), 29)
    semi = ImageFont.truetype(str(FONT_DIR / "Barlow-SemiBold.ttf"), 28)
    cond = ImageFont.truetype(str(FONT_DIR / "BarlowCondensed-Bold.ttf"), 78)
    small_cond = ImageFont.truetype(str(FONT_DIR / "BarlowCondensed-Bold.ttf"), 31)

    draw.text((90, 54), "MESSI · SISTEMA GRÁFICO V1", font=cond, fill=WHITE)
    draw.text(
        (92, 133),
        "piezas independientes para LA ÚLTIMA FUNCIÓN — todavía no es la composición final",
        font=reg,
        fill=MUTED,
    )
    draw.line((92, 190, 2308, 190), fill=ELECTRIC, width=2)

    boxes = [
        (50, 230, 1420, 1065, "01 · TERRITORIO + xT", "01_territorio_xt.png"),
        (1450, 230, 2350, 1065, "03 · REMATES", "03_mapa_tiros.png"),
        (50, 1100, 1040, 1880, "02 · EFICIENCIA", "02_eficiencia_xt.png"),
        (1070, 1100, 2350, 1880, "04 · RECORRIDO", "04_timeline.png"),
    ]
    for x0, y0, x1, y1, label, filename in boxes:
        draw.rounded_rectangle(
            (x0, y0, x1, y1),
            radius=28,
            fill=PANEL,
            outline="#173650",
            width=2,
        )
        draw.text((x0 + 26, y0 + 18), label, font=small_cond, fill=ELECTRIC)
        image = _contain(OUT / filename, (x1 - x0 - 40, y1 - y0 - 82))
        px = x0 + (x1 - x0 - image.width) // 2
        py = y0 + 65 + (y1 - y0 - 65 - image.height) // 2
        canvas.paste(image, (px, py), image)

    kpis = [
        ("05_kpi_39.png", "EDAD"),
        ("06_kpi_21.png", "RÉCORD"),
        ("07_kpi_xt.png", "CREACIÓN"),
        ("08_kpi_influencia.png", "INFLUENCIA"),
    ]
    y0, y1 = 1920, 2525
    card_w = 555
    for i, (filename, label) in enumerate(kpis):
        x0 = 50 + i * 590
        x1 = x0 + card_w
        draw.rounded_rectangle(
            (x0, y0, x1, y1),
            radius=28,
            fill=PANEL,
            outline="#173650",
            width=2,
        )
        draw.text((x0 + 24, y0 + 18), f"0{i + 5} · {label}", font=semi, fill=ELECTRIC)
        image = _contain(OUT / filename, (card_w - 38, y1 - y0 - 65))
        canvas.paste(
            image,
            (x0 + (card_w - image.width) // 2, y0 + 60),
            image,
        )

    draw.text(
        (width - 60, height - 38),
        "MOVA MUNDIAL · CAPÍTULO 5 · WORK IN PROGRESS",
        anchor="rs",
        font=reg,
        fill=MUTED,
    )
    path = OUT / "messi_grid_v1.png"
    canvas.save(path, quality=96)
    print(f"→ {path.relative_to(ROOT)}")


if __name__ == "__main__":
    chart_territory()
    chart_efficiency()
    chart_shots()
    chart_timeline()
    make_kpis()
    make_grid()
