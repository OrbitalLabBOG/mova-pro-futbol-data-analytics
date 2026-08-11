"""Simulador walk-forward. El entorno, no el agente.

Recorre una temporada jornada a jornada: entrega a `decide()` solo lo que se
sabia antes del cierre, y despues puntua la decision contra lo que de verdad
paso. Es el unico modulo autorizado a usar `Store.results()`.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace

import pandas as pd

from mova_fpl.data.store import Store
from mova_fpl.engine.baselines import all_baselines
from mova_fpl.engine.evaluate import score_decision
from mova_fpl.engine.naive import naive_projection
from mova_fpl.engine.planner import PlannerConfig, plan
from mova_fpl.engine.policies import optimizer_config
from mova_fpl.engine.projection import minutes_projection, points_projection
from mova_fpl.engine.runner import Config, decide
from mova_fpl.engine.state import Candidate, State
from mova_fpl.optimizer.horizon import build_xp_matrix, fixture_counts
from mova_fpl.rules import get as get_rules
from mova_fpl.rules.base import Position, Squad, SquadPlayer
from mova_fpl.rules.chips import ChipUse, wasted
from mova_fpl.rules.market import accumulate_free_transfers
from mova_fpl.agent import Attribution, apply as apply_intervention, settle
from mova_fpl.trace import TraceWriter

MAX_GW = 38


@dataclass
class RunReport:
    run_id: str
    season: str
    mode: str
    policy: str
    gameweeks: list[dict] = field(default_factory=list)
    baselines: dict = field(default_factory=dict)
    chips: list[dict] = field(default_factory=list)      # atribucion medida, chip a chip
    wasted_chips: list = field(default_factory=list)     # caducados sin jugar

    @property
    def total(self) -> int:
        return sum(g["points"] for g in self.gameweeks)

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.gameweeks)

    def render(self) -> str:
        df = self.to_frame()
        if df.empty:
            return "corrida vacia"
        out = [f"# Backtest {self.season} · politica `{self.policy}` · modo `{self.mode}`", "",
               f"run_id `{self.run_id}`", "",
               "| GW | Pts | Acum | Cap | Hits | Subs | Template | Techo |",
               "|---:|---:|---:|---:|---:|---:|---:|---:|"]
        acum = 0
        for g in self.gameweeks:
            acum += g["points"]
            out.append(f"| {g['gw']} | {g['points']} | {acum} | {g['captain_points']} | "
                       f"{g['hits']} | {g['auto_subs']} | {g['template']} | {g['ceiling']} |")
        out += ["", "## Resultado frente a baselines", "",
                "| Serie | Puntos | vs motor |", "|---|---:|---:|",
                f"| **Motor ({self.policy})** | **{self.total}** | — |"]
        for k, v in self.baselines.items():
            out.append(f"| {k} | {v} | {self.total - v:+d} |")
        techo = self.baselines.get("ceiling", 0)
        if techo:
            out += ["", f"Captura del techo con informacion perfecta: "
                        f"**{100 * self.total / techo:.1f}%**"]
        out += self._render_chips()
        return "\n".join(out)

    def _render_chips(self) -> list[str]:
        """Atribucion por chip: no estimada, MEDIDA contra el contrafactual.

        Para cada chip jugado se puntua tambien la decision que se habria tomado
        sin el, con los mismos resultados reales. La resta es su valor exacto.
        """
        if not self.chips:
            return []
        out = ["", "## Chips", "",
               "| GW | Chip | Real | Contrafactual | Valor | xp esperado | Motivo |",
               "|---:|---|---:|---:|---:|---:|---|"]
        total = 0
        for c in self.chips:
            total += c["value"]
            out.append(f"| {c['gw']} | {c['chip']} | {c['points']} | {c['counterfactual']} | "
                       f"**{c['value']:+d}** | {c['expected']:+.1f} | {c['reason']} |")
        out += ["", f"Valor medido de los chips: **{total:+d}** puntos."]
        if self.wasted_chips:
            perdidos = ", ".join(f"{c} ({w})" for w, c in self.wasted_chips)
            out.append(f"\n⚠️ Chips caducados sin usar: {perdidos}")
        return out


def _alias_equipos(store: Store, season: str) -> dict:
    """Mapa club -> pseudonimo, ESTABLE en toda la temporada.

    Construirlo por jornada era un error latente: en una jornada en blanco faltan
    clubes, los indices se corren y `CLUB_03` deja de ser el mismo equipo entre
    jornadas. Como la cuota de tres por club se evalua contra esa etiqueta, la
    restriccion se estaba aplicando sobre identidades inconsistentes.
    """
    return {t: f"CLUB_{i:02d}" for i, t in enumerate(store.teams(season))}


def _anonymize(roster: pd.DataFrame, alias: dict) -> pd.DataFrame:
    """Sustituye identidades por pseudonimos estables.

    Para el motor determinista es indiferente (no lee nombres). La capacidad
    existe para medir la contaminacion cuando entre un agente LLM, que si los lee.
    """
    df = roster.copy()
    df["team"] = df["team"].map(lambda t: alias.get(t, t))
    df["name"] = df.apply(lambda r: f"{r['position']}_{int(r['element']):04d}", axis=1)
    return df


def _calendario(store: Store, season: str, gw: int, hasta: int, alias: dict) -> dict:
    """{(equipo, gw): n_partidos} en un rango. Lo publicado, nada mas."""
    sched = store.team_schedule(season, gw, hasta)
    if alias:
        sched = sched.assign(team=sched["team"].map(lambda t: alias.get(t, t)))
    return fixture_counts(sched.to_dict("records"))


def _horizonte(candidatos, conteo: dict, gw: int, config, max_gw: int) -> dict:
    """Matriz xp del horizonte. La construye el ENTORNO, no la politica.

    Asi `State` sigue siendo un valor y `decide()` sigue sin tocar la base de datos
    (ADR-004). Lo unico que se lee es el CALENDARIO, que esta publicado.
    """
    if config.horizon <= 1 and config.policy != "milp":
        return {}
    hasta = min(max_gw, gw + config.horizon - 1)
    return build_xp_matrix(candidatos, conteo, gw, hasta - gw + 1, decay=config.decay)


def _candidates(roster: pd.DataFrame, xp: pd.Series) -> tuple[Candidate, ...]:
    out = []
    for (_, r), v in zip(roster.iterrows(), xp):
        if pd.isna(r["position"]) or pd.isna(r["team"]) or pd.isna(r["value"]):
            continue
        out.append(Candidate(element=int(r["element"]), position=Position.parse(r["position"]),
                             team=str(r["team"]), price=float(r["value"]) / 10.0,
                             xp=float(v), name=str(r["name"])))
    return tuple(out)


def _squad_from(decision, conocidos: dict, bank: float) -> Squad:
    """Reconstruye la plantilla usando el catalogo ACUMULADO.

    Filtrar por el catalogo de la jornada perdia a los jugadores en jornada en
    blanco y la plantilla se iba encogiendo hasta no admitir formacion valida.
    """
    faltan = [e for e in decision.squad_15 if e not in conocidos]
    if faltan:
        raise RuntimeError(f"jugadores sin atributos conocidos al arrastrar plantilla: {faltan}")
    players = tuple(
        SquadPlayer(element=e, position=conocidos[e]["position"],
                    team=conocidos[e]["team"], price=conocidos[e]["price"])
        for e in decision.squad_15
    )
    return Squad(players=players, starters=decision.starters, captain=decision.captain,
                 vice_captain=decision.vice_captain, bench_order=decision.bench_order, bank=bank)


def _con_intervencion(gw: int, state: State, propuesta, config: Config):
    """Decide dos veces —sin y con la intervencion— y arma la ficha de atribucion.

    Espejo de `agent.measure()` que ademas devuelve ambas decisiones, para que el
    replay use la decision intervenida sin resolver el MILP una tercera vez.
    """
    base = decide(gw, state, config)
    tocado = apply_intervention(state, propuesta)
    con = decide(gw, tocado, config)
    att = Attribution(
        gw=gw, author=propuesta.author, rationale=propuesta.rationale,
        expected_delta=round(con.expected_points - base.expected_points, 3),
        changed=base.fingerprint() != con.fingerprint(),
        detail={
            "fingerprint_sin": base.fingerprint(), "fingerprint_con": con.fingerprint(),
            "chip_sin": base.chip, "chip_con": con.chip,
            "entran": sorted(set(con.squad_15) - set(base.squad_15)),
            "salen": sorted(set(base.squad_15) - set(con.squad_15)),
            "capitan_sin": base.captain, "capitan_con": con.captain,
        },
    )
    return tocado, con, base, att


def replay(season: str, mode: str = "named", config: Config | None = None,
           store: Store | None = None, trace: TraceWriter | None = None,
           run_id: str | None = None, resume: bool = False,
           max_gw: int = MAX_GW, verbose: bool = True,
           agent_fn=None, agent_shadow: bool = False) -> RunReport:
    if mode not in ("named", "anonymized"):
        raise ValueError(f"modo desconocido: {mode}")
    config = config or Config()
    store = store or Store()
    trace = trace or TraceWriter()
    run_id = run_id or f"{season}-{config.policy}-{mode}-{uuid.uuid4().hex[:8]}"

    modelo_min, modelos = None, None
    if config.projector == "minutes":
        from mova_fpl.models.registry import load
        modelo_min = load("minutes", config.model_version)
    elif config.projector == "points":
        from mova_fpl.models.registry import load
        modelos = {"minutes": load("minutes", "1.0.0"),
                   "points": load("points", config.model_version)}
    elif config.projector != "naive":
        raise ValueError(f"proyector desconocido: {config.projector}")

    rules_mod = get_rules(season)
    rules = rules_mod.SQUAD
    catalogo = rules_mod.CHIPS
    con_chips = config.chip_policy == "planner"
    pcfg = PlannerConfig(enabled=con_chips, structure_lookahead=config.structure_lookahead)
    chips_used: list[ChipUse] = []
    ya_hechas = trace.completed_gws(run_id) if resume else set()
    trace.start_run(run_id, season, mode, config.policy, config.horizon, config.seed,
                    {"season": season, "mode": mode, "max_gw": max_gw})

    alias = _alias_equipos(store, season) if mode == "anonymized" else {}
    report = RunReport(run_id=run_id, season=season, mode=mode, policy=config.policy)
    conocidos: dict = {}          # catalogo acumulado: sobrevive a jornadas en blanco
    squad: Squad | None = None
    free_transfers, bank = 1, 0.0
    acum_baselines: dict = {}

    for gw in range(1, max_gw + 1):
        if gw in ya_hechas:
            continue

        historia = store.as_of(season, gw)          # cold start real en gw=1
        roster = store.roster(season, gw)
        if roster.empty:
            continue
        if mode == "anonymized":
            roster = _anonymize(roster, alias)

        if modelos is not None:
            xp = points_projection(historia, roster, modelos, season)
        elif modelo_min is not None:
            xp = minutes_projection(historia, roster, modelo_min)
        else:
            xp = naive_projection(historia, roster)
        candidatos = _candidates(roster, xp)
        if len(candidatos) < rules["size"]:
            continue

        # Un solo vistazo al calendario: el horizonte del optimizador y la
        # estructura que ve el planificador salen del mismo rango consultado.
        alcance = max(config.horizon, config.structure_lookahead + 1 if con_chips else 0)
        conteo = _calendario(store, season, gw, min(max_gw, gw + alcance), alias)
        horizon_xp = _horizonte(candidatos, conteo, gw, config, max_gw)

        state = State(season=season, gw=gw, candidates=candidatos, squad=squad,
                      free_transfers=free_transfers, bank=bank, rules=rules,
                      horizon_xp=horizon_xp,
                      chips=catalogo if con_chips else None,
                      chips_used=tuple(chips_used),
                      schedule=conteo if con_chips else {})

        veredicto = None
        if con_chips and not state.is_cold_start:
            # En la GW1 no hay plantilla que arreglar: ningun chip tiene sentido.
            veredicto = plan(state, horizon_xp or {gw: {c.element: c.xp for c in candidatos}},
                             optimizer_config(config, len(horizon_xp) or 1), pcfg)
            if veredicto.chip:
                state = replace(state, chips_allowed={gw: frozenset({veredicto.chip})})

        _libres_previas = free_transfers
        propuesta = att = decision_sin = None
        if agent_fn is not None and not state.is_cold_start:
            propuesta = agent_fn(state)
            if propuesta is not None and propuesta.is_empty():
                propuesta = None
        if propuesta is not None:
            tocado, con_int, decision_sin, att = _con_intervencion(gw, state, propuesta, config)
            if agent_shadow:
                # SOMBRA: se mide el efecto local de la intervencion pero la trayectoria
                # sigue siendo la del baseline. Cada jornada es una muestra pareada limpia,
                # sin el ruido de camino que domina los totales de temporada.
                decision, decision_sin = decision_sin, con_int
                att = replace(att, detail={**att.detail, "shadow": True})
            else:
                state, decision = tocado, con_int
        else:
            decision = decide(gw, state, config)

        conocidos.update({c.element: {"position": c.position, "team": c.team, "price": c.price}
                          for c in candidatos})

        resultados = store.results(season, gw)      # oraculo: solo para puntuar
        outcome = score_decision(decision, resultados, rules, conocidos)
        bases = all_baselines(resultados, rules, config.seed + gw)

        trace.record_gw(run_id, decision, outcome, train_rows=len(historia), state="reconciled")
        trace.record_baselines(run_id, gw, bases)

        if att is not None:
            # El valor de la intervencion se liquida contra los MISMOS resultados
            # reales que la decision intervenida (misma maquinaria que los chips).
            otro = score_decision(decision_sin, resultados, rules, conocidos)
            # `settle` recibe siempre (con intervencion, sin intervencion), en ese orden:
            # en sombra la decision jugada es la del baseline, asi que los papeles se invierten.
            con_pts, sin_pts = ((otro.points, outcome.points) if agent_shadow
                                else (outcome.points, otro.points))
            trace.record_intervention(run_id, gw, propuesta, settle(att, con_pts, sin_pts))

        report.gameweeks.append({
            "gw": gw, "points": outcome.points, "expected": decision.expected_points,
            "captain_points": outcome.captain_points, "hits": decision.hits,
            "auto_subs": len(outcome.auto_subs), "train_rows": len(historia),
            "transfers": len(decision.transfers_in), "chip": decision.chip or "",
            **bases,
        })
        for k, v in bases.items():
            acum_baselines[k] = acum_baselines.get(k, 0) + v

        if decision.chip:
            chips_used.append(ChipUse(gw=gw, chip=decision.chip))
            report.chips.append(_atribuir(decision, outcome, state, config, resultados,
                                          rules, conocidos, veredicto))

        arranque_en_frio = squad is None
        if decision.chip == "free_hit":
            # La plantilla REVIERTE: el free hit no deja rastro en el equipo real.
            # Tampoco consume transferencias, asi que las libres acumulan normal.
            free_transfers = accumulate_free_transfers(free_transfers, 0,
                                                       rules["max_free_transfers"])
        else:
            squad = _squad_from(decision, conocidos, bank)
            # Tras armar la plantilla inicial se llega a la GW2 con UNA transferencia
            # libre, no con dos: la plantilla de arranque no consume ninguna, pero
            # tampoco acumula. `accumulate_free_transfers` daba 2 y regalaba un cambio.
            free_transfers = 1 if arranque_en_frio else accumulate_free_transfers(
                free_transfers, len(decision.transfers_in), rules["max_free_transfers"])
            bank = decision.bank_after
            if decision.chip == "wildcard":
                # El wildcard no destruye las libres: se conservan y suman una.
                free_transfers = min(rules["max_free_transfers"], _libres_previas + 1)

        if verbose:
            print(f"  GW{gw:>2}  {outcome.points:>3} pts  (esperado {decision.expected_points:>5.1f})"
                  f"  template {bases['template']:>3}  techo {bases['ceiling']:>3}"
                  f"  entrenado con {len(historia):>5} filas")

    report.baselines = acum_baselines
    if con_chips:
        report.wasted_chips = wasted(tuple(chips_used), catalogo, max_gw)
    trace.finish_run(run_id, report.total)
    return report


def _atribuir(decision, outcome, state, config, resultados, rules, conocidos, veredicto) -> dict:
    """Valor REAL de un chip: lo que se saco menos lo que se habria sacado sin el.

    Se vuelve a decidir con la autorizacion retirada y se puntua esa decision
    contra los mismos resultados. No es una estimacion del modelo: es la resta de
    dos marcadores reales. La misma maquinaria medira despues al agente.
    """
    contrafactual = None
    try:
        sin_chip = decide(state.gw, replace(state, chips_allowed={}), config)
        contrafactual = score_decision(sin_chip, resultados, rules, conocidos).points
    except Exception as exc:                                   # noqa: BLE001
        return {"gw": state.gw, "chip": decision.chip, "points": outcome.points,
                "counterfactual": None, "value": 0,
                "expected": veredicto.value if veredicto else 0.0,
                "reason": f"contrafactual no calculable: {exc}"}
    return {
        "gw": state.gw, "chip": decision.chip, "points": outcome.points,
        "counterfactual": contrafactual, "value": outcome.points - contrafactual,
        "expected": veredicto.value if veredicto else 0.0,
        "reason": veredicto.reason if veredicto else "",
    }
