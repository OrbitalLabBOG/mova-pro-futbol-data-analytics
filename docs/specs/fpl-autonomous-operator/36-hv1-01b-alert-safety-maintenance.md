---
type: deployment-evidence
name: "HV1-01B — Alertas, safety summary y mantenimiento"
created: 2026-08-31
updated: 2026-08-31
tags: [mova, fpl, observability, alerts, maintenance]
status: tested-pending-live-rollout
---

# HV1-01B — Alertas, safety summary y mantenimiento

## Alcance

Cerrar los huecos no temporales de WP-002/WP-007 sin modificar autoridad, browser ni decisiones
deportivas. La iteración conserva `shadow/A0`, `kill_switch=true`, compliance pendiente y writes
del browser deshabilitados.

## Contratos implementados

- `mova alerts status|dispatch|acknowledge`: outbox sanitizado, claim con lease, entrega local a
  journald, retry exponencial, límite de cinco intentos y acuse idempotente/auditado.
- El watchdog ejecuta el dispatcher después de validar el heartbeat. Una caída después del claim
  no pierde el evento: el lease vencido vuelve a ser reclamable.
- `mova safety` y `GET /api/v1/safety`: respuesta `safe_to_wait`, `attention_required` o `unsafe`
  con deadline, controles, frescura e incidentes; no concede autoridad.
- `mova maintenance cleanup`: dry-run por defecto. La aplicación requiere actor, razón e
  idempotency key y sólo elimina formatos explícitamente transitorios dentro de artifact root.

## Seguridad

La entrega ocurre fuera de la transacción SQLite. Logs y status omiten `payload_json`; el sink
sólo recibe IDs, severidad, título y código de evento. Symlinks, JSON, Markdown, manifests,
decisiones, incidentes y backups no son candidatos de cleanup. El canal actual es journald local:
una ruta externa sigue siendo una decisión operativa separada.

## Evidencia prevista de rollout

Antes de cambiar este acta a `verified-live` deben pasar suite completa, build/smoke Docker,
`mova doctor --json`, `mova safety`, dispatch vivo del outbox, paridad PostgreSQL y backup. Los
resultados exactos se anexarán después del despliegue; no se anticipan aquí.

## Verificación local

- suite completa: `1074 passed, 1 skipped, 79 deselected`;
- pruebas P0/P1: delivery, retry sin filtrar el error, lease recovery, ack idempotente y audit;
- cleanup: dry-run, allowlist, preservación de JSON y rechazo de symlinks;
- `compileall`, `git diff --check` y sintaxis de scripts shell: pass;
- build Docker local: no ejecutable porque ese host no tiene el plugin `docker-buildx`; se difiere
  al builder provisionado del VPS y no se considera evidencia de éxito.
