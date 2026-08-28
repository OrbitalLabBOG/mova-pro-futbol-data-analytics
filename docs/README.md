---
type: project
name: "MOVA FPL — Technical Documentation"
updated: 2026-08-27
status: active
tags: [mova, fpl, documentation]
---

# Documentación técnica

| Necesidad | Fuente |
| --- | --- |
| Entender el motor | [Arquitectura](architecture/decision-engine.md) |
| Operar una jornada | [Runbook de jornada](operations/gameweek.md) |
| Consultar `mova status/doctor` | [Contrato del operador](operations/operator.md) |
| Diagnosticar o desplegar el VPS | [Runbook VPS](operations/vps.md) |
| Operar PostgreSQL shadow | [Runbook PostgreSQL](operations/postgres-shadow.md) |
| Operar plan y research | [Contexto estratégico](operations/strategic-research.md) |
| Consultar la decisión GW1 | [Research y decisión](decisions/2026-27/gw01-research-and-decision.md) |
| Auditar el experimento de odds/eventos | [Ablación causal](decisions/2026-27/odds-events-ablation.md) |
| Implementar el harness | [Autonomous Harness v1](specs/fpl-autonomous-operator/10-autonomous-harness-v1.md) |
| Auditar el motor v1 cerrado | [Spec del decision engine](specs/fpl-decision-engine/README.md) |
| Recuperar el capítulo histórico | [Historia](history.md) |

`10-autonomous-harness-v1.md` es la hoja de ruta ejecutable. Las specs 08 y 09 son
referencias de hardening, no backlog automático.
