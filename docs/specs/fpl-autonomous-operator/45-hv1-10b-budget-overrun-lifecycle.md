---
type: deployment-evidence
name: "HV1-10B — Agent budget overrun lifecycle"
created: 2026-08-31
updated: 2026-08-31
tags: [mova, fpl, agents, budget, overrun, observability]
status: verified-live
---

# HV1-10B — Agent budget overrun lifecycle

## Objetivo

Convertir el overrun detectado por el scorecard en mejora continua verificable, sin borrar costo,
elevar presupuesto ni cerrar el hallazgo mediante una declaración no comprobada.

## Contrato implementado

- ledger inmutable `agent_budget_overrun_events` en SQLite y `agent.budget_overrun_events` en
  PostgreSQL;
- transiciones `open -> reviewed -> resolved|waived`, con actor, razón, acción, hashes e
  idempotencia semántica;
- `resolved` sólo acepta una reserva posterior equivalente, liquidada y dentro del límite;
- CLI `mova cost overrun`, endpoint `/api/v1/budget-overrun-events` y métrica
  `mova_agent_budget_overrun_reviews{scope,status}`;
- scorecard económico con estados `unreviewed`, `reviewed_pending` y `closed`;
- Researcher limitado a diez búsquedas, doce documentos finales y una salida acotada; si no
  alcanza cobertura marca `not_checked` en lugar de consumir sin límite;
- ninguna transición modifica controles, presupuesto, equipo o autoridad.

## Evidencia viva

- implementación `10189f8`; replay sanitizado `73daf4e`;
- evento `budgetoverrun_c2b244cb8c964561396a5302`, evidencia
  `f20345581f6f065eebe36989bb76904fd36e107eea095f34df9b33d4c9b04678`;
- reserva observada `budget_01c7c07ea38ce1c1a4371d25`: 167.678 tokens sobre límite 160.000,
  exceso 7.678;
- transición viva `open -> reviewed`, acción `optimize_prompt`, `runtime_mutated=false`;
- replay exacto `reused` y sanitizado; misma clave con intención distinta rechazada sin mutación;
- scorecard: 13/19 pass, 6 pending, 0 blocked; economics `reviewed_pending`, cero reservas
  huérfanas y presupuestos agregados dentro de límite;
- PostgreSQL import `pgimport_ddf74236e7b54151a2e7956dd7741c2a`: 55/55 tablas, paridad de
  contenido pass; el evento replica 1/1;
- doctor: 22 pass, 0 warn, 0 fail; safety `safe_to_wait`; browser final apagado;
- checkout e imágenes API/browser en `73daf4e`;
- backup previo `/opt/orbital/backups/mova-fpl/20260831T032841Z`; backup PostgreSQL posterior
  `/opt/orbital/backups/mova-fpl/postgres/20260831T033541Z`.

## Pendiente temporal, no deuda de implementación

No se lanzó otra investigación artificial: quedan cuatro usos GW y duplicar la misma consulta
gastaría presupuesto sin nueva información deportiva. La próxima corrida legítima del Researcher
será el follow-up. Sólo si queda liquidada por debajo de 160.000 tokens podrá ejecutarse la
transición `reviewed -> resolved`; de lo contrario el caso seguirá visible para otra iteración.
