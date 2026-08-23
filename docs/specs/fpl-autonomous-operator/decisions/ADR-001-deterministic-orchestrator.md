---
type: decision
name: "ADR-001 — Orquestador determinista por deadline"
created: 2026-08-21
updated: 2026-08-22
tags: [mova, fpl, adr, orchestration]
status: proposed
---

# ADR-001 — Orquestador determinista por deadline

## Decisión

Usar una máquina de estados explícita ejecutada por un `tick` idempotente. El deadline
oficial determina qué trabajo vence; un LLM no decide el orden del workflow.

## Alternativas

| Opción | Razón de descarte/selección |
| --- | --- |
| crons independientes por tarea | simples, pero sin estado común, idempotencia ni recuperación coherente |
| agente LLM planner | flexible, pero difícil de reproducir y peligroso cerca de deadlines |
| LangGraph | descartado para esta iniciativa: duplica estado, checkpoints y retries ya resueltos en `ops.db` |
| máquina de estados propia | seleccionada: pequeña, auditable y compatible con el motor actual |

## Consecuencias

Cada transición tiene precondiciones, output y estado terminal. Un cambio futuro de
framework requeriría una ADR explícita y evidencia de una necesidad que la máquina actual
no pueda resolver; no es parte de la hoja de ruta vigente.
