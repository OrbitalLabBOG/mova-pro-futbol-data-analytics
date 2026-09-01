---
type: implementation-evidence
name: "HV1-13 — cockpit operativo, triage y sentinel de deadline"
created: 2026-09-01
updated: 2026-09-01
tags: [mova, fpl, cockpit, observability, watchdog, caddy, rollout]
status: complete
---

# HV1-13 — cockpit operativo, triage y sentinel de deadline

## Resultado

Se cerró la interfaz operativa mínima para que Julián vea el estado del producto y para que
ORBIX/Codex diagnostique el harness desde un contrato único. El cambio no agregó un control plane
paralelo, no habilitó escrituras en FPL y no alteró la autoridad A0.

- implementación del cockpit: `2301bf6` (incluye `c4bfe96`);
- infraestructura Caddy versionada en `orbital-os`: `8b0ca6a`;
- dashboard privado: `https://mova.72-60-245-2.sslip.io`;
- contrato compartido CLI/API/web: `mova-cockpit-v1`;
- contrato de diagnóstico: `mova-triage-v1`.

## Superficie entregada

- `mova cockpit [--json] [--watch N]` para panorama, automatización y observación continua;
- `mova triage [--incident-id ID] [--json]` para incidentes y jobs relacionados;
- `GET /api/v1/cockpit` y `GET /api/v1/triage`;
- dashboard HTML de solo lectura con GW/deadline, autoridad, funciones, stages, costos, calidad y
  alertas;
- acceso HTTPS con Basic Auth en Caddy y API ligada exclusivamente a `127.0.0.1:8787`;
- sentinel deadline-aware integrado al watchdog, con incidentes deduplicados y métricas
  Prometheus;
- runbook canónico en `docs/operations/cockpit.md` y skill de operador actualizada.

## Evidencia de verificación

| Prueba | Resultado |
| --- | --- |
| Suite completa | `1236 passed, 1 skipped, 79 deselected` |
| Suite cockpit/watchdog | `18 passed` después del ajuste final de estados |
| API local `/readyz` | `200`, contenedor healthy |
| Dashboard público sin credenciales | `401` |
| Cockpit autenticado | `200`, `schema=mova-cockpit-v1` |
| Escritura HTTP autenticada (`POST`) | `405` |
| TLS | certificado válido para `mova.72-60-245-2.sslip.io` |
| Servicios Caddy preexistentes | listener activo; `premier` respondió `200` |
| Sentinel GW3 fuera de T−6h | healthy, cero riesgos P0/P1 |

El fallo inicial del restart de Caddy fue operacional y reversible: el nuevo archivo de log no
existía con ownership del usuario `caddy`. Se creó con permisos mínimos, se reinició el servicio y
se repitió toda la validación. No hubo exposición temporal del API porque permaneció en loopback.

## Estado de control al cierre

- autoridad activa: A0/shadow;
- `writes_enabled=false` y browser writes apagado;
- kill switch activo;
- collector, analytics, research, backups locales y timers continúan habilitados;
- canal externo de alertas: `local_only` hasta que exista destino y credencial autorizados;
- backup offsite: no configurado; el backup local programado sí permanece activo.

## Operación posterior

El punto de entrada es la skill `mova-fpl-operator`; su primer paso es `mova cockpit --json`. Una
alarma P0/P1 exige `mova triage` y el runbook de la capa afectada. La UI sirve como llamada de
atención humana, pero no reemplaza `ops.db`, los audit logs ni los gates fail-closed.
