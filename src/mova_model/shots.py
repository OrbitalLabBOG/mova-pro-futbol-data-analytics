"""Extracción unificada de tiros (StatsBomb + WhoScored) con features comunes.

Solo features presentes en AMBOS proveedores (transferibilidad): distancia, ángulo,
parte del cuerpo {foot,head,other}, tipo de jugada {open,setpiece,corner,freekick,penalty}.
Penales se marcan (xg constante, fuera del fit). SIN freeze-frames.
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import geometry as geo

BODY = ["foot", "head", "other"]
PLAY = ["open", "setpiece", "corner", "freekick"]   # penalty se maneja aparte
# big_chance: señal de calidad de ocasión (WhoScored). Es el feature que captura
# mano a mano / contraataque claro que la geometría sola no ve. StatsBomb=0.
FEATURES = (["dist", "angle", "dist2"]
            + [f"body_{b}" for b in BODY] + [f"play_{p}" for p in PLAY]
            + ["big_chance"])


def _body(name: str) -> str:
    if not name:
        return "other"
    n = name.lower()
    if "foot" in n:
        return "foot"
    if "head" in n:
        return "head"
    return "other"


# ── StatsBomb ──────────────────────────────────────────────────────
def _sb_play_type(shot_type: str, play_pattern: str) -> str:
    if shot_type == "Penalty":
        return "penalty"
    if shot_type == "Free Kick":
        return "freekick"
    pp = (play_pattern or "")
    if pp == "From Corner":
        return "corner"
    if pp.startswith("From "):
        return "setpiece"
    return "open"


def from_statsbomb(raw_dir: Path) -> pd.DataFrame:
    rows = []
    for f in glob.glob(str(Path(raw_dir) / "*" / "*.json")):
        comp = Path(f).parent.name           # wc-2022 / wc-2018
        mid = Path(f).stem
        for i, e in enumerate(json.load(open(f))):
            if e.get("type") != "Shot":
                continue
            loc = e.get("location")
            if not isinstance(loc, list) or len(loc) < 2:
                continue
            gx, gy = geo.sb_to_xy(loc[0], loc[1])
            rows.append({
                "source": "statsbomb", "competition": comp, "match_id": mid,
                "shot_uid": e.get("id") or f"{mid}_{i}",
                "team": e.get("team"), "minute": e.get("minute"),
                "dist": geo.distance(gx, gy), "angle": geo.angle(gx, gy),
                "body_part": _body(e.get("shot_body_part")),
                "play_type": _sb_play_type(e.get("shot_type"), e.get("play_pattern")),
                "is_big_chance": 0,          # StatsBomb no expone BigChance
                "is_goal": int(e.get("shot_outcome") == "Goal"),
                "xg_sb": e.get("shot_statsbomb_xg"),
            })
    return pd.DataFrame(rows)


# ── WhoScored ──────────────────────────────────────────────────────
def _ws_play_type(qnames: set) -> str:
    if "Penalty" in qnames:
        return "penalty"
    if "DirectFreekick" in qnames or "DirectFreekickGoal" in qnames:
        return "freekick"
    if "FromCorner" in qnames:
        return "corner"
    if "SetPiece" in qnames:
        return "setpiece"
    return "open"


def _ws_body(qnames: set) -> str:
    if "RightFoot" in qnames or "LeftFoot" in qnames:
        return "foot"
    if "Head" in qnames:
        return "head"
    return "other"


def from_whoscored(conn) -> pd.DataFrame:
    rows = []
    cur = conn.execute(
        """SELECT e.match_id, e.ws_event_id, e.team_name, e.player_id, e.minute,
                  e.x, e.y, e.is_goal, e.qualifiers
           FROM events e WHERE e.is_shot=1 AND e.x IS NOT NULL AND e.y IS NOT NULL"""
    )
    for mid, uid, team, pid, minute, x, y, is_goal, quals in cur:
        qnames = {(q.get("type") or {}).get("displayName") for q in json.loads(quals or "[]")}
        gx, gy = geo.ws_to_xy(x, y)
        rows.append({
            "source": "whoscored", "match_id": str(mid), "shot_uid": str(uid),
            "team": team, "player_id": pid, "minute": minute,
            "dist": geo.distance(gx, gy), "angle": geo.angle(gx, gy),
            "body_part": _ws_body(qnames), "play_type": _ws_play_type(qnames),
            "is_big_chance": int("BigChance" in qnames), "is_goal": int(is_goal or 0),
        })
    return pd.DataFrame(rows)


# ── Matriz de diseño (idéntica para SB y WS) ───────────────────────
def design_matrix(df: pd.DataFrame) -> np.ndarray:
    X = pd.DataFrame(index=df.index)
    X["dist"] = df["dist"]
    X["angle"] = df["angle"]
    X["dist2"] = df["dist"] ** 2
    for b in BODY:
        X[f"body_{b}"] = (df["body_part"] == b).astype(int)
    for p in PLAY:
        X[f"play_{p}"] = (df["play_type"] == p).astype(int)
    X["big_chance"] = df["is_big_chance"] if "is_big_chance" in df else 0
    return X[FEATURES].to_numpy(dtype=float)
