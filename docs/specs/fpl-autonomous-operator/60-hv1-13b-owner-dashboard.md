---
type: implementation-evidence
name: "HV1-13B — dashboard ejecutivo para el owner"
created: 2026-09-01
updated: 2026-09-01
tags: [mova, fpl, dashboard, owner, observability, caddy, ux]
status: complete
---

# HV1-13B — dashboard ejecutivo para el owner

## Resultado

El cockpit web dejó de presentar el contrato técnico completo a Julián. La vista principal ahora
responde sólo tres preguntas: si el sistema funciona, cuándo es el próximo cierre y si el owner
debe avisar a ORBIX. CLI y API conservan toda la profundidad técnica para diagnóstico.

- runtime: `df8cff4`;
- infraestructura Caddy: `5f78f0f`;
- URL: `https://mova.72-60-245-2.sslip.io`;
- página pública sin contraseña; diagnóstico externo bloqueado.

## Semántica visual

- verde / **Todo está funcionando**: no hay P0/P1, safety es `safe_to_wait` y operator, datos,
  analytics y PostgreSQL están saludables;
- rojo / **Necesito que avises a ORBIX**: existe un P0/P1, safety inseguro o una capa core
  degradada;
- los P2 internos —presupuesto bajo, alertas `local_only` o deliberación no crítica— se resumen
  como pendientes bajo control y no alarman al owner;
- el deadline se presenta en `America/Bogota` y como tiempo relativo, nunca como ISO/segundos en
  la vista principal;
- el detalle mínimo está plegado por defecto.

La vista no usa un LLM por refresh. El resumen es determinista, auditable y no consume tokens; el
agente conserva el diagnóstico profundo mediante `mova cockpit --json` y `mova triage --json`.

## Frontera pública

Caddy sólo enruta `/` y `/dashboard` hacia el API loopback. Desde Internet, `/api/*`, `/metrics`,
`/readyz` y rutas desconocidas responden `404`. Los secretos legacy de Basic Auth y el drop-in de
systemd fueron retirados; no se abrió `127.0.0.1:8787` ni se amplió autoridad.

## Evidencia

| Prueba | Resultado |
| --- | --- |
| Suite completa | `1239 passed, 1 skipped, 79 deselected` |
| Contratos cockpit/read-only | `273 passed` |
| Vista desktop y móvil | revisadas con browser real; sin overflow móvil final |
| Página pública `/` y `/dashboard` | `200` |
| API, métricas y readyz públicos | `404` |
| API local cockpit | `200`, `mova-cockpit-v1` |
| POST público/local | `405` |
| Doctor | `23/23 PASS` |
| Timers / unidades fallidas | `8 / 0` |
| Deployment parity | checkout e imagen `df8cff4`, healthy |
| Servicio Caddy previo | `premier` continuó respondiendo `200` |

Al validar el estado vivo, la pantalla mostró verde, `Tu acción: Ninguna`, safety
`safe_to_wait` y cero incidentes críticos. La ruta roja se cubrió con prueba de contrato P1.
