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

## Pendientes explícitos

1. La revisión causal falla al proponer mejoras: `CausalReviewerService._proposals`
   genera `change_level=experiment` y `priority=medium`, incompatibles con los enums
   persistidos C0–C3 y P0–P3. Incidente P2
   `incident_3a203ef9d2e14b238474f7f89b9dc2e0`; job fallido
   `job_19f24d209d9e4ecc8443384baeaacc9c`. El reintento con la misma clave devuelve
   `reused` aunque el job falló: corregir también la recuperación idempotente.
   No marcar la revisión causal como completada; el cierre factual sigue válido.
2. La comparación MILP del paquete inicial fue rechazada por el validador de presupuesto,
   que no contempla adecuadamente la valorización de plantilla. Se utilizó el estado previo
   real con precios históricos de compra; no se relajó el gate. MILP pendiente de evaluación.
3. `settle_trace` conserva la etiqueta legacy `pure_model_v1.1.0` y atribución fija
   `julian+orbix`. Para este cierre la autoridad semántica es el paquete v2 y su procedencia:
   comparador sin cambios, autor de clicks no determinado. Corregir estas etiquetas antes
   de usar la traza como evidencia de autoría o de un modelo puro.

No hubo cambios de código, despliegue ni promoción durante el cierre.

El backup SQLite posterior al cierre terminó correctamente en
`/opt/orbital/backups/mova-fpl/20260922T145032Z` (job
`job_7df7a11c0f744fc7a30f4a77919065c2`). La copia PostgreSQL iniciada a las
14:50:40 UTC seguía en curso en la última observación, con unos 24,7 MB escritos;
no se declara completa ni restaurada. El último backup PostgreSQL completo
observado antes de este cierre es `20260922T102352Z`.
