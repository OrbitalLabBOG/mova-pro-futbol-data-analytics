---
type: deployment-evidence
name: "HV1-08 — mejora continua fail-closed"
created: 2026-08-30
updated: 2026-08-30
tags: [mova, fpl, hv1-08, learning, costs, rollout]
status: verified-shadow
---

# HV1-08 — mejora continua fail-closed

## Alcance

Este corte convierte el feedback post-GW en un workflow consultable y auditable sin concederle
autoridad sobre producción. Implementa propuestas, evaluaciones, lecciones validadas y un
read-model de uso/costo. No implementa todavía el reviewer causal automático, budgets duros ni
la aplicación de un cambio aceptado.

## Evidencia de implementación

| Componente | Evidencia |
| --- | --- |
| Rama | `feat/continuous-improvement-gate` |
| Commits | `420e7d2`, `8a091c0`, `045bcc8` |
| VPS checkout/imagen | `1d67eae` / `mova-fpl-engine:1d67eae` |
| SQLite | migration `011`, aplicada |
| PostgreSQL shadow | migration `013`, aplicada |
| Import shadow | `pgimport_7ab05a115f8f4639a1ae0bcb18173814` |
| Reconciliación | 46/46 tablas `pass`, incluidas evaluations y lessons |
| Tests | 906 passed, 1 skipped, 79 deselected |
| Doctor vivo | 22 PASS, 0 WARN, 0 FAIL |
| Runtime vivo | `healthy`, siete timers, browser detenido |
| Backup | SQLite y PostgreSQL, `20260830T172323Z`, service result `success` |

El gate admite `proposed → testing → accepted|rejected`. La aceptación exige experimento,
timestamp, baseline, candidato, evidencia de tests, criterio aprobado y rollback. Reintentar la
misma transición reutiliza la clave; usarla con otro contenido falla. `accepted` crea una lesson,
pero devuelve explícitamente `runtime_mutated=false`.

La lectura viva contabilizó 12 usos Codex por suscripción, 512.805 tokens de entrada y 38.514 de
salida. Como no existe costo atribuible por llamada, `estimated_cost_usd=null` y
`unknown_cost_uses=12`; el sistema no los convierte en USD 0.

## Hallazgo operativo corregido

El dashboard estaba `critical` por un P1 del 28 de agosto ya superado. Collector y analytics
reconciliaban incidentes al recuperarse, pero el tick no. Un tick exitoso ahora resuelve
`Tick MOVA falló` y añade `incident_resolved` al audit log. La corrida forzada auditada
`rollout:045bcc8:recovery` completó, cerró el P1 y devolvió el runtime a `healthy`.

## Guardrails observados

- `mode=shadow`;
- `action_level=A0`;
- `compliance_gate=pending`;
- `kill_switch=true`;
- `browser_writes=false`;
- cero execution attempts y browser detenido.

La corrida de verificación selló una decisión GW3 y un preflight `blocked`; no hizo clicks ni
modificó el equipo. Supabase conserva únicamente el checkpoint PM al 98% y no recibió datos
operativos.

## Pendiente para cerrar HV1-08

1. producir review causal automáticamente después de cada settlement elegible;
2. aplicar budgets por job, GW y mes con alertas;
3. vincular una lesson aceptada con experimento, shadow y promoción/rollback reales;
4. medir la utilidad atribuida de research y decisiones durante varias GWs.
