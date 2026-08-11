"""Backtest con agencia: replay del motor con un agente LLM moviendo entradas.

Uso:
  source ../orbital-os/.env.local   # OPENROUTER_API_KEY  (o exportarla)
  python -m experiments.agent_backtest.run --max-gw 10 --model google/gemini-2.5-pro
  python -m experiments.agent_backtest.run --max-gw 10 --arm baseline   # brazo sin agente

Dos brazos con la MISMA config y seed; la diferencia de puntos es el valor del
agente. Cada intervencion queda ademas medida individualmente en la traza
(expected vs realized delta) — la misma maquinaria que mide los chips.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from mova_fpl.agent import Intervention, validate
from mova_fpl.engine.runner import Config
from mova_fpl.engine.simulator import replay
from mova_fpl.trace import TraceWriter

from experiments.agent_backtest.briefing import Briefer
from experiments.agent_backtest.llm import LLM, parse_json
from experiments.agent_backtest.memory import Memoria
from experiments.agent_backtest.prompts import DECIDIR, REFLEXIONAR

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "agent_backtest"


class AgenteLLM:
    """agent_fn para replay(): decide pre-deadline y reflexiona al despertar en la GW siguiente."""

    def __init__(self, season: str, model: str, run_dir: Path, trace: TraceWriter, run_id: str):
        self.season, self.model = season, model
        self.tag = model.split("/")[-1]
        self.llm = LLM(model, run_dir / "llm_calls.csv")
        self.briefer = Briefer(season)
        self.memoria = Memoria(run_dir / "memoria.json")
        self.trace, self.run_id = trace, run_id
        self.run_dir = run_dir
        self.pendiente_reflexion: int | None = None

    # ---------- reflexion sobre la GW anterior (lazy, al despertar) ----------
    def _reflexionar(self) -> None:
        gw = self.pendiente_reflexion
        self.pendiente_reflexion = None
        import sqlite3
        con = sqlite3.connect(self.trace.db_path)
        con.row_factory = sqlite3.Row
        fila = con.execute(
            "SELECT payload, expected_delta, realized_delta, points_with, points_without,"
            " changed, detail FROM interventions WHERE run_id=? AND gw=?",
            (self.run_id, gw)).fetchone()
        if fila is None:
            return
        detalle = json.loads(fila["detail"] or "{}")
        payload = json.loads(fila["payload"] or "{}")
        jugadores = {}
        for pid, factor in (payload.get("xp_multiplier") or {}).items():
            r = self.briefer.can.execute(
                "SELECT name, minutes, total_points FROM player_gameweek"
                " WHERE season=? AND gw=? AND element=?",
                (self.season, gw, int(pid))).fetchone()
            if r is not None:
                jugadores[f"{r['name']} (id {pid})"] = {
                    "factor_que_aplicaste": factor,
                    "minutos_reales": r["minutes"], "puntos_reales": r["total_points"]}
                self.memoria.registrar_call_jugador(gw, int(pid), r["name"], factor,
                                                    r["minutes"], r["total_points"])
        resultado = {
            "que_hizo_cada_jugador_que_tocaste": jugadores,
            "cambio_la_decision": bool(fila["changed"]),
            "xp_prometido": fila["expected_delta"],
            "puntos_reales_con_tu_intervencion": fila["points_with"],
            "puntos_reales_sin_ella": fila["points_without"],
            "delta_real": fila["realized_delta"],
            "jugadores_que_entraron_por_tu_intervencion": detalle.get("entran", []),
            "jugadores_que_salieron": detalle.get("salen", []),
        }
        prompt = REFLEXIONAR.format(gw=gw, intervencion=fila["payload"],
                                    resultado=json.dumps(resultado, ensure_ascii=False, indent=1))
        try:
            salida = parse_json(self.llm.call(prompt, f"reflexion-gw{gw}"))
            self.memoria.registrar_reflexion(gw, salida)
        except Exception as e:                          # una reflexion perdida no tumba la corrida
            print(f"      ⚠️ reflexion GW{gw} fallida: {e}")
        if fila["changed"]:
            self.memoria.registrar_calibracion(gw, fila["expected_delta"] or 0.0,
                                               fila["realized_delta"])

    # ---------- decision pre-deadline ----------
    def __call__(self, state) -> Intervention | None:
        if self.pendiente_reflexion is not None:
            self._reflexionar()
        gw = state.gw
        cuerpo = self.briefer.build(state, self.memoria.bloque_prompt())
        prompt = DECIDIR.format(season=self.season, gw=gw, model_tag=self.tag) + cuerpo
        (self.run_dir / f"briefing_gw{gw:02d}.txt").write_text(prompt)

        propuesta = None
        for intento in range(2):
            try:
                d = parse_json(self.llm.call(prompt, f"decidir-gw{gw}", effort="high"))
                d.pop("tesis_semana", None)
                d["gw"] = gw                             # el agente no puede equivocarse de GW
                propuesta = Intervention.from_dict(d)
                problemas = validate(propuesta, state)
                if not problemas:
                    break
                detalle = "; ".join(f"{p.code}: {p.detail}" for p in problemas)
                print(f"      ⚠️ GW{gw} intervencion invalida ({detalle}), reintento")
                prompt += f"\n\nTU RESPUESTA ANTERIOR FUE INVALIDA: {detalle}. Corrige y responde de nuevo."
                propuesta = None
            except Exception as e:
                print(f"      ⚠️ GW{gw} intento {intento+1} fallo: {e}")
        if propuesta is not None and not propuesta.is_empty():
            self.pendiente_reflexion = gw
            n = len(propuesta.xp_multiplier)
            print(f"      🤖 GW{gw}: interviene ({n} multiplicadores) — {propuesta.rationale[:90]}...")
        else:
            print(f"      🤖 GW{gw}: sin intervencion")
        return propuesta


def main() -> None:
    ap = argparse.ArgumentParser(description="Backtest con agencia")
    ap.add_argument("--season", default="2025-26")
    ap.add_argument("--max-gw", type=int, default=10)
    ap.add_argument("--model", default="google/gemini-2.5-pro")
    ap.add_argument("--arm", default="agent", choices=["agent", "baseline", "rules"])
    ap.add_argument("--mode", default="anonymized", choices=["anonymized", "named"],
                    help="modo del MOTOR. anonymized = el canonico (2303). El agente ve "
                         "nombres reales en ambos: el briefing sale del almacen, no del State")
    ap.add_argument("--horizon", type=int, default=3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--chips", action="store_true", default=True)
    ap.add_argument("--label", default="")
    ap.add_argument("--shadow", action="store_true",
                    help="modo sombra: mide el efecto local de cada intervencion sin dejar "
                         "que cambie la trayectoria. Muestras pareadas limpias (recomendado)")
    args = ap.parse_args()

    etiqueta = args.label or (args.arm if args.arm == "baseline" else args.model.split("/")[-1])
    sufijo = "-shadow" if args.shadow else ""
    run_id = f"agentbt-{args.season}-gw{args.max_gw}-{etiqueta}{sufijo}-s{args.seed}"
    run_dir = OUT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    cfg = Config(policy="milp", projector="points", horizon=args.horizon, seed=args.seed,
                 chip_policy="planner" if args.chips else "none")
    trace = TraceWriter()

    agente = None
    if args.arm == "agent":
        agente = AgenteLLM(args.season, args.model, run_dir, trace, run_id)
    elif args.arm == "rules":
        from experiments.agent_backtest.rules_arm import AgenteReglas
        agente = AgenteReglas(args.season)

    t0 = time.time()
    rep = replay(args.season, mode=args.mode, config=cfg, trace=trace, run_id=run_id,
                 max_gw=args.max_gw, verbose=True, agent_fn=agente,
                 agent_shadow=args.shadow)
    dt = time.time() - t0

    resumen = {"run_id": run_id, "arm": args.arm, "mode": args.mode,
               "shadow": args.shadow, "model": args.model if args.arm == "agent" else None,
               "total_points": rep.total, "gws": len(rep.gameweeks),
               "wall_seconds": round(dt, 1),
               "llm_cost_usd": round(agente.llm.gastado, 4)
               if (agente is not None and hasattr(agente, "llm")) else 0.0}
    (run_dir / "resumen.json").write_text(json.dumps(resumen, indent=1))
    print(f"\n{'='*60}\n{json.dumps(resumen, indent=1)}")


if __name__ == "__main__":
    main()
