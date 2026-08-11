"""Brazo de control: reglas deterministas sobre las MISMAS señales, sin LLM.

Aisla el valor marginal del razonamiento. Si estas cuatro reglas tontas capturan
casi toda la ganancia del agente, el LLM no esta aportando: esta redescubriendo
heuristicas que caben en veinte lineas.

Las reglas salen de lo que el propio agente destilo en el humo (HALLAZGOS.md),
para que el control sea generoso, no un hombre de paja.
"""
from __future__ import annotations

from mova_fpl.agent import Intervention

from experiments.agent_backtest.briefing import Briefer


class AgenteReglas:
    def __init__(self, season: str):
        self.briefer = Briefer(season)
        self.season = season

    def __call__(self, state) -> Intervention | None:
        gw = state.gw
        snap = self.briefer._snapshot(gw)
        hist = self.briefer._historial(gw)
        mult, motivos = {}, []

        for c in state.candidates:
            e = c.element
            s, h = snap.get(e), hist.get(e, [])
            if not s or not h:
                continue
            balance = s["transfers_balance"] or 0
            ult = h[-1]

            # R1 exodo masivo: el mercado sabe algo que el historico no refleja
            if balance < -300_000:
                mult[e] = min(mult.get(e, 1.0), 0.5)
                motivos.append(f"{e}: exodo {balance}")
            # R2 sustitucion temprana anomala (titular, <25 min, sin roja)
            elif ult["starts"] and 0 < ult["minutes"] < 25 and not ult["red_cards"]:
                mult[e] = min(mult.get(e, 1.0), 0.5)
                motivos.append(f"{e}: sustituido al {ult['minutes']}'")
            # R3 dejo de ser titular con salida de managers
            elif not ult["starts"] and ult["minutes"] == 0 and balance < -50_000:
                mult[e] = min(mult.get(e, 1.0), 0.6)
                motivos.append(f"{e}: 0 min + salidas")

        if not mult:
            return None
        return Intervention(gw=gw, author="rules:v1",
                            rationale="; ".join(motivos[:6]), xp_multiplier=mult)
