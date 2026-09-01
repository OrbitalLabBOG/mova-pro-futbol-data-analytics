---
type: deployment-evidence
name: "HV1-08C — cadencia agentic por slots"
created: 2026-09-01
updated: 2026-09-01
tags: [mova, fpl, agents, cadence, budget, observability]
status: verified-live
---

# HV1-08C — cadencia agentic por slots

## Problema observado

El feedback provisional de GW2 encontró que el circuito de seguridad detenía correctamente el
gasto, pero demasiado tarde: GW3 acumuló `835790/900000` tokens comprometidos y `19/20` usos en
baseline. Research tenía intervalo mínimo, pero no slots máximos; Strategist/Critic podía además
reservar presupuesto ante cada envelope con identidad semántica nueva.

## Cambio

La revisión `69d12e1` despliega `bounded-deliberation-1.1.0`:

1. Researcher tiene un intento automático por slot: `broad` T-30h…T-6h, `refresh` T-6h…T-2h y
   `final` T-120…T-70 minutos.
2. Un intento terminal consume el slot; un replay no crea otra identidad para ocultar el fallo.
3. Strategist/Critic requiere research `imported`, manifest posterior al import y ausencia de una
   deliberación posterior para ese research.
4. Semantic reuse se consulta antes del gate y conserva bindings sin reservar tokens.
5. Baseline, settlement y el hard cutoff no abren inferencias automáticas.

No se añadió migración ni se cambió el presupuesto, los controles o la autoridad.

## Verificación

| Check | Resultado |
| --- | --- |
| Pruebas focalizadas | 22 passed |
| Suite hermética | 1218 passed, 79 deselected |
| Compileall / Compose / diff | pass |
| Backup previo | SQLite + PostgreSQL; PostgreSQL `20260901T035105Z` |
| Revisión checkout/imagen | `69d12e1` / `69d12e1` |
| API | ready y healthy |
| Doctor | 23 PASS, 0 WARN, 0 FAIL |
| Research baseline | `outside_research_window`, exit 75 |
| Gate deliberación directo | `outside_deliberation_window`, `due=false` |
| Timer research real | `Result=success`, `ExecMainStatus=75`; no worker Codex |
| Presupuesto antes/después | `835790` tokens, `19` usos, `0` reservas |
| Cola/watchdog | healthy; 0 requests, 0 anomalías |
| Safety | `safe_to_wait` |

## Estado y rollback

El despliegue permanece `shadow/A0`, `kill_switch=true`, `compliance=pending` y
`browser_writes=false`; `fpl_mutated=false`. El único uso restante de GW3 no se fuerza ni se
recupera elevando límites: la policy nueva preserva el ledger histórico y operará normalmente en
las siguientes ventanas/GWs. Ante regresión, la imagen y revisión anterior `c80c99f` permanecen
disponibles; no existe migración que revertir.
