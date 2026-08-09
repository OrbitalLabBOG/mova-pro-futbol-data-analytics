---
work_key: WP-INIT-MOVA-FPL-ENGINE-007
title: "Operacion GW1 2026/27 - decision en vivo, acta y reconciliacion"
work_type: workpack
spec_version: 2
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
  el bloqueo aplica desde GW2, no para GW1. **Sigue abierto** y documentado en el runbook §8.
- **Q-05 (horizonte)**, abierta. Se opera con `--horizon 3`, que es el mejor con el modelo
  vigente y está en el medio del rango medido. La justificación está en el runbook §5; no es
  una decisión demostrada, es un defecto razonado.

## Superficie permitida

```
mova_fpl/cli/live.py
mova_fpl/data/live.py                 (v2: en vez de sources/fpl_live.py, ver abajo)
mova_fpl/engine/report.py
outputs/fpl/2026-27/gw01_decision.md  (nuevo)
docs/runbook-fpl.md                   (nuevo)
```

**Desviación de superficie en v2.** La v1 preveía `data/sources/fpl_live.py` con su propio
acceso a red. Se implementó como `data/live.py` **sin ninguna llamada de red**: consume
`fetch_bootstrap()` y `fetch_fixtures()` de `sources.py`, que sigue siendo el único `urlopen`
del paquete. La alternativa habría dejado dos puntos de salida a internet y debilitado
`test_la_unica_primitiva_de_red_es_get`, que es la garantía de REQ-S-002.

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

| Criterio | Tipo | Evidencia esperada | Entregada |
| --- | --- | --- | --- |
| AC-WP007-001 | artefacto | Acta de GW1 con timestamp de emisión | `evidence/WP-007-acta-gw01.md` — emitida 2026-08-09T20:35:02Z, 11,9 días de margen |
| AC-WP007-002 | artefacto | Salida de `validate_squad` sobre la plantilla del acta | `evidence/WP-007-operacion.md` — devuelve `[]` |
| AC-WP007-003 | artefacto | Acta con xP desglosado por jugador y git sha del modelo | `evidence/WP-007-acta-gw01.md` — desglose por componente en las 15 filas |
| AC-WP007-004 | medición | Salida de `time` del ciclo completo | `evidence/WP-007-operacion.md` — 5,6 s contra un techo de 600 |
| AC-WP007-005 | test | pytest `test_readonly_http.py` | `evidence/WP-007-operacion.md` — 4 pruebas sobre 30 módulos |
| AC-WP007-006 | consulta | Fila de traza en estado `committed` | `evidence/WP-007-operacion.md` — run `2026-27-live-milp-h3` |
| AC-WP007-007 | documento | `docs/runbook-fpl.md` | 8 secciones, incluido el plan B si la API no responde |

## Rollback

El acta es un documento; no hay efecto externo que revertir. Si el motor falla antes del
deadline, Julián arma el equipo manualmente — la ausencia de escritura automática
(REQ-S-002) garantiza que no haya daño.

## Definition of Done

- [x] Todos los criterios requeridos tienen evidencia `pass`.
- [x] El acta fue entregada antes del deadline, con 11,9 días de margen. **Se emite marcada
      como borrador**: a esa distancia del cierre los precios y el parte médico todavía se
      mueven. Lo que queda demostrado es que el ciclo funciona contra datos reales de
      2026/27, no cuál es el equipo definitivo. La corrida que cuenta va dentro de las 24
      horas previas (runbook §2).
- [x] La expectativa comunicada viene del harness: **2.217 puntos** en el backtest ciego de
      2025-26, frente a 2.043 del baseline `template`. No es una estimación optimista, es la
      cifra medida — con la salvedad declarada de que el sistema en vivo usa el parte médico,
      que el backtest no tiene, y esa diferencia no está cuantificada.

## Cambio de versión

**v1 → v2 (2026-08-09).** Se sustituye `data/sources/fpl_live.py` por `data/live.py` sin
acceso a red, se anotan las evidencias entregadas y se registra que Q-01 y Q-05 siguen
abiertas. Los criterios de aceptación no cambian: son los mismos siete de v1.

## Lo que queda abierto

| # | Asunto | Impacto |
| --- | --- | --- |
| Q-01 | Falta el `entry_id` del equipo | **Bloquea desde la GW2.** Sin él, el motor no sabe de qué plantilla parte y solo puede proponer un equipo desde cero |
| Q-05 | Horizonte de producción sin fijar | Se opera con 3 por defecto razonado; decidirlo bien exige más temporadas |
| H-WP007-01 | La decisión en vivo usa el parte médico y el backtest no | El 2.217 medido no es exactamente el sistema que opera. El sesgo es favorable pero no está cuantificado |
