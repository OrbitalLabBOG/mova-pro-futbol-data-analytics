---
type: evidence
name: "HV1-08B — observabilidad y reconciliación semántica de budget agentic"
created: 2026-08-30
updated: 2026-08-30
tags: [mova, fpl, budgets, costs, agents, observability]
status: implemented-pending-rollout
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
