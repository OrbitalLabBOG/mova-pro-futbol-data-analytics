---
type: decision
name: "ADR-001 — Orquestador determinista por deadline"
created: 2026-08-21
updated: 2026-08-21
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
| LangGraph | válido si luego aparece branching complejo; hoy añade runtime sin resolver dominio |
| máquina de estados propia | seleccionada: pequeña, auditable y compatible con el motor actual |

## Consecuencias

Cada transición tiene precondiciones, output y estado terminal. Agregar LangGraph después es
posible si preserva estos contratos y no mueve la autoridad de decisión.
