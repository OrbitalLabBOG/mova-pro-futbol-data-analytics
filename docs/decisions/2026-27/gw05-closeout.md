---
type: gameweek-closeout
created: 2026-09-22
season: 2026-27
gameweek: 5
status: closed-with-review-followup
---

# GW5 — cierre retrospectivo verificado

El 22 de septiembre a las 14:45 UTC se registró el cierre con FPL
`finished=true` y `data_checked=true`. Resultado: **60 puntos**, promedio 48,
banca 19, dos transferencias, cero hits, sin chip y sin autosubs.

La plantilla autenticada observada el 18 de septiembre a las 17:23:41 UTC,
antes del deadline de las 17:30, coincide con los quince picks oficiales,
posiciones, capitán y vicecapitán. Esto demuestra el estado manual observado;
no demuestra autor, motivo original ni ejecución autónoma. A0 permanece vigente.

## Comparación

| Escenario | xP | Puntos |
| --- | ---: | ---: |
| Plantilla final autenticada | 51,80 | 60 |
| Estado autenticado anterior sin cambios | 46,94 | 65 |

El delta realizado es −5. El comparador incorpora el autosub João Pedro → Thomas.
La banca de 19 puntos no demuestra que correspondiera usar Bench Boost.
El experimento separado `season_value_v2` obtuvo +21 frente a su propio control,
pero acumula solo dos jornadas y no cumple el mínimo de tres para promoción.

## Evidencia persistida

- Revisión: `review_508d792e47e3d4e237e30229`.
- Settlement: `settlement_215c7cbbff7709a27b4dfa53`.
- Job de cierre: `job_68eee4b58bbd4111a5dc6c9addf1a0dd`.
- Paquete VPS: `/var/lib/mova-fpl/artifacts/review-packages/2026-27/gw05_closeout-v2.json`.
- Artefacto de revisión SHA256: `6a3157f55851f306e753b4ac3a3893bd5078fe16e2d9c21e01dcd260972da16e`.
- Se verificaron siete checks y se registraron treinta resultados jugador/escenario.
- `mova review status --gw 5` devuelve `closed`.
- Reconciliación `job_03957ce17d274dea87a32d954b540cd8`: scorecards baseline y shadow
  de GW5 finales; analytics healthy. El cockpit ya identifica GW6.

## Recuperación posterior — 22/09, 15:20 UTC

La release `8a9d4d8`, seguida por `e15cce7`, corrigió el contrato de propuestas y
la recuperación idempotente. El mismo job `job_19f24d209d9e4ecc8443384baeaacc9c`
terminó en su segundo intento; el replay posterior devolvió `reused`, attempt 2.
La revisión causal `causalreview_cecf3bd08717004e954216e6` quedó persistida y el
incidente P2 `incident_3a203ef9d2e14b238474f7f89b9dc2e0` se resolvió por éxito.
Artefacto causal SHA256:
`6d2f80a506aa1c6394f8771d9525fd57df23264ddded57164896a12393fd881d`.

La propuesta `proposal_b9bba5493b35369d7108221d` confundía bloqueos operativos
`TEAM_STATE_FRESH` / `IRREVERSIBLE_ACTION_WINDOW` con un defecto del optimizador.
Se rechazó con evidencia mediante `evaluation_1862bb4e588c4b13ab819bff95ee1f13`,
sin lección promovida ni mutación de policy. `e15cce7` corrige la clasificación
para revisiones futuras. No se reescribió el artefacto causal histórico.

Los exports nuevos de `settle_trace` conservan etiqueta del comparador, autor
conocido o `unknown`, transferencias, hits y chip del paquete. Esta corrección
no cambia silenciosamente las trazas anteriores.

## Pendientes explícitos

1. La comparación MILP del paquete inicial fue rechazada por el validador de
   presupuesto, que no contempla adecuadamente la valorización de plantilla.
   Se utilizó el estado previo real con precios históricos de compra; no se
   relajó el gate. Falta un contrato retrospectivo de banco/ventas/compras
   respaldado por el estado previo sellado; no basta aceptar un presupuesto
   mayor declarado por el propio paquete.
2. La traza histórica GW5 conserva la etiqueta legacy `pure_model_v1.1.0` y
   atribución fija `julian+orbix`. La autoridad semántica de este cierre es el
   paquete v2 y su procedencia: comparador sin cambios. La traza por sí sola
   no demuestra autoría ni comparación contra un modelo puro.
3. Este cierre y la recuperación supervisada no suman una jornada autónoma
   sin rescate. AC-03 y AC-08 permanecen abiertos.

No hubo cambios de código, despliegue ni promoción durante el cierre factual de
las 14:45 UTC. Los cambios posteriores pertenecen a la
[iteración de recuperación](runtime-review-recovery-20260922.md).

El backup SQLite posterior al cierre terminó correctamente en
`/opt/orbital/backups/mova-fpl/20260922T145032Z` (job
`job_7df7a11c0f744fc7a30f4a77919065c2`). La copia PostgreSQL iniciada a las
14:50:40 UTC terminó y dejó su manifest en
`/opt/orbital/backups/mova-fpl/postgres/20260922T145040Z/manifest.json`.
La existencia del backup no acredita por sí sola una nueva prueba de restauración.
