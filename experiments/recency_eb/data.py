"""Causal data loaders and frozen 1.1.0 model helpers for exp-recency-eb.

Offline / box-only. Never contacts VPS or FPL APIs and never modifies production models.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from mova_fpl.data.identity import player_key as name_player_key
from mova_fpl.data.store import PLAYABLE_POSITIONS, Store
from mova_fpl.models.features.points_features import RecencyEBConfig
from mova_fpl.rules.base import Position, Squad, SquadPlayer

NOTES_ROOT = Path("/workspace/mova-fpl-notes/mlops")
EXP_ROOT = NOTES_ROOT / "exp-recency-eb"
VAASTAV_ROOT = EXP_ROOT / "data" / "vaastav"
LIVE_DATA_ROOT = NOTES_ROOT / "data"
RAW_ENTRY_ROOT = EXP_ROOT / "raw"
MODELS_ROOT = NOTES_ROOT / "models"

POS_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

JULIAN_GW1_ELEMENTS = (
    109, 8, 418, 11, 557, 426, 427, 124, 346, 165, 411, 496, 565, 329, 173,
)

# Columns permitted in pre-deadline roster (mirrors Store.ROSTER_COLS strictly)
ROSTER_COLS = list(Store.ROSTER_COLS)


def _install_sklearn_loss_shim() -> None:
    """Allow unpickling sklearn 1.7.2 HistGradientBoostingClassifier under sklearn 1.9.x."""
    if "_loss" not in sys.modules:
        import sklearn._loss._loss as _sk_loss
        sys.modules["_loss"] = _sk_loss


def load_frozen_models(models_root: Path = MODELS_ROOT) -> tuple[object, object]:
    """Load frozen production minutes-1.1.0 and points-1.1.0 joblibs (read-only)."""
    _install_sklearn_loss_shim()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        minutes_model = joblib.load(models_root / "minutes" / "minutes-1.1.0.joblib")
        points_model = joblib.load(models_root / "points" / "points-1.1.0.joblib")
    return minutes_model, points_model


def make_eb_points_model(points_prod, cfg: RecencyEBConfig, version: str = "1.2.0-eb"):
    """Create an opt-in EB2 candidate copy of the frozen 1.1.0 PointsModel."""
    cand = copy.deepcopy(points_prod)
    cand.version = version
    cand.player_recency_half_life = None
    cand.recency_mode = "eb2"
    cand.recency_eb = cfg
    return cand


def canonical_db_available() -> Path | None:
    env = os.environ.get("MOVA_CANONICAL_DB")
    if env and Path(env).exists():
        return Path(env)
    default = Path("/workspace/mova-fpl/data/processed/fpl_canonical.db")
    if default.exists():
        return default
    return None


def _attach_code_player_key(df: pd.DataFrame, players_raw: pd.DataFrame) -> pd.DataFrame:
    """Assign cross-season identity using FPL `code` from players_raw (never raw element)."""
    out = df.copy()
    id_to_code = dict(zip(
        pd.to_numeric(players_raw["id"], errors="coerce").dropna().astype(int),
        pd.to_numeric(players_raw["code"], errors="coerce").dropna().astype(int),
    ))
    codes = pd.to_numeric(out["element"], errors="coerce").map(id_to_code)
    fallback = out["name"].map(name_player_key) if "name" in out.columns else pd.Series(None, index=out.index)
    out["player_code"] = codes
    out["player_key"] = [
        f"code:{int(c)}" if pd.notna(c) else (str(fb) if pd.notna(fb) else f"el:{int(e)}")
        for c, fb, e in zip(codes, fallback, out["element"])
    ]
    return out


def load_vaastav_season(season: str) -> pd.DataFrame:
    """Load one season from vaastav merged_gw.csv + players_raw.csv with code-based player_key."""
    sdir = VAASTAV_ROOT / season
    mg = pd.read_csv(sdir / "merged_gw.csv", low_memory=False)
    pr = pd.read_csv(sdir / "players_raw.csv", low_memory=False)

    mg = mg.rename(columns={"GW": "gw", "xP": "xp_official"})
    mg["season"] = season
    mg["gw"] = pd.to_numeric(mg["gw"], errors="coerce").astype(int)
    mg["element"] = pd.to_numeric(mg["element"], errors="coerce").astype(int)
    mg["fixture"] = pd.to_numeric(mg["fixture"], errors="coerce").fillna(0).astype(int)
    if "was_home" in mg.columns:
        wh = mg["was_home"]
        if wh.dtype == bool:
            mg["was_home"] = wh.astype(int)
        else:
            mg["was_home"] = (
                wh.astype(str).str.lower().isin({"true", "1", "1.0"})
            ).astype(int)

    # Filter out non-playable assets (e.g., 2024-25 Assistant Manager 'AM')
    mg["position"] = mg["position"].astype(str).str.upper().str.strip()
    mg = mg[mg["position"].isin(PLAYABLE_POSITIONS)].copy()
    # vaastav 2025-26 has 10 exact duplicate player-fixture rows
    mg = mg.drop_duplicates(subset=["gw", "element", "fixture"], keep="first")

    mg = _attach_code_player_key(mg, pr)
    mg = mg.sort_values(["gw", "element", "fixture"]).reset_index(drop=True)
    return mg


def derive_equipos(season_df: pd.DataFrame) -> dict[int, str]:
    """Derive {opponent_team_id: team_name} from fixture pairings (pure calendar metadata)."""
    p = season_df.dropna(subset=["team", "opponent_team", "fixture"]).drop_duplicates(
        ["gw", "fixture", "team"]
    )
    mapping: dict[int, str] = {}
    for _, pair in p.groupby(["gw", "fixture"], sort=False):
        if len(pair) != 2:
            continue
        r1, r2 = pair.iloc[0], pair.iloc[1]
        mapping[int(r1["opponent_team"])] = str(r2["team"])
        mapping[int(r2["opponent_team"])] = str(r1["team"])
    return mapping


def load_season_2026_27() -> dict:
    """Build 2026-27 GW1-11 frame with zero price leakage and code-based player_key.

    - GW1-10: vaastav 2026-27 merged_gw.csv (100% verified identical to official live_2026_27_fx
      on points/minutes/xG/DefCon, with 0 transfer-team mismatches and exact point-in-time prices).
    - GW11: official live_2026_27_fx.csv (gw==11) joined with fixtures_2026_27.csv,
      teams_2026_27.csv, catalog_gw11.csv (as-of GW11 deadline price/team/position), and
      players_raw.csv (FPL persistent `code`).
    """
    v26 = load_vaastav_season("2026-27")
    pr26 = pd.read_csv(VAASTAV_ROOT / "2026-27" / "players_raw.csv", low_memory=False)
    live = pd.read_csv(LIVE_DATA_ROOT / "live_2026_27_fx.csv")
    fixtures = pd.read_csv(LIVE_DATA_ROOT / "fixtures_2026_27.csv")
    teams = pd.read_csv(LIVE_DATA_ROOT / "teams_2026_27.csv")
    cat11 = pd.read_csv(LIVE_DATA_ROOT / "catalog_gw11.csv")
    cat_latest = pd.read_csv(LIVE_DATA_ROOT / "catalog_latest.csv")
    cat_asof = pd.read_csv(LIVE_DATA_ROOT / "catalog_asof_gw8_11.csv")
    proj_approved = pd.read_csv(LIVE_DATA_ROOT / "proj_approved_gw8_11.csv")

    id_to_team = dict(zip(teams["team_id"].astype(int), teams["name"].astype(str)))

    # Build GW11 rows from official live + catalog_gw11 (fallback catalog_latest for 2 late 0-min adds)
    l11 = live[live["gw"] == 11].copy()
    l11["element"] = l11["element"].astype(int)
    cat11_meta = cat11[["element", "web_name", "first_name", "second_name",
                        "team_id", "element_type", "now_cost"]].copy()
    missing_els = set(l11["element"]) - set(cat11_meta["element"])
    if missing_els:
        extra = cat_latest[cat_latest["element"].isin(missing_els)][
            ["element", "web_name", "first_name", "second_name", "team_id", "element_type", "now_cost"]
        ].copy()
        cat11_meta = pd.concat([cat11_meta, extra], ignore_index=True)

    fx11 = fixtures.rename(columns={"fixture_id": "fixture"}).copy()
    m11 = l11.merge(fx11, left_on="fixture_id", right_on="fixture", how="left", suffixes=("", "_fx"))
    m11 = m11.merge(cat11_meta, on="element", how="left")
    m11["season"] = "2026-27"
    m11["gw"] = 11
    m11["fixture"] = pd.to_numeric(m11["fixture"], errors="coerce").fillna(0).astype(int)
    m11["position"] = m11["element_type"].map(POS_MAP)
    m11["team_id"] = pd.to_numeric(m11["team_id"], errors="coerce").astype("Int64")
    m11["was_home"] = (m11["team_id"] == m11["team_h"]).astype(int)
    m11["opponent_team"] = np.where(m11["was_home"] == 1, m11["team_a"], m11["team_h"]).astype(int)
    m11["team"] = m11["team_id"].map(id_to_team)
    m11["value"] = pd.to_numeric(m11["now_cost"], errors="coerce")
    m11["name"] = (m11["first_name"].fillna("") + " " + m11["second_name"].fillna("")).str.strip()
    m11["round"] = 11
    m11 = _attach_code_player_key(m11, pr26)

    # Align columns with v26
    common_cols = [c for c in v26.columns if c in m11.columns]
    df_26 = pd.concat([v26, m11[common_cols]], ignore_index=True, sort=False)
    df_26 = df_26.sort_values(["gw", "element", "fixture"]).reset_index(drop=True)

    # Full 38-GW team schedule from official fixtures_2026_27.csv (pure calendar)
    sched_rows = []
    for r in fixtures.dropna(subset=["gw"]).itertuples(index=False):
        gw_i = int(r.gw)
        th = id_to_team.get(int(r.team_h))
        ta = id_to_team.get(int(r.team_a))
        if th:
            sched_rows.append({"season": "2026-27", "gw": gw_i, "team": th, "fixture": int(r.fixture_id)})
        if ta:
            sched_rows.append({"season": "2026-27", "gw": gw_i, "team": ta, "fixture": int(r.fixture_id)})
    sched_df = pd.DataFrame(sched_rows)

    # Julian's real GW1 picks and season history (human reference)
    gw1_picks_json = json.loads((RAW_ENTRY_ROOT / "entry-picks-gw1.json").read_text(encoding="utf-8"))
    entry_history_json = json.loads((RAW_ENTRY_ROOT / "entry-history.json").read_text(encoding="utf-8"))
    entry_transfers_json = json.loads((RAW_ENTRY_ROOT / "entry-transfers.json").read_text(encoding="utf-8"))

    # Build Julian's GW1 Squad using GW1 vaastav prices (never current now_cost)
    gw1_roster = build_roster(df_26, 1)
    gw1_by_el = gw1_roster.set_index("element")
    picks = gw1_picks_json["picks"]
    players = []
    starters = []
    bench = []
    captain = None
    vice = None
    for p in sorted(picks, key=lambda x: int(x["position"])):
        el = int(p["element"])
        row = gw1_by_el.loc[el]
        price = float(row["value"]) / 10.0
        players.append(SquadPlayer(
            element=el,
            position=Position.parse(str(row["position"])),
            team=str(row["team"]),
            price=price,
            purchase_price=price,
        ))
        if int(p["position"]) <= 11:
            starters.append(el)
        else:
            bench.append(el)
        if p.get("is_captain"):
            captain = el
        if p.get("is_vice_captain"):
            vice = el

    julian_gw1_squad = Squad(
        players=tuple(players),
        starters=tuple(starters),
        captain=captain,
        vice_captain=vice,
        bench_order=tuple(bench),
        bank=float(gw1_picks_json["entry_history"]["bank"]) / 10.0,
    )

    return {
        "df": df_26,
        "equipos": id_to_team,
        "schedule_df": sched_df,
        "fixtures": fixtures,
        "teams": teams,
        "catalog_asof_gw8_11": cat_asof,
        "proj_approved_gw8_11": proj_approved,
        "julian_gw1_squad": julian_gw1_squad,
        "julian_history": entry_history_json,
        "julian_transfers": entry_transfers_json,
        "players_raw": pr26,
    }


def build_roster(season_df: pd.DataFrame, gw: int) -> pd.DataFrame:
    """Strictly pre-deadline roster for `gw` (same contract as Store.roster)."""
    sub = season_df[season_df["gw"] == int(gw)].copy()
    playable = sub["position"].astype("string").str.upper().isin(PLAYABLE_POSITIONS)
    sub = sub.loc[playable].drop_duplicates(subset=["element"], keep="first")
    cols = [c for c in ROSTER_COLS if c in sub.columns]
    return sub[cols].sort_values("element").reset_index(drop=True)


def build_results(season_df: pd.DataFrame, gw: int) -> pd.DataFrame:
    """Post-GW oracle results for scoring/evaluation ONLY (never fed to models)."""
    return season_df[season_df["gw"] == int(gw)].sort_values(["element", "fixture"]).reset_index(drop=True)


def team_schedule_counts(df_or_sched: pd.DataFrame, gw_from: int, gw_to: int) -> dict[tuple[str, int], int]:
    """{(team, gw): n_fixtures} over [gw_from, gw_to]. Pure calendar metadata."""
    sub = df_or_sched[
        (df_or_sched["gw"] >= int(gw_from))
        & (df_or_sched["gw"] <= int(gw_to))
        & df_or_sched["team"].notna()
    ]
    if sub.empty:
        return {}
    grp = sub.groupby(["team", "gw"])["fixture"].nunique()
    return {(str(team), int(gw)): int(cnt) for (team, gw), cnt in grp.items()}


def causal_history(prev_df: pd.DataFrame, curr_df: pd.DataFrame, target_gw: int) -> pd.DataFrame:
    """Return strictly causal history: full prev_season + curr_season rows with gw < target_gw."""
    curr_past = curr_df[curr_df["gw"] < int(target_gw)]
    if curr_past.empty:
        return prev_df.copy()
    out = pd.concat([prev_df, curr_past], ignore_index=True, sort=False)
    # Hard causal assertion
    in_curr = out["season"] == str(curr_df["season"].iloc[0])
    if in_curr.any() and int(out.loc[in_curr, "gw"].max()) >= int(target_gw):
        raise AssertionError(f"Causal violation: gw >= {target_gw} leaked into history")
    return out
