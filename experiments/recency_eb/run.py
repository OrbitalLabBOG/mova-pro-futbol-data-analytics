"""CLI runner for EXP-RECENCY-EB-2026-001 (points-1.2.0-eb vs prod 1.1.0).

Usage:
    python -m experiments.recency_eb.run all
    python -m experiments.recency_eb.run tune
    python -m experiments.recency_eb.run verify
    python -m experiments.recency_eb.run evaluate
    python -m experiments.recency_eb.run replay
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from experiments.recency_eb.data import (
    EXP_ROOT,
    canonical_db_available,
    derive_equipos,
    load_frozen_models,
    load_season_2026_27,
    load_vaastav_season,
    make_eb_points_model,
)
from experiments.recency_eb.evaluate import (
    evaluate_gw8_11_sealed_minutes,
    evaluate_walkforward_predictions,
)
from experiments.recency_eb.replay import replay_season_arm, summarize_julian_actual
from experiments.recency_eb.tune import run_tune
from mova_fpl.models.features.points_features import RecencyEBConfig

DEFAULT_OUT_DIR = EXP_ROOT
RESULTS_FILE = "results.json"
WINNER_FILE = "tune-winner.json"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _git_sha() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True, text=True, timeout=5, check=True,
        )
        return r.stdout.strip()
    except Exception:
        return "unknown"


def _cfg_from_winner(winner: dict[str, Any]) -> RecencyEBConfig:
    return RecencyEBConfig(
        h_attack=float(winner["h_attack"]),
        k_in_attack=float(winner["k_in_attack"]),
        h_role=float(winner["h_role"]),
        k_in_role=float(winner["k_in_role"]),
        n_cap=float(winner.get("n_cap", 15.0)),
        gamma_club=float(winner.get("gamma_club", 0.7)),
        skip_bonus_double_shrink=bool(winner.get("skip_bonus_double_shrink", True)),
    )


def _load_or_run_tune(out_dir: Path, force: bool = False) -> tuple[dict[str, Any], RecencyEBConfig]:
    winner_path = out_dir / WINNER_FILE
    if winner_path.exists() and not force:
        tune_res = _read_json(winner_path)
        return tune_res, _cfg_from_winner(tune_res["winner"])
    tune_res = run_tune(verbose=True)
    _write_json(winner_path, tune_res)
    return tune_res, _cfg_from_winner(tune_res["winner"])


def cmd_verify(cfg: RecencyEBConfig, *, time_limit: int, skip_replay: bool = False) -> dict[str, Any]:
    """Verify frozen winner on 2025-26 (no retune): walk-forward prediction + legal MILP replay."""
    minutes_model, points_prod = load_frozen_models()
    points_cand = make_eb_points_model(points_prod, cfg)

    df_24 = load_vaastav_season("2024-25")
    df_25 = load_vaastav_season("2025-26")
    equipos_25 = derive_equipos(df_25)

    pred_25 = evaluate_walkforward_predictions(
        season="2025-26",
        prev_df=df_24,
        curr_df=df_25,
        equipos=equipos_25,
        minutes_model=minutes_model,
        points_control=points_prod,
        points_candidate=points_cand,
        gws=list(range(1, 39)),
        verbose=True,
    )

    out: dict[str, Any] = {"prediction_2025_26": pred_25}
    if not skip_replay:
        minutes_cache: dict = {}
        rep_ctrl = replay_season_arm(
            arm_name="control_1_1_0",
            season="2025-26",
            prev_df=df_24,
            curr_df=df_25,
            schedule_source=df_25,
            equipos=equipos_25,
            minutes_model=minutes_model,
            points_model=points_prod,
            gws=list(range(1, 39)),
            max_calendar_gw=38,
            initial_squad=None,
            lock_gw1_squad=False,
            time_limit=time_limit,
            minutes_cache=minutes_cache,
            verbose=True,
        )
        rep_cand = replay_season_arm(
            arm_name="candidate_1_2_0_eb",
            season="2025-26",
            prev_df=df_24,
            curr_df=df_25,
            schedule_source=df_25,
            equipos=equipos_25,
            minutes_model=minutes_model,
            points_model=points_cand,
            gws=list(range(1, 39)),
            max_calendar_gw=38,
            initial_squad=None,
            lock_gw1_squad=False,
            time_limit=time_limit,
            minutes_cache=minutes_cache,
            verbose=True,
        )
        out["replay_2025_26"] = {
            "control_1_1_0": rep_ctrl,
            "candidate_1_2_0_eb": rep_cand,
            "pva_38_delta": int(rep_cand["totals"]["total_points"] - rep_ctrl["totals"]["total_points"]),
        }
    return out


def cmd_evaluate_2026_27(cfg: RecencyEBConfig, *, time_limit: int,
                         run_predictions: bool = True, run_replay: bool = True) -> dict[str, Any]:
    """Evaluate ONCE on 2026-27 GW2-11 (prediction) and GW1-11 (decisions from Julian GW1 squad)."""
    minutes_model, points_prod = load_frozen_models()
    points_cand = make_eb_points_model(points_prod, cfg)

    df_25 = load_vaastav_season("2025-26")
    s26 = load_season_2026_27()
    df_26 = s26["df"]
    equipos_26 = s26["equipos"]

    out: dict[str, Any] = {}
    if run_predictions:
        out["prediction_2026_27_gw2_11"] = evaluate_walkforward_predictions(
            season="2026-27",
            prev_df=df_25,
            curr_df=df_26,
            equipos=equipos_26,
            minutes_model=minutes_model,
            points_control=points_prod,
            points_candidate=points_cand,
            gws=list(range(2, 12)),
            catalog_asof=s26["catalog_asof_gw8_11"],
            verbose=True,
        )
        out["prediction_2026_27_gw8_11_sealed_minutes"] = evaluate_gw8_11_sealed_minutes(
            prev_df=df_25,
            curr_df=df_26,
            equipos=equipos_26,
            proj_approved=s26["proj_approved_gw8_11"],
            catalog_asof=s26["catalog_asof_gw8_11"],
            fixtures=s26["fixtures"],
            points_control=points_prod,
            points_candidate=points_cand,
        )

    if run_replay:
        minutes_cache: dict = {}
        rep_ctrl = replay_season_arm(
            arm_name="control_1_1_0",
            season="2026-27",
            prev_df=df_25,
            curr_df=df_26,
            schedule_source=s26["schedule_df"],
            equipos=equipos_26,
            minutes_model=minutes_model,
            points_model=points_prod,
            gws=list(range(1, 12)),
            max_calendar_gw=38,
            initial_squad=s26["julian_gw1_squad"],
            lock_gw1_squad=True,
            time_limit=time_limit,
            minutes_cache=minutes_cache,
            verbose=True,
        )
        rep_cand = replay_season_arm(
            arm_name="candidate_1_2_0_eb",
            season="2026-27",
            prev_df=df_25,
            curr_df=df_26,
            schedule_source=s26["schedule_df"],
            equipos=equipos_26,
            minutes_model=minutes_model,
            points_model=points_cand,
            gws=list(range(1, 12)),
            max_calendar_gw=38,
            initial_squad=s26["julian_gw1_squad"],
            lock_gw1_squad=True,
            time_limit=time_limit,
            minutes_cache=minutes_cache,
            verbose=True,
        )
        julian_ref = summarize_julian_actual(s26["julian_history"], max_gw=11)
        out["replay_2026_27_gw1_11"] = {
            "start_squad": "Julian real GW1 squad (entry 3609854, 15 players, GW1 vaastav prices = 100.0M, bank = 0.0)",
            "control_1_1_0": rep_ctrl,
            "candidate_1_2_0_eb": rep_cand,
            "julian_actual_reference": julian_ref,
            "delta_candidate_vs_control": int(
                rep_cand["totals"]["total_points"] - rep_ctrl["totals"]["total_points"]
            ),
            "delta_candidate_vs_julian": int(
                rep_cand["totals"]["total_points"] - julian_ref["totals"]["total_points"]
            ),
            "delta_control_vs_julian": int(
                rep_ctrl["totals"]["total_points"] - julian_ref["totals"]["total_points"]
            ),
        }
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="EXP-RECENCY-EB-2026-001 runner")
    parser.add_argument(
        "command",
        choices=("all", "tune", "verify", "evaluate", "replay"),
        help="Stage to run",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--time-limit", type=int, default=15, help="MILP solver time_limit (s) equal on both arms")
    parser.add_argument("--force-tune", action="store_true")
    args = parser.parse_args()

    t_start = time.perf_counter()
    out_dir: Path = args.out_dir
    results_path = out_dir / RESULTS_FILE
    results = _read_json(results_path)
    results.setdefault("experiment_id", "EXP-RECENCY-EB-2026-001")
    results["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    results["git_sha"] = _git_sha()
    results["data_source"] = {
        "canonical_db_found": canonical_db_available() is not None,
        "historical_source": "vaastav 2022-23..2025-26 merged_gw.csv + players_raw.csv (FPL persistent code identity)",
        "season_2026_27_source": "vaastav 2026-27 GW1-10 (100% verified vs live_2026_27_fx) + official live_2026_27_fx GW11 + catalog_gw11 as-of prices",
        "minutes_model": "frozen prod minutes-1.1.0.joblib (loaded with sklearn _loss unpickle shim; identical on both arms)",
        "points_control": "frozen prod points-1.1.0.joblib (player_recency_half_life=None)",
        "points_candidate": "points-1.2.0-eb (recency_mode='eb2' on top of frozen 1.1.0 global parameters)",
    }

    if args.command == "tune":
        tune_res, _ = _load_or_run_tune(out_dir, force=True)
        results["tune"] = tune_res
    elif args.command == "verify":
        tune_res, cfg = _load_or_run_tune(out_dir, force=args.force_tune)
        results["tune"] = tune_res
        results["verify_2025_26"] = cmd_verify(cfg, time_limit=args.time_limit, skip_replay=False)
    elif args.command == "evaluate":
        tune_res, cfg = _load_or_run_tune(out_dir, force=args.force_tune)
        results["tune"] = tune_res
        ev = cmd_evaluate_2026_27(cfg, time_limit=args.time_limit, run_predictions=True, run_replay=False)
        results.setdefault("evaluate_2026_27", {}).update(ev)
    elif args.command == "replay":
        tune_res, cfg = _load_or_run_tune(out_dir, force=args.force_tune)
        results["tune"] = tune_res
        ev = cmd_evaluate_2026_27(cfg, time_limit=args.time_limit, run_predictions=False, run_replay=True)
        results.setdefault("evaluate_2026_27", {}).update(ev)
    elif args.command == "all":
        tune_res, cfg = _load_or_run_tune(out_dir, force=args.force_tune)
        results["tune"] = tune_res
        _write_json(results_path, results)
        results["verify_2025_26"] = cmd_verify(cfg, time_limit=args.time_limit, skip_replay=False)
        _write_json(results_path, results)
        results["evaluate_2026_27"] = cmd_evaluate_2026_27(
            cfg, time_limit=args.time_limit, run_predictions=True, run_replay=True,
        )

    results["last_command"] = args.command
    results["last_run_runtime_seconds"] = round(time.perf_counter() - t_start, 2)
    _write_json(results_path, results)
    print(f"[done] wrote {results_path} in {results['last_run_runtime_seconds']}s", flush=True)


if __name__ == "__main__":
    main()
