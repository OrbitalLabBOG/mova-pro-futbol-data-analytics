"""Research del operador en el acta: p_play antes de proyectar, seguro en p=0."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from mova_fpl.agent import contract, research as rs
from mova_fpl.cli import live as live_cli
from mova_fpl.engine.runner import Config, decide
from mova_fpl.engine.simulator import _candidates
from mova_fpl.engine.state import Candidate, State
from mova_fpl.ops import interventions as ops_iv
from mova_fpl.rules import get as get_rules
from mova_fpl.rules.base import Position

RULES = get_rules("2025-26").SQUAD
CATALOGO = get_rules("2025-26").CHIPS
GW = 5


def roster(avail=None):
    rows, e = [], 1
    for pos, n in zip(("GKP", "DEF", "MID", "FWD"), (5, 12, 12, 7)):
        for k in range(n):
            rows.append({"element": e, "position": pos, "team": f"C{e % 10}",
                         "value": int((4.0 + 0.1 * k) * 10), "name": f"{pos}{e}",
                         "disponibilidad": (avail or {}).get(e, 1.0)})
            e += 1
    return pd.DataFrame(rows)


def base_xp(frame):
    return np.array([2.0 + 0.4 * (int(e) % 7) + 0.1 * int(e) % 5 for e in frame["element"]])


class Projector:
    """Proyector falso: xP = base * disponibilidad. Cuenta llamadas."""
    def __init__(self):
        self.calls = 0

    def __call__(self, frame, disp):
        self.calls += 1
        xp = pd.Series(base_xp(frame) * np.clip(np.asarray(disp, dtype=float), 0, 1))
        return xp, pd.DataFrame({"element": frame["element"], "xp": xp})


def doc(**extra):
    return {"gw": GW, "source": "agent:noticias", "rationale": "rueda de prensa", **extra}


def args_for(tmp_path, document=None, chips=False):
    path = None
    if document is not None:
        path = tmp_path / "iv.json"
        path.write_text(json.dumps(document))
    return SimpleNamespace(interventions=str(path) if path else None, gw=GW, chips=chips)


# ------------------------------------------------------------------ validacion

def test_missing_source_or_rationale_rejected():
    body = {"gw": GW, "adjustments": [{"element": 3, "p_play": 0.0}]}
    with pytest.raises(ValueError, match="source"):
        rs.parse({**body, "rationale": "x"}, gw=GW)
    with pytest.raises(ValueError, match="rationale"):
        rs.parse({**body, "source": "julian"}, gw=GW)


def test_cap_on_adjusted_players():
    many = [{"element": i, "xp_multiplier": 0.9} for i in range(1, rs.MAX_ADJUSTED + 2)]
    with pytest.raises(ValueError, match="tope"):
        rs.parse(doc(adjustments=many), gw=GW)
    ok = rs.parse(doc(adjustments=many[:rs.MAX_ADJUSTED]), gw=GW)
    assert len(ok.adjusted_elements()) == rs.MAX_ADJUSTED


@pytest.mark.parametrize("bad", [
    {"element": 1, "p_play": 1.2}, {"element": 1, "p_play": float("nan")},
    {"element": 1, "xp_multiplier": 3.0}, {"element": 1}, {"element": 1, "p_play": 0.5, "x": 1},
])
def test_bad_adjustments_rejected(bad):
    with pytest.raises(ValueError):
        rs.parse(doc(adjustments=[bad]), gw=GW)


def test_empty_document_is_empty_and_needs_no_source():
    assert rs.parse({"gw": GW}, gw=GW).is_empty()


def test_chip_names_normalized_at_the_boundary():
    out = ops_iv.normalize_doc(doc(block_chips=["freehit", "bboost"], allow_chips=["3xc"]), gw=GW)
    assert out["block_chips"] == ["bench_boost", "free_hit"]
    parsed = rs.parse(out, gw=GW)
    assert parsed.intervention.allow_chips == frozenset({"triple_captain"})
    with pytest.raises(ValueError, match="chip"):
        ops_iv.normalize_doc(doc(block_chips=["nope"]), gw=GW)


def test_chip_block_takes_effect_in_state():
    st = State(season="2025-26", gw=GW, candidates=_candidates(roster(), pd.Series(base_xp(roster()))),
               rules=RULES, chips=CATALOGO)
    research = rs.parse(doc(allow_chips=["wildcard"], block_chips=["freehit"]), gw=GW)
    new = contract.apply(st, research.intervention)
    assert new.chips_allowed[GW] == frozenset({"wildcard"})
    only_block = contract.apply(
        replace_allowed(st, {GW: frozenset({"free_hit", "bench_boost"})}),
        rs.parse(doc(block_chips=["freehit"]), gw=GW).intervention)
    assert only_block.chips_allowed[GW] == frozenset({"bench_boost"})


def replace_allowed(state, allowed):
    from dataclasses import replace
    return replace(state, chips_allowed=allowed)


# ------------------------------------------------------------ p_play / veto / subir

def test_p_play_zero_is_safe_and_zeroes_xp(tmp_path):
    frame = roster()
    proj = Projector()
    research, adjusted, xp, _, info = live_cli._projection_with_research(
        args_for(tmp_path, doc(adjustments=[{"element": 30, "p_play": 0.0}])), frame, proj)
    row = adjusted.index[adjusted.element == 30][0]
    assert xp.iloc[row] == 0.0 and info["xp_raw_by_el"][30] > 0
    assert proj.calls == 2  # crudo + ajustado; ningún MILP


def test_model_availability_zero_does_not_divide_and_can_be_raised(tmp_path):
    frame = roster(avail={31: 0.0, 32: 0.5})
    proj = Projector()
    body = doc(adjustments=[
        {"element": 31, "p_play": 0.9, "confidence": "high", "reason": "entrenó"},
        {"element": 32, "p_play": 0.95, "confidence": "high"},
    ])
    research, adjusted, xp, _, info = live_cli._projection_with_research(
        args_for(tmp_path, body), frame, proj)
    by = dict(zip(adjusted.element, xp))
    assert by[31] > info["xp_raw_by_el"][31] == 0.0  # 0 -> 0.9 sin ZeroDivisionError
    assert by[32] == pytest.approx(info["xp_raw_by_el"][32] * 0.95 / 0.5)
    assert by[32] > info["xp_raw_by_el"][32]


def test_raising_above_model_requires_high_confidence(tmp_path):
    frame = roster(avail={32: 0.5})
    with pytest.raises(ValueError, match="confidence"):
        live_cli._projection_with_research(
            args_for(tmp_path, doc(adjustments=[{"element": 32, "p_play": 0.95}])),
            frame, Projector())
    # bajar nunca exige confianza
    live_cli._projection_with_research(
        args_for(tmp_path, doc(adjustments=[{"element": 32, "p_play": 0.1}])),
        frame, Projector())


def test_unknown_player_rejected(tmp_path):
    with pytest.raises(ValueError, match="roster"):
        live_cli._projection_with_research(
            args_for(tmp_path, doc(adjustments=[{"element": 9999, "p_play": 0.0}])),
            roster(), Projector())


def test_no_intervention_is_identical(tmp_path):
    frame = roster(avail={7: 0.5})
    plain, proj = Projector(), Projector()
    expected = plain(frame, frame["disponibilidad"].to_numpy())[0]
    research, same, xp, _, info = live_cli._projection_with_research(
        args_for(tmp_path), frame, proj)
    assert research is None and info is None and same is frame
    assert proj.calls == 1 and xp.equals(expected)
    # y un archivo vacío tampoco cambia nada
    research, same, xp, _, _ = live_cli._projection_with_research(
        args_for(tmp_path, {"gw": GW}), frame, Projector())
    assert research is None and xp.equals(expected)
    st = State(season="2025-26", gw=GW, candidates=_candidates(frame, xp), rules=RULES,
               horizon_xp={GW: dict(zip(frame.element, xp))})
    st2 = State(season="2025-26", gw=GW, candidates=_candidates(frame, expected), rules=RULES,
                horizon_xp={GW: dict(zip(frame.element, expected))})
    cfg = Config(policy="milp", top_k=0, time_limit=60)
    assert decide(GW, st, cfg).fingerprint() == decide(GW, st2, cfg).fingerprint()


def test_veto_drives_decision_and_deltas_are_projection_shifts(tmp_path):
    frame = roster()
    proj = Projector()
    cfg = Config(policy="milp", top_k=0, time_limit=60)

    def state_from(xp, f, mult=None):
        cands = _candidates(f, xp)
        return State(season="2025-26", gw=GW, candidates=cands, rules=RULES,
                     horizon_xp={GW: {c.element: c.xp for c in cands}})

    raw_xp = proj(frame, frame["disponibilidad"].to_numpy())[0]
    raw_state = state_from(raw_xp, frame)
    raw_dec = decide(GW, raw_state, cfg)
    star = raw_dec.captain
    research, adjusted, xp, _, info = live_cli._projection_with_research(
        args_for(tmp_path, doc(adjustments=[{"element": int(star), "p_play": 0.0}],
                               lock_out=[int(star)])), frame, proj)
    state = contract.apply(state_from(xp, adjusted), research.intervention)
    new_dec = decide(GW, state, cfg)
    assert star not in new_dec.squad_15 and new_dec.captain != star

    # reporte: cambio de la PROYECCIÓN del jugador, no diferencia entre soluciones
    names = {c.element: c.name for c in state.candidates}
    raw_by_el = info["xp_raw_by_el"]
    final = state.horizon_xp[GW]
    rows = rs.adjustment_report(research, names=names, model_availability=info["model_avail"],
                                xp_raw=raw_by_el, xp_final=final)
    row = next(r for r in rows if r["element"] == star)
    assert row["xp_after"] == 0.0 and row["delta_xp"] == pytest.approx(-raw_by_el[star], abs=1e-3)
    assert row["p_play_before"] == 1.0 and row["p_play_after"] == 0.0 and row["lock"] == "out"
    # re-score de la MISMA decisión: bajar al vetado es esperable; no se vende como pérdida
    same_decision_raw = rs.rescore(raw_dec, raw_by_el)
    assert same_decision_raw == pytest.approx(raw_dec.expected_points, abs=1.0)
    assert rs.rescore(raw_dec, final) < same_decision_raw  # la vieja XI ya no vale
    # la nueva decisión re-puntuada con el xP crudo NO supera a la óptima cruda
    assert rs.rescore(new_dec, raw_by_el) <= same_decision_raw + 1e-6


def test_multiplier_applies_after_projection_to_gw_and_horizon():
    frame = roster()
    xp = pd.Series(base_xp(frame))
    cands = _candidates(frame, xp)
    st = State(season="2025-26", gw=GW, candidates=cands, rules=RULES,
               horizon_xp={GW: {c.element: c.xp for c in cands},
                           GW + 1: {c.element: c.xp for c in cands}})
    research = rs.parse(doc(adjustments=[{"element": 20, "xp_multiplier": 0.5}]), gw=GW)
    new = contract.apply(st, research.intervention)
    before = next(c.xp for c in st.candidates if c.element == 20)
    assert next(c.xp for c in new.candidates if c.element == 20) == pytest.approx(before / 2)
    assert new.horizon_xp[GW + 1][20] == pytest.approx(before / 2)


def test_live_does_not_wire_attribution_or_extra_solves():
    source = Path(live_cli.__file__).read_text()
    assert "attribution" not in source and "measure(" not in source


# ------------------------------------------------------------------ notas

class FakeDB:
    def __init__(self, notes):
        self.notes = notes

    def strategy_notes(self, **kw):
        return [n for n in self.notes if n["kind"] in kw.get("kinds", (n["kind"],))]


def test_notes_mapper_ignores_ordinary_notes_and_maps_structured_ones():
    notes = [
        {"kind": "decision", "players": {"captain": 1, "chip": "freehit"}, "text": "XI ok",
         "source": "owner", "actor": "j", "superseded": False},
        {"kind": "hypothesis", "players": [], "text": "ruido libre", "source": "assistant",
         "actor": "bot", "superseded": False},
        {"kind": "hypothesis", "source": "assistant", "actor": "bot", "superseded": False,
         "text": "Rueda de prensa: dudoso confirmado",
         "players": {"research_adjustment": {
             "adjustments": [{"element": 32, "p_play": 0.95, "confidence": "high"}],
             "block_chips": ["freehit"]}}},
        {"kind": "hypothesis", "source": "assistant", "actor": "bot", "superseded": True,
         "text": "viejo", "players": {"research_adjustment": {
             "adjustments": [{"element": 33, "p_play": 0.0}]}}},
    ]
    out = ops_iv.doc_from_notes(FakeDB(notes), season="2025-26", gw=GW)
    parsed = rs.parse(out, gw=GW)
    assert set(parsed.p_play) == {32} and parsed.intervention.block_chips == {"free_hit"}
    assert "notes(" in parsed.intervention.author
    assert ops_iv.doc_from_notes(FakeDB(notes[:2]), season="2025-26", gw=GW) is None
    assert ops_iv.doc_from_notes(None, season="2025-26", gw=GW) is None


# --- revisión: hold con lock_out sobre un jugador propio; chips del planificador ---------

def _owned_state(lock_out=()):
    from mova_fpl.rules.base import Squad, SquadPlayer

    frame = roster()
    cands = _candidates(frame, pd.Series(base_xp(frame)))
    pick = []
    for pos, n in ((Position.GKP, 2), (Position.DEF, 5), (Position.MID, 5), (Position.FWD, 3)):
        pick += [c for c in cands if c.position == pos][:n]
    players = tuple(SquadPlayer(element=c.element, position=c.position, team=c.team,
                                price=c.price, purchase_price=c.price) for c in pick)
    ids = [p.element for p in players]
    by_pos = {pos: [p.element for p in players if p.position == pos] for pos in Position}
    starters = tuple(by_pos[Position.GKP][:1] + by_pos[Position.DEF][:4]
                     + by_pos[Position.MID][:4] + by_pos[Position.FWD][:2])
    bench = tuple(e for e in ids if e not in starters)
    squad = Squad(players=players, starters=starters, captain=starters[-1],
                  vice_captain=starters[-2], bench_order=bench, bank=1.0)
    return State(season="2025-26", gw=GW, candidates=cands, squad=squad, bank=1.0,
                 rules=RULES, free_transfers=1,
                 horizon_xp={GW: {c.element: c.xp for c in cands}},
                 lock_out=frozenset(lock_out)), ids


def test_hold_state_with_owned_lock_out_is_feasible_and_lets_the_veto_leave():
    from dataclasses import replace

    base, ids = _owned_state()
    vetoed = ids[7]
    state = replace(base, lock_out=frozenset({vetoed}))
    cfg = Config(policy="milp", top_k=0, time_limit=60)
    # construcción antigua: lock_in = owned choca con lock_out -> infactible
    with pytest.raises(Exception):
        decide(GW, replace(state, lock_in=frozenset(ids)), cfg)
    # construcción de cli.live: owned - lock_out
    hold = decide(GW, replace(state, lock_in=frozenset(ids) - state.lock_out), cfg)
    assert vetoed not in hold.squad_15
    assert vetoed in hold.transfers_out
    kept = set(ids) - {vetoed}
    assert kept <= set(hold.squad_15)  # el resto sí se conserva (hold)


def test_planner_chips_exclude_blocked_and_keep_allowed():
    from mova_fpl.engine.state import State as S

    st = S(season="2025-26", gw=GW, candidates=(), rules=RULES, chips=CATALOGO)
    avail = set(st.chips_available(GW))
    assert avail
    victim = sorted(avail)[0]
    research = rs.parse(doc(block_chips=[victim]), gw=GW)
    solo = live_cli._planner_chips(st, research)
    assert victim not in solo and solo == frozenset(avail - {victim})
    assert live_cli._planner_chips(st, None) == frozenset()
    everything = rs.parse(doc(block_chips=sorted(avail)), gw=GW)
    blocked_all = live_cli._planner_chips(st, everything)
    assert not (blocked_all & avail)  # nada evaluable: el planificador devuelve sin chips
