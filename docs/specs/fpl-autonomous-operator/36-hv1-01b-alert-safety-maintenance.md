---
type: deployment-evidence
name: "HV1-01B — Alertas, safety summary y mantenimiento"
created: 2026-08-31
updated: 2026-08-31
tags: [mova, fpl, observability, alerts, maintenance]
status: verified-live
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

## Rollout vivo

El 31 de agosto de 2026 se promovió el commit de código `203f4fe` al VPS después de backup
predeploy. El primer intento de smoke reveló que Compose había construido `local` mientras el
wrapper conservaba el tag `7a946ee`; se corrigió sin ocultarlo, alineando explícitamente
`MOVA_IMAGE_TAG`, `MOVA_GIT_SHA`, checkout e imagen antes de certificar.

Evidencia final:

- checkout e imagen: `203f4fe`, check `deployment_revision=PASS`;
- Docker build del engine y smoke de `safety`, `alerts status` y cleanup: pass;
- doctor: 22 pass, 0 warn, 0 fail;
- readiness: 9 pass, 6 pending temporales, 0 blocked; nivel técnico A0;
- `GET /api/v1/safety`: `safe_to_wait`, cero incidentes abiertos y cero entregas pendientes;
- dos eventos históricos —P1 tick y P2 collector— entregados a journald, un intento cada uno,
  cero fallos y cero `dead`; no se marcaron falsamente como acuse humano;
- watchdog real: heartbeat `ok`, dispatcher integrado, cero eventos vencidos tras el drain;
- cleanup vivo dry-run: cero candidatos y cero bytes, sin mutación;
- import PostgreSQL `pgimport_5483d778101445f5820a29095063a157`: 54/54 tablas, paridad
  `pass`, cero fallos;
- backup postdeploy: `/opt/orbital/backups/mova-fpl/20260831T011303Z`.

No cambió ningún control ni se operó el navegador. El canal sigue siendo journald local; una
notificación externa y su owner permanecen como decisión separada antes de autonomía desatendida.
