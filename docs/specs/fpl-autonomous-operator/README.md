---
type: project
name: "MOVA FPL Autonomous Operator 2026/27 — Specification Index"
created: 2026-08-21
updated: 2026-08-21
tags: [mova, fpl, autonomy, observability, specification]
status: proposed
---

# MOVA FPL Autonomous Operator 2026/27

Especificación de la iniciativa sucesora del motor FPL v1. Define cómo operar el equipo
durante toda la temporada con ciclos autónomos, trazables y seguros, sin cambiar la lógica
de decisión que ya vive en `mova_fpl/`.

Este paquete es **solo diseño**. No autoriza despliegues, migraciones locales, cambios en
la cuenta FPL ni activación de automatizaciones externas. Supabase queda fuera del runtime:
solo conserva el seguimiento PM de construcción del proyecto.

## Estado

| Campo | Valor |
| --- | --- |
| Versión | 0.1 |
| Estado | `proposed` |
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
| [decisions/](decisions/) | decisiones arquitectónicas propuestas |
| [workpacks/](workpacks/) | unidades de implementación futura; ninguna está autorizada aún |

## Principio rector

La autonomía no significa libertad para improvisar. Significa que cada jornada puede
avanzar sin intervención rutinaria porque las fuentes, decisiones, límites, reintentos,
verificaciones y criterios de parada están codificados y son observables.
