---
work_key: WP-INIT-MOVA-FPL-ENGINE-007
title: "Operacion GW1 2026/27 - decision en vivo, acta y reconciliacion"
work_type: workpack
spec_version: 1
spec_status: approved
priority: critical
estimated_hours: 8
parent_key: null
depends_on_keys: [WP-INIT-MOVA-FPL-ENGINE-003, WP-INIT-MOVA-FPL-ENGINE-006]
---

# WP-007 — Operación de GW1

## Objetivo y resultado

Emitir el acta de decisión para la gameweek 1 de la temporada 2026/27 antes del deadline
`2026-08-21T17:30:00Z` (12:30 Bogotá), usando la misma `decide()` validada en el harness.

Este workpack cierra el objetivo primario de la iniciativa.

## Requisitos cubiertos

REQ-F-011, REQ-Q-006, REQ-S-002

## No objetivos

- **No se escribe en la API de FPL.** El acta se entrega; Julián la ingresa (ADR-006).
- No se monta cron ni servicio.

## Precondiciones y dependencias

- WP-003 (traza y runner) y WP-006 (optimizador) terminados.
  Si WP-006 no está listo el 18-ago, se ejecuta con la heurística de WP-003 (corte de R-01).
- **BLOQUEO Q-01:** se necesita el `entry_id` del equipo FPL de Julián para leer estado
  real. Para GW1 el estado inicial es trivial (sin plantilla previa, £100M, 1 FT), así que
  el bloqueo aplica desde GW2, no para GW1.

## Superficie permitida

```
mova_fpl/cli/live.py
mova_fpl/data/sources/fpl_live.py     (sólo GET)
mova_fpl/engine/report.py
outputs/fpl/2026-27/gw01_decision.md  (nuevo)
docs/runbook-fpl.md                   (nuevo)
```

## Interfaces y comportamiento

```bash
python -m mova_fpl.cli.live --season 2026-27 --gw 1 --dry-run
python -m mova_fpl.cli.live --season 2026-27 --gw 1
```

El acta incluye: 15 jugadores con posición, club, precio y xP desglosado; XI; banco
ordenado; capitán y vicecapitán; costo total y banco restante; timestamp de emisión;
versión de modelo y git sha; y una declaración explícita si algún dato provino de caché por
fallo de la fuente.

## Criterios de aceptación

| ID | Requisito | Criterio verificable |
| --- | --- | --- |
| AC-WP007-001 | REQ-F-011 | El acta de GW1 existe, con timestamp anterior a `2026-08-21T17:30:00Z` |
| AC-WP007-002 | REQ-F-011 | `rules_2026_27.validate_squad` sobre la plantilla del acta devuelve `[]` |
| AC-WP007-003 | REQ-F-011 | El acta reporta xP desglosado por jugador y el git sha del modelo usado |
| AC-WP007-004 | REQ-Q-006 | El ciclo completo (descarga + entrenamiento + optimización + acta) tarda ≤ 10 minutos |
| AC-WP007-005 | REQ-S-002 | El test de verbos HTTP confirma que sólo hubo `GET` contra `fantasy.premierleague.com` |
| AC-WP007-006 | REQ-F-010 | La decisión queda persistida en la traza en estado `committed` |
| AC-WP007-007 | REQ-F-011 | El runbook documenta cómo re-correr una jornada y qué hacer si la fuente no responde antes del deadline |

## Verificación

```bash
time python -m mova_fpl.cli.live --season 2026-27 --gw 1 --dry-run
pytest tests/test_readonly_http.py -v
python -m mova_fpl.trace.query --run latest --gw 1
```

## Evidencia requerida

| Criterio | Tipo | Evidencia esperada |
| --- | --- | --- |
| AC-WP007-001 | artefacto | Acta de GW1 con timestamp de emisión |
| AC-WP007-002 | artefacto | Salida de `validate_squad` sobre la plantilla del acta |
| AC-WP007-003 | artefacto | Acta con xP desglosado por jugador y git sha del modelo |
| AC-WP007-004 | medición | Salida de `time` del ciclo completo |
| AC-WP007-005 | test | pytest `test_readonly_http.py` |
| AC-WP007-006 | consulta | Fila de traza en estado `committed` |
| AC-WP007-007 | documento | `docs/runbook-fpl.md` |

## Rollback

El acta es un documento; no hay efecto externo que revertir. Si el motor falla antes del
deadline, Julián arma el equipo manualmente — la ausencia de escritura automática
(REQ-S-002) garantiza que no haya daño.

## Definition of Done

- [ ] Todos los criterios requeridos tienen evidencia `pass`.
- [ ] El acta fue entregada antes del deadline.
- [ ] La expectativa comunicada a Julián viene del harness, no de una estimación optimista.
