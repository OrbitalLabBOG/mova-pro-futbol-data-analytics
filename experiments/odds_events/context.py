"""Causal match-context features for the odds/events ablation.

This module is intentionally isolated under ``experiments/``.  It does not
change the production model or its data contract.  Every feature for gameweek
``gw`` is built from information available before that gameweek:

* football-data.co.uk pre-closing market averages (never closing columns), and
* WhoScored events from strictly earlier gameweeks.

The output is a pair of expected-goal intensities per fixture.  The existing
decomposed FPL model remains responsible for minutes and player-level rates.
"""
from __future__ import annotations

import csv
import math
import sqlite3
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import least_squares
from scipy.stats import poisson
from sklearn.metrics import mean_poisson_deviance

from mova_fpl.data.store import Store
from mova_fpl.models.features.points_features import lambda_conceded, team_strength


TEAM_ALIASES = {
    "Man Utd": "Man United",
    "Spurs": "Tottenham",
    "Sheffield Utd": "Sheffield United",
    "Nottingham Forest": "Nott'm Forest",
}

EVENT_FEATURE_SETS = {
    "shots": ("shots",),
    "shot_quality": ("shots", "box_shots", "big_chances"),
    "spatial": ("shots", "box_shots", "big_chances", "box_touches"),
}

EVENT_DEFAULTS = {
    "shots": 12.5,
    "box_shots": 7.5,
    "big_chances": 1.8,
    "box_touches": 24.0,
}


def canonical_team(value: str) -> str:
    value = str(value).strip()
    return TEAM_ALIASES.get(value, value)


def season_odds_code(season: str) -> str:
    """``2020-21`` -> football-data mirror code ``2021``."""
    return season.replace("-", "")[2:]


def load_fpl_matches(db_path: Path | str, seasons: tuple[str, ...]) -> pd.DataFrame:
    """One row per fixture from the canonical player-gameweek store."""
    placeholders = ",".join("?" * len(seasons))
    sql = f"""
        SELECT season, gw, fixture, MIN(kickoff_time) AS kickoff_time,
               MAX(CASE WHEN was_home = 1 THEN team END) AS home_team,
               MAX(CASE WHEN was_home = 0 THEN team END) AS away_team,
               MAX(team_h_score) AS home_goals,
               MAX(team_a_score) AS away_goals
          FROM player_gameweek
         WHERE season IN ({placeholders})
         GROUP BY season, gw, fixture
        HAVING home_team IS NOT NULL AND away_team IS NOT NULL
         ORDER BY season, gw, fixture
    """
    with sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True) as con:
        out = pd.read_sql_query(sql, con, params=seasons)
    out["match_date"] = pd.to_datetime(out["kickoff_time"], utc=True).dt.strftime("%Y-%m-%d")
    out["home_team"] = out["home_team"].map(canonical_team)
    out["away_team"] = out["away_team"].map(canonical_team)
    out["home_goals"] = pd.to_numeric(out["home_goals"], errors="coerce")
    out["away_goals"] = pd.to_numeric(out["away_goals"], errors="coerce")
    return out


def _number(row: dict, *names: str) -> float | None:
    for name in names:
        try:
            value = float(row.get(name, ""))
        except (TypeError, ValueError):
            continue
        if np.isfinite(value) and value > 1.0:
            return value
    return None


def devig(*odds: float) -> np.ndarray:
    inverse = 1.0 / np.asarray(odds, dtype=float)
    return inverse / inverse.sum()


def score_probabilities(lambda_home: float, lambda_away: float, max_goals: int = 12) -> np.ndarray:
    """Independent-Poisson probabilities ``[home, draw, away, over_2_5]``."""
    goals = np.arange(max_goals + 1)
    ph = poisson.pmf(goals, lambda_home)
    pa = poisson.pmf(goals, lambda_away)
    matrix = np.outer(ph, pa)
    p_home = float(np.tril(matrix, -1).sum())
    p_draw = float(np.trace(matrix))
    p_away = float(np.triu(matrix, 1).sum())
    # This expression is exact for independent Poisson totals.
    p_over = float(1.0 - poisson.cdf(2, lambda_home + lambda_away))
    norm = p_home + p_draw + p_away
    return np.array([p_home / norm, p_draw / norm, p_away / norm, p_over])


def infer_market_lambdas(p_1x2: np.ndarray, p_over_25: float) -> tuple[float, float, float]:
    """Recover home/away scoring intensities from 1X2 and O/U 2.5.

    We mirror the current market-calibration literature: choose the two Poisson
    intensities that reproduce the devigged market probabilities by bounded
    least squares.  The returned error is useful as a data-quality gate.
    """
    p_1x2 = np.asarray(p_1x2, dtype=float)
    total_guess = 2.7
    tilt = float(np.clip(p_1x2[0] - p_1x2[2], -0.8, 0.8))
    x0 = np.array([
        np.clip(total_guess * (0.5 + 0.32 * tilt), 0.2, 4.5),
        np.clip(total_guess * (0.5 - 0.32 * tilt), 0.2, 4.5),
    ])

    def residual(x):
        predicted = score_probabilities(float(x[0]), float(x[1]))
        # Away is retained: although 1X2 sums to one, the truncation/renormalising
        # makes the redundant residual a useful numerical stabiliser.
        return np.r_[predicted[:3] - p_1x2, predicted[3] - p_over_25]

    fit = least_squares(residual, x0=x0, bounds=(0.05, 5.5), xtol=1e-10, ftol=1e-10)
    error = float(np.sqrt(np.mean(residual(fit.x) ** 2)))
    return float(fit.x[0]), float(fit.x[1]), error


def load_opening_market(odds_dir: Path | str, seasons: tuple[str, ...]) -> pd.DataFrame:
    """Load pre-closing consensus and infer goal intensities.

    ``Avg*`` is preferred because it is the cross-book consensus.  Bet365 and
    Pinnacle are fallbacks only.  No column whose name contains ``C`` (closing)
    is used.
    """
    rows: list[dict] = []
    odds_dir = Path(odds_dir)
    for season in seasons:
        path = odds_dir / f"season-{season_odds_code(season)}.csv"
        with path.open(encoding="utf-8-sig", errors="replace") as handle:
            for raw in csv.DictReader(handle):
                home = _number(raw, "AvgH", "B365H", "PSH")
                draw = _number(raw, "AvgD", "B365D", "PSD")
                away = _number(raw, "AvgA", "B365A", "PSA")
                over = _number(raw, "Avg>2.5", "B365>2.5", "P>2.5")
                under = _number(raw, "Avg<2.5", "B365<2.5", "P<2.5")
                date = pd.to_datetime(raw.get("Date"), dayfirst=True, errors="coerce")
                if None in (home, draw, away, over, under) or pd.isna(date):
                    continue
                p_1x2 = devig(home, draw, away)
                p_total = devig(over, under)
                lam_h, lam_a, fit_error = infer_market_lambdas(p_1x2, float(p_total[0]))
                rows.append({
                    "season": season,
                    "match_date": date.strftime("%Y-%m-%d"),
                    "home_team": canonical_team(raw.get("HomeTeam", "")),
                    "away_team": canonical_team(raw.get("AwayTeam", "")),
                    "p_home_market": p_1x2[0],
                    "p_draw_market": p_1x2[1],
                    "p_away_market": p_1x2[2],
                    "p_over25_market": p_total[0],
                    "lambda_home_market": lam_h,
                    "lambda_away_market": lam_a,
                    "market_fit_rmse": fit_error,
                })
    return pd.DataFrame(rows)


def attach_market(matches: pd.DataFrame, market: pd.DataFrame) -> pd.DataFrame:
    keys = ["season", "match_date", "home_team", "away_team"]
    out = matches.merge(market, on=keys, how="left", validate="one_to_one")
    return out


def add_baseline_lambdas(matches: pd.DataFrame, store: Store) -> pd.DataFrame:
    """Reproduce the production goal-context model walk-forward."""
    frames = []
    for (season, gw), target in matches.groupby(["season", "gw"], sort=True):
        strength = team_strength(store.as_of(str(season), int(gw)))
        part = target.copy()
        part["lambda_home_baseline"] = [
            lambda_conceded(strength, away, home, local=False)
            for home, away in zip(part["home_team"], part["away_team"])
        ]
        part["lambda_away_baseline"] = [
            lambda_conceded(strength, home, away, local=True)
            for home, away in zip(part["home_team"], part["away_team"])
        ]
        frames.append(part)
    return pd.concat(frames, ignore_index=True)


def blend_lambdas(frame: pd.DataFrame, market_weight: float, prefix: str = "blend") -> pd.DataFrame:
    """Convex blend used by Egidi et al.; weight is selected before holdout."""
    out = frame.copy()
    for side in ("home", "away"):
        baseline = out[f"lambda_{side}_baseline"].to_numpy(float)
        market = out[f"lambda_{side}_market"].to_numpy(float)
        out[f"lambda_{side}_{prefix}"] = (1.0 - market_weight) * baseline + market_weight * market
    return out


def goal_deviance(frame: pd.DataFrame, prefix: str) -> float:
    actual = np.r_[frame["home_goals"].to_numpy(float), frame["away_goals"].to_numpy(float)]
    pred = np.r_[frame[f"lambda_home_{prefix}"].to_numpy(float),
                 frame[f"lambda_away_{prefix}"].to_numpy(float)]
    return float(mean_poisson_deviance(actual, np.clip(pred, 0.02, None)))


def select_market_weight(frame: pd.DataFrame, seasons: tuple[str, ...]) -> tuple[float, pd.DataFrame]:
    train = frame[frame["season"].isin(seasons)].dropna(
        subset=["lambda_home_market", "lambda_away_market"])
    rows = []
    for weight in np.linspace(0.0, 1.0, 21):
        candidate = blend_lambdas(train, float(weight), "candidate")
        rows.append({"weight": float(weight), "poisson_deviance": goal_deviance(candidate, "candidate")})
    scores = pd.DataFrame(rows)
    best = float(scores.loc[scores["poisson_deviance"].idxmin(), "weight"])
    return best, scores


def _event_query() -> str:
    return """
        SELECT m.match_id, m.start_utc, m.home_team, m.away_team, e.team_name,
               SUM(CASE WHEN e.is_shot = 1 THEN 1 ELSE 0 END) AS shots,
               SUM(CASE WHEN e.is_shot = 1 AND e.x >= 83 THEN 1 ELSE 0 END) AS box_shots,
               SUM(CASE WHEN e.is_shot = 1 AND e.qualifiers LIKE '%BigChance%' THEN 1 ELSE 0 END)
                   AS big_chances,
               SUM(CASE WHEN e.is_touch = 1 AND e.x >= 83 AND e.y BETWEEN 18 AND 82
                        THEN 1 ELSE 0 END) AS box_touches
          FROM events e
          JOIN matches m ON m.match_id = e.match_id
         WHERE m.competition LIKE 'Premier League%'
         GROUP BY m.match_id, m.start_utc, m.home_team, m.away_team, e.team_name
    """


def load_event_matches(events_db: Path | str, fpl_matches: pd.DataFrame) -> pd.DataFrame:
    """Aggregate WhoScored events and map them to canonical FPL fixtures."""
    with sqlite3.connect(f"file:{Path(events_db)}?mode=ro", uri=True) as con:
        team_rows = pd.read_sql_query(_event_query(), con)
    team_rows["match_date"] = pd.to_datetime(
        team_rows["start_utc"], format="%d/%m/%Y", errors="coerce").dt.strftime("%Y-%m-%d")
    for col in ("home_team", "away_team", "team_name"):
        team_rows[col] = team_rows[col].map(canonical_team)

    metrics = tuple(EVENT_DEFAULTS)
    home = team_rows[team_rows["team_name"] == team_rows["home_team"]].copy()
    away = team_rows[team_rows["team_name"] == team_rows["away_team"]].copy()
    home = home[["match_id", "match_date", "home_team", "away_team", *metrics]].rename(
        columns={m: f"home_{m}" for m in metrics})
    away = away[["match_id", *metrics]].rename(columns={m: f"away_{m}" for m in metrics})
    events = home.merge(away, on="match_id", how="inner", validate="one_to_one")

    keys = ["match_date", "home_team", "away_team"]
    fixtures = fpl_matches[fpl_matches["season"] == "2025-26"][
        ["season", "gw", "fixture", *keys]].drop_duplicates("fixture")
    return fixtures.merge(events, on=keys, how="inner", validate="one_to_one")


def _ewm_update(old: float | None, value: float, alpha: float) -> float:
    return float(value) if old is None else float((1.0 - alpha) * old + alpha * value)


def build_event_factors(matches: pd.DataFrame, events: pd.DataFrame,
                        half_life: float = 5.0, shrink_matches: float = 5.0) -> pd.DataFrame:
    """Create pre-GW event-strength factors for every 2025/26 fixture.

    All fixtures in a gameweek are scored before any event from that gameweek is
    added to state.  This is stricter than ordering by kickoff and matches the
    single FPL deadline information barrier.
    """
    season = matches[matches["season"] == "2025-26"].sort_values(["gw", "fixture"])
    event_by_fixture = events.set_index("fixture").to_dict("index")
    alpha = 1.0 - math.exp(math.log(0.5) / half_life)
    team_state: dict[str, dict] = defaultdict(lambda: {"n": 0, "for": {}, "against": {}})
    league_sum = defaultdict(float)
    league_n = 0
    rows = []

    def prior(metric: str) -> float:
        return (league_sum[metric] / league_n) if league_n else EVENT_DEFAULTS[metric]

    def index(team: str, opponent: str, feature_set: tuple[str, ...]) -> float:
        attack, weak = [], []
        own, opp = team_state[team], team_state[opponent]
        for metric in feature_set:
            base = max(prior(metric), 1e-6)
            own_weight = own["n"] / (own["n"] + shrink_matches)
            opp_weight = opp["n"] / (opp["n"] + shrink_matches)
            own_obs = own["for"].get(metric, base)
            opp_obs = opp["against"].get(metric, base)
            attack.append(max((own_weight * own_obs + (1 - own_weight) * base) / base, 0.2))
            weak.append(max((opp_weight * opp_obs + (1 - opp_weight) * base) / base, 0.2))
        return float(np.clip(math.sqrt(np.exp(np.mean(np.log(attack)))
                                           * np.exp(np.mean(np.log(weak)))), 0.60, 1.60))

    for gw, fixtures in season.groupby("gw", sort=True):
        # Snapshot all predictions at the shared GW deadline.
        for _, match in fixtures.iterrows():
            row = {"season": "2025-26", "gw": int(gw), "fixture": int(match["fixture"])}
            for name, feature_set in EVENT_FEATURE_SETS.items():
                row[f"factor_home_{name}"] = index(match["home_team"], match["away_team"], feature_set)
                row[f"factor_away_{name}"] = index(match["away_team"], match["home_team"], feature_set)
            row["event_target_available"] = int(match["fixture"] in event_by_fixture)
            rows.append(row)

        # Only after the GW is fully predicted may its events update state.
        for _, match in fixtures.iterrows():
            observed = event_by_fixture.get(int(match["fixture"]))
            if observed is None:
                continue
            home, away = match["home_team"], match["away_team"]
            for team, side, other in ((home, "home", "away"), (away, "away", "home")):
                state = team_state[team]
                for metric in EVENT_DEFAULTS:
                    value_for = float(observed[f"{side}_{metric}"])
                    value_against = float(observed[f"{other}_{metric}"])
                    state["for"][metric] = _ewm_update(state["for"].get(metric), value_for, alpha)
                    state["against"][metric] = _ewm_update(
                        state["against"].get(metric), value_against, alpha)
                    league_sum[metric] += value_for
                state["n"] += 1
            league_n += 2
    return pd.DataFrame(rows)


def apply_event_factor(frame: pd.DataFrame, base_prefix: str, feature_set: str,
                       exponent: float, output_prefix: str) -> pd.DataFrame:
    out = frame.copy()
    for side in ("home", "away"):
        factor = out[f"factor_{side}_{feature_set}"].fillna(1.0).to_numpy(float)
        base = out[f"lambda_{side}_{base_prefix}"].to_numpy(float)
        out[f"lambda_{side}_{output_prefix}"] = np.clip(base * factor ** exponent, 0.05, 5.5)
    return out


def select_event_spec(frame: pd.DataFrame, base_prefix: str,
                      validation_gws=range(10, 20)) -> tuple[str, float, pd.DataFrame]:
    validation = frame[(frame["season"] == "2025-26")
                       & frame["gw"].isin(validation_gws)].copy()
    rows = []
    for name in EVENT_FEATURE_SETS:
        for exponent in np.linspace(0.0, 1.5, 16):
            candidate = apply_event_factor(validation, base_prefix, name, float(exponent), "candidate")
            rows.append({"feature_set": name, "exponent": float(exponent),
                         "poisson_deviance": goal_deviance(candidate, "candidate")})
    scores = pd.DataFrame(rows)
    best = scores.loc[scores["poisson_deviance"].idxmin()]
    return str(best["feature_set"]), float(best["exponent"]), scores


def match_metrics(frame: pd.DataFrame, prefix: str) -> dict:
    """Goal, clean-sheet and 1X2 metrics with one independent row per match."""
    lh = np.clip(frame[f"lambda_home_{prefix}"].to_numpy(float), 0.02, None)
    la = np.clip(frame[f"lambda_away_{prefix}"].to_numpy(float), 0.02, None)
    hg = frame["home_goals"].to_numpy(float)
    ag = frame["away_goals"].to_numpy(float)
    actual_goals = np.r_[hg, ag]
    predicted_goals = np.r_[lh, la]

    # A home clean sheet means away goals == 0 and vice versa.
    actual_cs = np.r_[(ag == 0).astype(float), (hg == 0).astype(float)]
    predicted_cs = np.r_[np.exp(-la), np.exp(-lh)]
    brier_cs = float(np.mean((predicted_cs - actual_cs) ** 2))
    logloss_cs = float(-np.mean(actual_cs * np.log(np.clip(predicted_cs, 1e-9, 1.0))
                                + (1 - actual_cs) * np.log(np.clip(1 - predicted_cs, 1e-9, 1.0))))

    rps = []
    for home_lambda, away_lambda, home_goals, away_goals in zip(lh, la, hg, ag):
        p = score_probabilities(home_lambda, away_lambda)[:3]
        y = np.array([home_goals > away_goals, home_goals == away_goals,
                      home_goals < away_goals], dtype=float)
        rps.append(float(np.sum((np.cumsum(p)[:-1] - np.cumsum(y)[:-1]) ** 2) / 2.0))
    return {
        "matches": int(len(frame)),
        "poisson_deviance": float(mean_poisson_deviance(actual_goals, predicted_goals)),
        "goals_mae": float(np.mean(np.abs(predicted_goals - actual_goals))),
        "cs_brier": brier_cs,
        "cs_logloss": logloss_cs,
        "rps_1x2": float(np.mean(rps)),
    }


def loss_by_match(frame: pd.DataFrame, prefix: str, metric: str) -> np.ndarray:
    lh = np.clip(frame[f"lambda_home_{prefix}"].to_numpy(float), 0.02, None)
    la = np.clip(frame[f"lambda_away_{prefix}"].to_numpy(float), 0.02, None)
    hg = frame["home_goals"].to_numpy(float)
    ag = frame["away_goals"].to_numpy(float)
    if metric == "cs_brier":
        return ((np.exp(-la) - (ag == 0)) ** 2 + (np.exp(-lh) - (hg == 0)) ** 2) / 2.0
    if metric == "poisson_deviance":
        # Unit Poisson deviance, averaged over the two team observations.
        def unit(y, mu):
            log_term = np.zeros_like(y, dtype=float)
            positive = y > 0
            log_term[positive] = y[positive] * np.log(y[positive] / mu[positive])
            return 2.0 * (log_term - (y - mu))
        return (unit(hg, lh) + unit(ag, la)) / 2.0
    raise ValueError(metric)


def paired_bootstrap_delta(frame: pd.DataFrame, candidate: str, baseline: str,
                           metric: str, draws: int = 2000, seed: int = 42) -> dict:
    """Candidate minus baseline; negative means improvement."""
    delta = loss_by_match(frame, candidate, metric) - loss_by_match(frame, baseline, metric)
    rng = np.random.default_rng(seed)
    samples = rng.choice(delta, size=(draws, len(delta)), replace=True).mean(axis=1)
    return {"mean": float(delta.mean()), "lo": float(np.quantile(samples, 0.025)),
            "hi": float(np.quantile(samples, 0.975))}
