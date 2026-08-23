---
type: project
name: "MOVA FPL Autonomous Operator 2026/27 — Specification Index"
created: 2026-08-21
updated: 2026-08-22
tags: [mova, fpl, autonomy, observability, specification]
status: active-shadow
---

# MOVA FPL Autonomous Operator 2026/27

Especificación de la iniciativa sucesora del motor FPL v1. Define cómo operar el equipo
durante toda la temporada con ciclos autónomos, trazables y seguros, sin cambiar la lógica
de decisión que ya vive en `mova_fpl/`.

La especificación ya tiene una primera implementación desplegada en el VPS en modo
**shadow A0**. Esto autoriza recolección, análisis, modelos y evidencia; no autoriza
cambios en la cuenta FPL. Supabase queda fuera del runtime: solo conserva el seguimiento
PM de construcción del proyecto.

## Estado

| Campo | Valor |
| --- | --- |
| Versión | 0.5 |
| Estado | `active-shadow` |
| Riesgo | alto: cuenta externa, deadlines irreversibles y sesión autenticada |
| Business owner | Julián Zuluaga |
| Aprobación técnica | pendiente de Nicolás Buitrago |
| Temporada | 2026/27 |
| Equipo | `losmillosFPL`, `entry_id=3609854` |
| Primera aplicación prevista | GW2; GW1 ya fue montada y sellada manualmente |

## Documentos

| Documento | Contenido |
| --- | --- |
| [00-brief.md](00-brief.md) | objetivo, alcance, hechos, riesgos y éxito |
| [01-requirements.md](01-requirements.md) | requisitos funcionales, calidad, seguridad y operación |
| [02-architecture.md](02-architecture.md) | componentes, estado, scheduling, ejecución y fallos |
| [03-data-and-observability.md](03-data-and-observability.md) | datos, trazas, métricas, SLO, alertas y retención |
| [04-readiness-and-rollout.md](04-readiness-and-rollout.md) | readiness actual, gates y rollout por niveles |
| [05-source-register.md](05-source-register.md) | reglas y referencias técnicas verificadas |
| [06-traceability.md](06-traceability.md) | requisitos → decisiones → workpacks → evidencia esperada |
| [07-deployment-evidence.md](07-deployment-evidence.md) | acta verificable del primer despliegue shadow en VPS |
| [08-agentic-research-harness.md](08-agentic-research-harness.md) | coordinador de investigación, backends, contratos, persistencia y roadmap |
| [09-agent-harness-implementation-spec.md](09-agent-harness-implementation-spec.md) | implementación exacta del harness, workers, budgets, seguridad, evals y despliegue |
| [contracts/](contracts/) | JSON Schemas máquina para request, result y signal |
| [decisions/](decisions/) | decisiones arquitectónicas propuestas |
| [workpacks/](workpacks/) | unidades de implementación y criterios todavía pendientes |

## Principio rector

La autonomía no significa libertad para improvisar. Significa que cada jornada puede
avanzar sin intervención rutinaria porque las fuentes, decisiones, límites, reintentos,
verificaciones y criterios de parada están codificados y son observables.
