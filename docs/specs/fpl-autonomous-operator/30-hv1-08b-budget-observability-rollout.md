---
type: evidence
name: "HV1-08B — observabilidad y reconciliación semántica de budget agentic"
created: 2026-08-30
updated: 2026-08-30
tags: [mova, fpl, budgets, costs, agents, observability]
status: deployed-shadow
---

# HV1-08B — observabilidad de budget agentic

## Problema observado

Una corrida Researcher viva reportó más tokens reales que el techo por job y el reporte agrupaba
dos rechazos terminales bajo `reserved`. El presupuesto agregado sí seguía comprometido, pero el
operador no podía distinguir jobs activos, consumo conocido y cargos inciertos.

## Contrato implementado

- `consumed_*`: usage real escrito en `cost_ledger`;
- `reserved_*`: exclusivamente requests todavía queued;
- `charged_estimate_*`: llamadas rechazadas sin usage confiable;
- `committed_*`: suma conservadora de las tres categorías;
- `job_overruns`: jobs settled cuyo actual supera el policy sellado de su reserva;
- `orphaned_reservations`: reservas activas sin subject queued correspondiente.

El settlement devuelto por cada import incluye reserva, actual, límite y `overrun`. Un overrun no
se oculta ni invalida retroactivamente evidencia que pasó sus validadores; queda como warning y
se descuenta el uso real. Una reserva huérfana tampoco se libera automáticamente. Prometheus suma
tres métricas específicas y conserva las métricas agregadas existentes.

## Evidencia previa al rollout

| Check | Resultado |
| --- | --- |
| pruebas focales budget/research/deliberation | 17 passed |
| suite hermética | 1017 passed, 1 skipped, 79 deselected |
| compileall | pass |
| schema/migración | sin cambio; derivación sobre ledger existente |
| controles FPL | sin modificación |

## Criterio de rollout

El reporte vivo debe mostrar cero reservas huérfanas, separar los dos cargos estimados de las
reservas activas y detectar el overrun real previamente observado. Checkout, imagen, doctor y
backup deben quedar alineados. El rollout no habilita browser, agentes adicionales ni autonomía.

## Rollout vivo

| Evidencia | Resultado |
| --- | --- |
| revisión funcional VPS | `0ca4b181` |
| reservas activas GW3 | 0 tokens / 0 usos |
| cargos estimados GW3 | 240.000 tokens / 2 usos |
| consumo real GW3 | 407.014 tokens / 13 usos |
| total comprometido GW3 | 647.014 / 900.000 tokens; 15/20 usos |
| overrun real | 1 job; 167.678 actual; 7.678 sobre policy |
| reservas huérfanas | 0 |
| métricas nuevas | presentes y con los mismos valores del CLI |
| API | healthy |
| doctor | 22 PASS, 0 WARN, 0 FAIL |
| backup predeploy | `/opt/orbital/backups/mova-fpl/20260830T225104Z` |
| backup postdeploy | `/opt/orbital/backups/mova-fpl/20260830T225154Z` |

El estado superior es `job_overrun_observed`; los scopes GW/mes permanecen `within_budget` porque
el comprometido agregado no excede sus techos. Esta distinción evita esconder el incumplimiento
por job sin afirmar falsamente que se agotó todo el presupuesto de la jornada.
