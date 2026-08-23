---
type: project
name: "MOVA FPL Autonomous Operator 2026/27 — Traceability"
created: 2026-08-21
updated: 2026-08-22
tags: [mova, fpl, traceability, workpacks]
status: proposed
---

# Trazabilidad

## Requisitos a decisiones

| Requisitos | ADR |
| --- | --- |
| F-001, F-017, Q-001..003 | ADR-001 orquestador determinista por deadline |
| F-002, F-003, F-008, F-015 | ADR-002 snapshots inmutables y manifest raíz |
| F-005..007, O-009..010 | ADR-003 LLM como intervención acotada |
| F-011..013, S-001..009 | ADR-004 ejecución por niveles y compliance gate |
| F-017, Q-008..011 | ADR-005 Docker + systemd en VPS |
| F-004, F-014..017, S-003..004, O-004 | ADR-006 almacenamiento dividido |
| O-001..010 | ADR-007 observabilidad local + ledger |
| F-012..016, Q-003..004, S-006 | ADR-008 exactly-once observable y hard stop |
| F-019..026, Q-012..014, S-011..014, O-011..012 | ADR-009 coordinador delgado con Pydantic AI/Codex |
| F-005, F-025, S-012, S-014 | ADR-010 discovery separado de evidencia recuperada |

## Requisitos a workpacks

| Workpack | Requisitos principales | Evidencia de cierre futura |
| --- | --- | --- |
| WP-001 Runtime/deploy | Q-005, Q-008, Q-010..011, S-007..008 | image digest, versions, tests, restore/reboot drill |
| WP-002 Control plane | F-001, F-017, Q-001..002, Q-011, S-003..004, O-004 | SQLite migration, concurrency, integrity/backup e idempotency tests |
| WP-003 Data quality | F-002..004, Q-004, Q-007 | snapshot manifest, drift fixtures, stale-source drill |
| WP-004 Research | F-005..006, F-019..026, Q-012..014, S-009, S-011..014, O-009, O-011..012 | schemas, queue/importer, gold claims, evidence/SSRF/injection tests, provider replay, budgets y redaction |
| WP-005 Decision lifecycle | F-007..010, F-014..015, Q-006 | replay, model registry, shadow attribution |
| WP-006 Browser executor | F-011..013, S-001..002, S-006, S-008 | DOM contracts, ambiguous-save drill, evidence hash |
| WP-007 Observability | O-001..010 | dashboards, alert fire/ack, correlation continuity |
| WP-008 Rollout | F-016, Q-003, S-006, S-010 | deadline rehearsal, gate approvals, rollback drill |

## Definition of done de la iniciativa

La iniciativa futura solo converge cuando:

1. todos los MUST tienen evidencia enlazada y reproducible;
2. no existen blockers P0/P1 abiertos;
3. el sistema completó el mínimo de shadow y supervised definido en G3/G4;
4. los estados privados se reconcilian sin suposiciones de venta/FT;
5. cada write ensayado tiene preview, reload, checks y evidencia hash;
6. alertas y kill switch funcionan bajo deadline simulado;
7. compliance y action levels tienen aprobación registrada;
8. el deploy exacto se reconstruye desde Git y artifacts;
9. el agente LLM sigue en shadow salvo promoción basada en atribución pareada;
10. Julián y Buitra aprueban el nivel de autonomía que se activa.

## Evidencia que no cuenta

- un toast o screenshot anterior a guardar;
- “el job terminó sin excepción” sin validación de salida;
- un total de temporada de una sola trayectoria;
- una recomendación LLM sin fuentes y TTL;
- un modelo `.joblib` sin dataset/config/git hash;
- un cron instalado sin ledger, alerta y recovery drill;
- un contenedor `healthy` que no valida la semántica de la última ingestión;
- una fila de `ops.db` alterada manualmente sin audit event ni migration.
