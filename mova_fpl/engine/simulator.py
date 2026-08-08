"""Simulador walk-forward. El entorno, no el agente.

Recorre una temporada jornada a jornada: entrega a `decide()` solo lo que se
sabia antes del cierre, y despues puntua la decision contra lo que de verdad
paso. Es el unico modulo autorizado a usar `Store.results()`.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import pandas as pd

from mova_fpl.data.store import Store
from mova_fpl.engine.baselines import all_baselines
from mova_fpl.engine.evaluate import score_decision
from mova_fpl.engine.naive import naive_projection
from mova_fpl.engine.projection import minutes_projection, points_projection
from mova_fpl.engine.runner import Config, decide
from mova_fpl.engine.state import Candidate, State
from mova_fpl.optimizer.horizon import build_xp_matrix, fixture_counts
from mova_fpl.rules import get as get_rules
from mova_fpl.rules.base import Position, Squad, SquadPlayer
from mova_fpl.rules.market import accumulate_free_transfers
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
        return "\n".join(out)


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


def _horizonte(store: Store, season: str, gw: int, candidatos, config, alias: dict,
               max_gw: int) -> dict:
    """Matriz xp del horizonte. La construye el ENTORNO, no la politica.

    Asi `State` sigue siendo un valor y `decide()` sigue sin tocar la base de datos
    (ADR-004). Lo unico que se lee es el CALENDARIO, que esta publicado.
    """
    if config.horizon <= 1 and config.policy != "milp":
        return {}
    hasta = min(max_gw, gw + config.horizon - 1)
    sched = store.team_schedule(season, gw, hasta)
    if alias:
        sched = sched.assign(team=sched["team"].map(lambda t: alias.get(t, t)))
    conteo = fixture_counts(sched.to_dict("records"))
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


def replay(season: str, mode: str = "named", config: Config | None = None,
           store: Store | None = None, trace: TraceWriter | None = None,
           run_id: str | None = None, resume: bool = False,
           max_gw: int = MAX_GW, verbose: bool = True) -> RunReport:
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

        horizon_xp = _horizonte(store, season, gw, candidatos, config, alias, max_gw)
        state = State(season=season, gw=gw, candidates=candidatos, squad=squad,
                      free_transfers=free_transfers, bank=bank, rules=rules,
                      horizon_xp=horizon_xp)
        decision = decide(gw, state, config)

        conocidos.update({c.element: {"position": c.position, "team": c.team, "price": c.price}
                          for c in candidatos})

        resultados = store.results(season, gw)      # oraculo: solo para puntuar
        outcome = score_decision(decision, resultados, rules, conocidos)
        bases = all_baselines(resultados, rules, config.seed + gw)

        trace.record_gw(run_id, decision, outcome, train_rows=len(historia), state="reconciled")
        trace.record_baselines(run_id, gw, bases)

        report.gameweeks.append({
            "gw": gw, "points": outcome.points, "expected": decision.expected_points,
            "captain_points": outcome.captain_points, "hits": decision.hits,
            "auto_subs": len(outcome.auto_subs), "train_rows": len(historia),
            "transfers": len(decision.transfers_in), **bases,
        })
        for k, v in bases.items():
            acum_baselines[k] = acum_baselines.get(k, 0) + v

        arranque_en_frio = squad is None
        squad = _squad_from(decision, conocidos, bank)
        # Tras armar la plantilla inicial se llega a la GW2 con UNA transferencia
        # libre, no con dos: la plantilla de arranque no consume ninguna, pero
        # tampoco acumula. `accumulate_free_transfers` daba 2 y regalaba un cambio.
        free_transfers = 1 if arranque_en_frio else accumulate_free_transfers(
            free_transfers, len(decision.transfers_in), rules["max_free_transfers"])
        bank = decision.bank_after

        if verbose:
            print(f"  GW{gw:>2}  {outcome.points:>3} pts  (esperado {decision.expected_points:>5.1f})"
                  f"  template {bases['template']:>3}  techo {bases['ceiling']:>3}"
                  f"  entrenado con {len(historia):>5} filas")

    report.baselines = acum_baselines
    trace.finish_run(run_id, report.total)
    return report
