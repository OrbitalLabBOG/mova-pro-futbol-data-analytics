---
type: deployment-evidence
name: "HV1-10C — Physical attempt budget accounting"
created: 2026-08-31
updated: 2026-08-31
tags: [mova, fpl, agents, retries, budget, cost, observability]
status: verified-live
---

# HV1-10C — Physical attempt budget accounting

## Problema cerrado

HV1-09J conservaba cada ejecución física, pero presupuesto y reportes seguían liquidando una sola
fila por research/deliberation. Un retry podía consumir dos llamadas y aparecer como un único uso;
un fallo con tokens conocidos seguía etiquetado como estimación. Esto dejaba el ledger correcto y
la barrera financiera incompleta.

## Contrato implementado

- cada `started` cuenta como un uso físico;
- los `finished` con input/output tokens se suman exactamente;
- el resultado validado puede completar una única salida exitosa sin tokens en su receipt;
- cada start sin evidencia terminal consume conservadoramente `reserved_tokens`;
- una liquidación guarda `actual_tokens`, `attempt_count`, `estimated_tokens` y
  `accounting_mode=exact|conservative|legacy`;
- `cost_ledger` conserva el resultado lógico y el reporte reemplaza su valor por la liquidación
  física asociada, evitando doble conteo;
- filas históricas sin reserva siguen visibles como legacy;
- la próxima reserva calcula límites GW/mes sobre usos y tokens físicos ya comprometidos;
- Prometheus diferencia cargos físicos totales de la porción estimada.

Persistencia:

- SQLite migration 020: columnas de accounting en `agent_budget_reservations`;
- PostgreSQL shadow migration 023: las mismas columnas en `agent.budget_reservations`;
- los cargos históricos quedan `conservative`, un intento y 100% estimado;
- las liquidaciones históricas quedan `legacy`, un intento y cero estimado.

## Verificación

- suite completa: 1.185 passed, 1 skipped, 79 deselected;
- pruebas focales: 58/58 para budget, attempts, migraciones, collector y control plane;
- fixtures específicos: dos fallos exactos = 24 tokens/2 usos; fallo+éxito = 24/2 sin doble
  conteo; dos starts sin finish = 200 tokens/2 usos conservadores;
- commit desplegado: `f7260d0`; checkout, engine, browser y research alineados;
- migraciones vivas SQLite 20 y PostgreSQL 23;
- import `pgimport_c3c3a4e5a56743448445277892b524e9`, paridad 56/56;
- doctor 23/23, watchdog `ok`, safety `safe_to_wait`;
- readiness 15/23 pass, 8 pending, 0 blocked;
- totales preexistentes preservados: GW3 426.818 consumidos + 240.000 charged = 666.818
  comprometidos; 14 + 2 = 16 usos; mes 1.019.605 tokens comprometidos;
- overrun real conserva `reviewed_pending`: 167.678 vs límite 160.000.

Backups:

- pre SQLite: `/opt/orbital/backups/mova-fpl/20260831T052822Z`;
- pre PostgreSQL: `/opt/orbital/backups/mova-fpl/postgres/20260831T052823Z`;
- post SQLite: `/opt/orbital/backups/mova-fpl/20260831T053040Z`;
- post PostgreSQL: `/opt/orbital/backups/mova-fpl/postgres/20260831T053041Z`.

No se ejecutó Codex para fabricar una muestra viva: no había una necesidad deportiva que
justificara gastar presupuesto. La cobertura de las nuevas ramas es hermética y la contabilidad
entra en vigor hacia adelante.

## Autoridad

El avance cierra observabilidad financiera, no amplía permisos. Producción continúa en
`shadow/A0`, kill switch activo, compliance pendiente y browser writes deshabilitado. Supabase
recibe únicamente el seguimiento PM; la operativa permanece en el VPS.
