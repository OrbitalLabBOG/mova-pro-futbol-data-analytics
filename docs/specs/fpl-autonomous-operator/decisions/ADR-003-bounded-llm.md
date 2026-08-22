---
type: decision
name: "ADR-003 — LLM limitado a señales e intervenciones"
created: 2026-08-21
updated: 2026-08-21
tags: [mova, fpl, adr, llm, safety]
status: proposed
---

# ADR-003 — LLM limitado a señales e intervenciones

## Decisión

El LLM extrae `ResearchSignal` y propone el `Intervention` existente. No genera `Decision`,
no invoca el executor y no puede forzar plantilla, XI o capitán.

## Razón

El laboratorio observó confabulación causal, abuso semántico de `0.0`, reincidencia e
inflación de reglas. Además, el efecto pareado actual no demuestra mejora.

## Alternativas

- LLM manager end-to-end: descartado por no reproducible;
- reglas de noticias manuales: seguras pero insuficientes para texto abierto;
- extracción LLM + policy determinista + MILP: seleccionada.

## Consecuencias

El sistema puede mejorar con noticias sin perder un baseline medible. Las intervenciones se
evalúan localmente con/sin sobre el mismo estado y solo se promueven por evidencia.
