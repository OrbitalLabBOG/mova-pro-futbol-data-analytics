"""Capa de contrato para agentes externos (LLM, humano, heuristica nueva).

La regla que sostiene todo el diseno
------------------------------------

    el agente PROPONE, el optimizador DISPONE

Un agente puede mover las ENTRADAS del sistema —cuanto espera que rinda un
jugador, que chips estan sobre la mesa, a quien no tocar esta semana— y nunca la
SALIDA. Quien arma la plantilla, elige el once y reparte el brazalete sigue
siendo el MILP.

No es purismo. Son dos razones concretas:

1. **Reparto de tareas por competencia.** Un modelo de lenguaje es bueno leyendo
   el mundo —ruedas de prensa, alineaciones probables, el parte medico de las
   ultimas horas— y malo resolviendo un problema combinatorio con quince
   variables acopladas y un presupuesto. El solver es exactamente al reves.

2. **Sin esto no hay medicion.** Si el agente decide directamente, se pierde la
   capacidad de responder "¿su intervencion sumo o resto?". Como solo mueve
   entradas, cada intervencion se puede evaluar resolviendo dos veces y restando
   marcadores reales. Es la misma maquinaria que ya mide los chips.

Lo que se gana: una temporada entera de intervenciones con su valor medido, que
es lo unico que distingue una estrategia de una supersticion.
"""
from mova_fpl.agent.contract import (Intervention, apply, describe, merge,
                                     validate)
from mova_fpl.agent.attribution import Attribution, measure, settle, summarize

__all__ = ["Intervention", "apply", "validate", "describe", "merge",
           "Attribution", "measure", "settle", "summarize"]
