"""Pruebas unitarias y de regresión para recencia Empirical Bayes en 2 etapas (points-1.2.0-eb)."""
from __future__ import annotations

import copy

import numpy as np
import pandas as pd
import pytest

from mova_fpl.models.bonus import BonusModel
from mova_fpl.models.features.points_features import (
    RecencyEBConfig,
    apply_eb_rates,
    prepare_eb_state,
    stratified_population_priors,
)
from mova_fpl.models.points import COMPONENTES, PointsModel
from mova_fpl.rules import get as get_rules

SCORING = get_rules("2026-27").SCORING
UMBRALES = SCORING.defcon_thresholds


def _row(
    *,
    season: str,
    gw: int,
    element: int,
    player_key: str,
    position: str,
    team: str,
    value: int,
    minutes: int,
    goals: int = 0,
    assists: int = 0,
    xg: float = 0.0,
    xa: float = 0.0,
    bps: int = 15,
    bonus: int = 0,
    defcon: float = 6.0,
    fixture: int | None = None,
) -> dict:
    return {
        "season": season,
        "gw": gw,
        "element": element,
        "fixture": fixture if fixture is not None else gw * 100 + element,
        "player_key": player_key,
        "name": player_key,
        "position": position,
        "team": team,
        "value": value,
        "opponent_team": 1,
        "was_home": 1,
        "kickoff_time": "2026-08-15T15:00:00Z",
        "minutes": minutes,
        "total_points": 2 + goals * 5 + assists * 3 + bonus,
        "goals_scored": goals,
        "assists": assists,
        "expected_goals": xg,
        "expected_assists": xa,
        "clean_sheets": 0,
        "goals_conceded": 1,
        "own_goals": 0,
        "penalties_saved": 0,
        "penalties_missed": 0,
        "yellow_cards": 0,
        "red_cards": 0,
        "saves": 3 if position == "GKP" else 0,
        "bonus": bonus,
        "bps": bps,
        "starts": 1 if minutes >= 60 else 0,
        "defensive_contribution": defcon,
        "clearances_blocks_interceptions": defcon * 0.6,
        "recoveries": defcon * 0.4,
        "tackles": 2.0,
        "team_h_score": 2,
        "team_a_score": 1,
    }


def _two_season_fixture() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Histórico sintético de 2025-26 + 2026-27 GW1..5 con precios estratificados."""
    rows = []
    # 8 MIDs en 2025-26 con precios iniciales claramente separados (45..120)
    # para que cuartil superior tenga tasa mucho mayor que la mediana global.
    specs = [
        ("mid_low_1", 45, "ClubA", 0.05, 10.0),
        ("mid_low_2", 45, "ClubA", 0.05, 10.0),
        ("mid_low_3", 50, "ClubB", 0.08, 9.5),
        ("mid_low_4", 50, "ClubB", 0.08, 9.5),
        ("mid_mid_1", 60, "ClubC", 0.15, 8.0),
        ("mid_mid_2", 65, "ClubC", 0.18, 7.5),
        ("mid_prem_1", 110, "ClubD", 0.60, 5.0),
        ("mid_prem_2", 120, "ClubD", 0.80, 4.0),
    ]
    for gw in range(1, 21):
        for idx, (pk, val, club, xg_per_90, dc_per_90) in enumerate(specs, start=1):
            rows.append(_row(
                season="2025-26", gw=gw, element=idx, player_key=pk,
                position="MID", team=club, value=val, minutes=90,
                goals=1 if (xg_per_90 >= 0.5 and gw % 2 == 0) else 0,
                xg=xg_per_90, xa=xg_per_90 * 0.5,
                bps=28 if xg_per_90 >= 0.5 else 14,
                bonus=2 if xg_per_90 >= 0.5 else 0,
                defcon=dc_per_90,
            ))
    # 2026-27 GW1..3
    for gw in range(1, 4):
        for idx, (pk, val, club, xg_per_90, dc_per_90) in enumerate(specs, start=1):
            # mid_prem_1 cambia de club a ClubX en 2026-27; su precio sube a 125 en GW2
            new_club = "ClubX" if pk == "mid_prem_1" else club
            curr_val = val + (15 if (pk == "mid_prem_1" and gw >= 2) else 0)
            rows.append(_row(
                season="2026-27", gw=gw, element=idx, player_key=pk,
                position="MID", team=new_club, value=curr_val, minutes=90,
                goals=0, xg=0.20 if pk == "mid_prem_1" else xg_per_90,
                xa=0.10, bps=18, bonus=1 if pk == "mid_prem_2" else 0,
                defcon=dc_per_90,
            ))
    hist = pd.DataFrame(rows)
    roster = pd.DataFrame([
        {
            "season": "2026-27", "gw": 4, "element": idx, "player_key": pk,
            "name": pk, "position": "MID",
            "team": "ClubX" if pk == "mid_prem_1" else club,
            "value": val + (20 if pk == "mid_prem_1" else 0),
            "opponent_team": 1, "was_home": 1, "fixture": 900 + idx,
        }
        for idx, (pk, val, club, _, _) in enumerate(specs, start=1)
    ] + [
        {
            "season": "2026-27", "gw": 4, "element": 99, "player_key": "mid_new_prem",
            "name": "New Prem", "position": "MID", "team": "ClubD", "value": 115,
            "opponent_team": 1, "was_home": 1, "fixture": 999,
        }
    ])
    return hist, roster


def test_defaults_reproduce_1_1_0_exact_including_unpickled_instance():
    """Con defaults (EB apagado), PointsModel reproduce 1.1.0 exactamente."""
    hist, roster = _two_season_fixture()
    pm_default = PointsModel().fit(hist)
    assert pm_default.player_recency_half_life is None
    assert pm_default.recency_mode is None
    assert pm_default.recency_eb is None
    assert pm_default.active_eb_config() is None

    # Simular un PointsModel unpickled de 1.1.0 sin los atributos nuevos en __dict__
    pm_legacy = copy.deepcopy(pm_default)
    del pm_legacy.__dict__["recency_mode"]
    del pm_legacy.__dict__["recency_eb"]
    assert pm_legacy.active_eb_config() is None

    proba = np.tile(np.array([0.1, 0.1, 0.8]), (len(roster), 1))
    out_default = pm_default.project(hist, roster, proba, SCORING, UMBRALES)
    out_legacy = pm_legacy.project(hist, roster, proba, SCORING, UMBRALES)
    pd.testing.assert_frame_equal(out_default, out_legacy, rtol=0.0, atol=0.0)


def test_stratified_population_prior_uses_exposure_weighted_mean_not_median():
    """El prior poblacional es media ponderada por exposición de (pos x cuartil precio inicial)."""
    hist, _ = _two_season_fixture()
    prev = hist[hist["season"] == "2025-26"]
    pop = stratified_population_priors(prev, price_quartiles=4)

    # En el cuartil más alto están mid_prem_1 (xg90=0.60) y mid_prem_2 (xg90=0.80),
    # ambos con igual exposición -> media ponderada = 0.70 (vs mediana global MID ~ 0.115).
    q_max = max(q for (p, q) in pop["by_stratum"] if p == "MID")
    assert pop["by_stratum"][("MID", q_max)]["xg90"] == pytest.approx(0.70, abs=1e-9)
    # El cuartil más bajo (45) tiene xg90 = 0.05
    assert pop["by_stratum"][("MID", 0)]["xg90"] == pytest.approx(0.05, abs=1e-9)

    # Verificar ponderación por exposición dentro del mismo estrato (no media simple)
    unbalanced = pd.DataFrame([
        _row(season="2025-26", gw=1, element=1, player_key="a", position="FWD",
             team="T1", value=80, minutes=90, xg=1.0),
        _row(season="2025-26", gw=2, element=1, player_key="a", position="FWD",
             team="T1", value=80, minutes=90, xg=1.0),
        _row(season="2025-26", gw=3, element=1, player_key="a", position="FWD",
             team="T1", value=80, minutes=90, xg=1.0),
        _row(season="2025-26", gw=1, element=2, player_key="b", position="FWD",
             team="T1", value=80, minutes=90, xg=0.0),
    ])
    pop_u = stratified_population_priors(unbalanced, price_quartiles=1)
    # Suma xg = 3.0, suma n90 = 4.0 -> 0.75 (media simple por jugador habría dado 0.50)
    assert pop_u["by_pos"]["FWD"]["xg90"] == pytest.approx(0.75, abs=1e-9)


def test_eb_stage1_n_cap_club_discount_and_newcomer_prior():
    """Verifica tope N_cap, descuento gamma_club=0.7 y prior de novato = media de estrato."""
    hist, roster = _two_season_fixture()
    # GW1 (sin filas de 2026-27): Stage 2 debe colapsar exactamente a mu_0 de Stage 1
    prev_only = hist[hist["season"] == "2025-26"].copy()
    roster_gw1 = roster.copy()
    roster_gw1["gw"] = 1

    cfg = RecencyEBConfig(h_attack=8.0, k_in_attack=6.0, h_role=5.0, k_in_role=4.0,
                          n_cap=15.0, gamma_club=0.7)
    eb_state = prepare_eb_state(prev_only, cfg, target_season="2026-27", target_gw=1)
    pos = pd.Series(["MID"] * len(roster_gw1), index=roster_gw1.index)
    rates = apply_eb_rates(roster_gw1, pos, eb_state, cfg).set_index(roster_gw1["player_key"])

    # Novato de precio 115 cae en el cuartil premium (mu_pop xg90 = 0.70), no mediana global
    assert rates.loc["mid_new_prem", "xg90"] == pytest.approx(0.70, abs=1e-9)

    # mid_prem_2: mismo club (ClubD), n90_prev=20 -> cap a 15, gamma=1.0 -> n_eff = 15
    # r_prev=0.80, mu_pop=0.70, k_pop=8 -> mu0 = (15*0.80 + 8*0.70)/(15+8)
    expected_prem2 = (15.0 * 0.80 + 8.0 * 0.70) / (15.0 + 8.0)
    assert rates.loc["mid_prem_2", "xg90"] == pytest.approx(expected_prem2, abs=1e-9)

    # mid_prem_1: cambió de club (ClubD -> ClubX), n90_prev=20 -> cap a 15, gamma=0.7 -> n_eff = 10.5
    # r_prev=0.60, mu_pop=0.70, k_pop=8 -> mu0 = (10.5*0.60 + 8*0.70)/(10.5+8)
    expected_prem1 = (10.5 * 0.60 + 8.0 * 0.70) / (10.5 + 8.0)
    assert rates.loc["mid_prem_1", "xg90"] == pytest.approx(expected_prem1, abs=1e-9)


def test_eb_stage2_units_gw_age_decay_and_newcomer_higher_k_in():
    """Verifica unidades brutas de x_t, decaimiento por edad en GWs (no apariciones) y K_in novatos."""
    # Temporada previa con un jugador estable y uno ausente (novato)
    prev = pd.DataFrame([
        _row(season="2025-26", gw=gw, element=1, player_key="ret", position="FWD",
             team="T1", value=80, minutes=90, goals=0, xg=0.50, bps=20, bonus=1, defcon=4.0)
        for gw in range(1, 16)
    ])
    # En 2026-27 (target_gw=6, gw_ref=5):
    # - 'ret' jugó SOLO en GW1 (90 min, xg=0.0, bps=30, bonus=3) y se lesionó GW2..5 -> age=4!
    # - 'cameo' (novato, n_eff=0) jugó 9 minutos en GW5 (e=0.1 n90) con xg=0.50 (raw x_t=0.50, NO tasa 5.0!)
    curr = pd.DataFrame([
        _row(season="2026-27", gw=1, element=1, player_key="ret", position="FWD",
             team="T1", value=80, minutes=90, goals=0, xg=0.0, bps=30, bonus=3, defcon=8.0),
        _row(season="2026-27", gw=5, element=2, player_key="cameo", position="FWD",
             team="T1", value=80, minutes=9, goals=1, xg=0.50, bps=10, bonus=0, defcon=1.0),
    ])
    hist = pd.concat([prev, curr], ignore_index=True)
    roster = pd.DataFrame([
        {"season": "2026-27", "gw": 6, "element": 1, "player_key": "ret",
         "name": "Ret", "position": "FWD", "team": "T1", "value": 80,
         "opponent_team": 2, "was_home": 1, "fixture": 601},
        {"season": "2026-27", "gw": 6, "element": 2, "player_key": "cameo",
         "name": "Cameo", "position": "FWD", "team": "T1", "value": 80,
         "opponent_team": 2, "was_home": 1, "fixture": 602},
    ])

    cfg = RecencyEBConfig(h_attack=8.0, k_in_attack=6.0, h_role=4.0, k_in_role=3.0,
                          k_in_newcomer_attack=9.0, k_in_newcomer_role=6.0,
                          n_cap=15.0, gamma_club=0.7)
    eb_state = prepare_eb_state(hist, cfg, target_season="2026-27", target_gw=6)
    pos = pd.Series(["FWD", "FWD"], index=roster.index)
    rates = apply_eb_rates(roster, pos, eb_state, cfg).set_index(roster["player_key"])

    # Para 'ret': mu_0 = 0.50 (xg90), 20.0 (bps90), 1.0 (bonus_aparicion).
    # En GW1 con target_gw=6 -> age = 5 - 1 = 4.
    w_atk = 2.0 ** (-4.0 / 8.0)
    w_role = 2.0 ** (-4.0 / 4.0)
    assert rates.loc["ret", "xg90"] == pytest.approx((w_atk * 0.0 + 6.0 * 0.50) / (w_atk * 1.0 + 6.0), abs=1e-9)
    assert rates.loc["ret", "bps90"] == pytest.approx((w_role * 30.0 + 3.0 * 20.0) / (w_role * 1.0 + 3.0), abs=1e-9)
    # bonus_aparicion usa denominador sum(w_t) = w_role
    assert rates.loc["ret", "bonus_aparicion"] == pytest.approx(
        (w_role * 3.0 + 3.0 * 1.0) / (w_role * 1.0 + 3.0), abs=1e-9
    )

    # Para 'cameo' (novato, n_eff=0): mu_0 = mu_pop = 0.50, k_in_newcomer_attack = 9.0,
    # age = 5 - 5 = 0 -> w = 1.0, x_t = 0.50 (bruto), e_t = 9/90 = 0.1.
    expected_cameo_xg90 = (1.0 * 0.50 + 9.0 * 0.50) / (1.0 * 0.1 + 9.0)
    assert rates.loc["cameo", "xg90"] == pytest.approx(expected_cameo_xg90, abs=1e-9)
    # Si hubiera usado tasa (5.0) en vez de conteo bruto (0.50), habría dado ~1.04!
    assert rates.loc["cameo", "xg90"] < 0.60


def test_bonus_model_removes_double_shrink_when_already_shrunk():
    """BonusModel.project no debe volver a encoger cuando already_shrunk=True."""
    bm = BonusModel(cortes=[10.0, 20.0, 30.0], valores=[0.1, 0.5], prior_global=0.25, k=6.0)
    bps90 = np.array([12.0])        # desde_bps ≈ 0.1
    bonus_post = np.array([0.80])   # posterior EB alto
    n90_small = np.array([2.0])     # n90 pequeño decaído
    noventas = np.array([1.0])

    legacy = bm.project(bps90, bonus_post, n90_small, noventas, already_shrunk=False)
    eb = bm.project(bps90, bonus_post, n90_small, noventas, already_shrunk=True)

    # Legacy encoge 0.80 fuertemente hacia ~0.10 porque n90=2 vs k=6
    assert legacy["bonus_por_90"][0] < 0.40
    # EB respeta el posterior sin doble shrink
    assert eb["bonus_por_90"][0] == pytest.approx(0.80, abs=1e-9)
    assert eb["puntos_bonus"][0] == pytest.approx(0.80, abs=1e-9)


def test_points_model_eb2_end_to_end_components_sum_and_gw1():
    """PointsModel con recency_mode='eb2' suma exactamente sus componentes y maneja GW1."""
    hist, roster = _two_season_fixture()
    pm = PointsModel(recency_mode="eb2", recency_eb=RecencyEBConfig()).fit(hist)
    proba = np.tile(np.array([0.1, 0.1, 0.8]), (len(roster), 1))

    out = pm.project(hist, roster, proba, SCORING, UMBRALES)
    assert np.allclose(out[list(COMPONENTES)].sum(axis=1), out["xp"], atol=1e-9)
    assert (out["xp"] >= 0).all()
    assert (out["xp_sd"] >= 0).all()

    # GW1 con solo 2025-26 en history
    prev_only = hist[hist["season"] == "2025-26"]
    roster_gw1 = roster.copy()
    roster_gw1["gw"] = 1
    out_gw1 = pm.project(prev_only, roster_gw1, proba, SCORING, UMBRALES)
    assert np.allclose(out_gw1[list(COMPONENTES)].sum(axis=1), out_gw1["xp"], atol=1e-9)
    # El novato premium (£11.5m) debe proyectar más xP que el MID barato (£4.5m) en GW1
    xp_by_key = dict(zip(roster_gw1["player_key"], out_gw1["xp"]))
    assert xp_by_key["mid_new_prem"] > xp_by_key["mid_low_1"]
