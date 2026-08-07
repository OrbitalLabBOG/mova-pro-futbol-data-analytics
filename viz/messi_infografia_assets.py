"""Mapas transparentes y sin texto para la infografía final de Messi."""

from pathlib import Path
import sqlite3

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import numpy as np
import pandas as pd
from mplsoccer import Pitch, VerticalPitch


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "divulgacion" / "messi"
OUT.mkdir(parents=True, exist_ok=True)

BG = "#050D19"
CYAN = "#75AADB"
ELECTRIC = "#82DDFF"
WHITE = "#F4F8FB"
TURQUOISE = "#25DFC4"
CORAL = "#F04B5F"
GOLD = "#E8C56A"

db = sqlite3.connect(ROOT / "data" / "mundial.db")
ev = pd.read_sql(
    """SELECT match_id, event_type, outcome, player_name, x, y, end_x, end_y,
              qualifiers, period, is_shot
       FROM events WHERE period != 'PenaltyShootout'""",
    db,
)
messi = ev[ev.player_name == "Lionel Messi"].copy()
xt = np.load(ROOT / "outputs" / "divulgacion" / "xt_grid.npy")
nx, ny = xt.shape


def zvalue(x, y):
    xx = np.clip((np.asarray(x) / 100 * nx).astype(int), 0, nx - 1)
    yy = np.clip((np.asarray(y) / 100 * ny).astype(int), 0, ny - 1)
    return xt[xx, yy]


def open_play(df):
    return df[
        ~df.qualifiers.str.contains(
            "Corner|Freekick|ThrowIn|GoalKick|KickOff", na=False
        )
    ]


def save(fig, filename):
    fig.savefig(
        OUT / filename,
        dpi=220,
        transparent=True,
        bbox_inches="tight",
        pad_inches=0.01,
    )
    plt.close(fig)
    print(f"→ {(OUT / filename).relative_to(ROOT)}")


def territory():
    fig, ax = plt.subplots(figsize=(9, 5.8))
    fig.subplots_adjust(0, 0, 1, 1)
    pitch = Pitch(
        pitch_type="opta",
        pitch_color="none",
        line_color=ELECTRIC,
        linewidth=1.25,
        line_alpha=0.78,
        goal_type="box",
        corner_arcs=True,
        line_zorder=3,
    )
    pitch.draw(ax=ax)

    actions = messi.dropna(subset=["x", "y"])
    cmap = LinearSegmentedColormap.from_list(
        "density", ["#050D1900", "#174D7655", "#75AADB99", "#82DDFFDD"]
    )
    pitch.kdeplot(
        actions.x,
        actions.y,
        ax=ax,
        fill=True,
        levels=65,
        thresh=0.04,
        cut=3,
        cmap=cmap,
        zorder=1,
    )

    passes = open_play(
        messi[
            (messi.event_type == "Pass") & (messi.outcome == "Successful")
        ].dropna(subset=["x", "y", "end_x", "end_y"])
    ).copy()
    passes["xt_gain"] = (
        zvalue(passes.end_x, passes.end_y) - zvalue(passes.x, passes.y)
    ).clip(0)
    for rank, row in enumerate(passes.nlargest(14, "xt_gain").itertuples()):
        pitch.arrows(
            row.x,
            row.y,
            row.end_x,
            row.end_y,
            ax=ax,
            color=GOLD if rank < 3 else TURQUOISE,
            width=1.8 if rank < 3 else 1.2,
            headwidth=5.2,
            headlength=5.2,
            alpha=0.95 if rank < 3 else 0.72,
            zorder=5,
        )
    save(fig, "clean_territorio_xt.png")


def shots():
    fig, ax = plt.subplots(figsize=(6.2, 7.4))
    fig.subplots_adjust(0, 0, 1, 1)
    pitch = VerticalPitch(
        pitch_type="opta",
        half=True,
        pitch_color="none",
        line_color=ELECTRIC,
        linewidth=1.2,
        line_alpha=0.78,
        goal_type="box",
        corner_arcs=True,
        line_zorder=2,
    )
    pitch.draw(ax=ax)
    data = messi[messi.event_type.isin({"Goal", "MissedShots", "SavedShot", "ShotOnPost"})]
    goals = data.event_type.eq("Goal") & ~data.qualifiers.str.contains("OwnGoal", na=False)
    penalties = data.qualifiers.str.contains('"Penalty"', na=False)
    big = data.qualifiers.str.contains("BigChance", na=False)
    other = ~goals & ~penalties

    pitch.scatter(
        data.loc[other, "x"],
        data.loc[other, "y"],
        s=80 + 100 * big[other].astype(int),
        marker="o",
        facecolor=BG,
        edgecolor=CYAN,
        linewidth=1.15,
        alpha=0.72,
        ax=ax,
        zorder=4,
    )
    pitch.scatter(
        data.loc[goals, "x"],
        data.loc[goals, "y"],
        s=320,
        marker="football",
        c=GOLD,
        edgecolors=WHITE,
        ax=ax,
        zorder=6,
    )
    px = data.loc[penalties & ~goals, "x"].to_numpy(copy=True)
    py = data.loc[penalties & ~goals, "y"].to_numpy(copy=True)
    if len(py) == 2:
        py += np.array([-1.8, 1.8])
    pitch.scatter(
        px,
        py,
        s=285,
        marker="X",
        c=CORAL,
        edgecolors=BG,
        linewidth=0.9,
        ax=ax,
        zorder=7,
    )
    save(fig, "clean_mapa_tiros.png")


def takeons():
    """Asset opcional: constelación espacial de regates, también sin rótulos."""
    fig, ax = plt.subplots(figsize=(6.2, 7.4))
    fig.subplots_adjust(0, 0, 1, 1)
    pitch = VerticalPitch(
        pitch_type="opta",
        pitch_color="none",
        line_color=ELECTRIC,
        linewidth=1.1,
        line_alpha=0.55,
        goal_type="box",
        corner_arcs=True,
        line_zorder=2,
    )
    pitch.draw(ax=ax)
    data = messi[messi.event_type == "TakeOn"]
    good = data.outcome.eq("Successful")
    pitch.scatter(
        data.loc[~good, "x"],
        data.loc[~good, "y"],
        s=75,
        marker="o",
        facecolor=BG,
        edgecolor=CYAN,
        linewidth=1.0,
        alpha=0.42,
        ax=ax,
        zorder=3,
    )
    pitch.scatter(
        data.loc[good, "x"],
        data.loc[good, "y"],
        s=120,
        marker="o",
        c=TURQUOISE,
        edgecolors=WHITE,
        linewidth=0.45,
        alpha=0.9,
        ax=ax,
        zorder=4,
    )
    save(fig, "clean_regates.png")


if __name__ == "__main__":
    territory()
    shots()
    takeons()
