---
type: deployment-evidence
name: "HV1-12 — External alert channel foundation"
created: 2026-08-31
updated: 2026-08-31
tags: [mova, fpl, alerts, webhook, security, observability]
status: verified-live
---

# HV1-12 — External alert channel foundation

## Objetivo

Dejar lista la salida P0/P1 fuera del VPS sin inventar proveedor, owner o URL y sin convertir un
ensayo local en falsa evidencia de operación desatendida.

## Contrato implementado

- `mova alerts channel` y `GET /api/v1/alert-channel` exponen `local_only`, `configured` o
  `invalid`; nunca devuelven URL, path ni token;
- secreto Docker `/run/secrets/alert_webhook_config`, deshabilitado por defecto;
- configuración versionada con owner y canal explícitos, HTTPS/443, sin credenciales en
  userinfo, sin redirects y con destino globalmente enrutable;
- payload allowlisted de incidente: identificadores, severidad, título, timestamps, intento,
  owner y canal; otros campos del outbox no salen;
- journald se conserva y un fallo externo vuelve al retry exponencial/dead-letter existente;
- métricas `mova_alert_channel_configured` y `mova_alert_channel_status`;
- readiness separa el rehearsal del adaptador y la configuración efectiva del destino;
- `mova drill alert-channel` comprueba seis invariantes sin DNS, red, DB efímera persistente ni
  mutación del runtime.

## Evidencia de implementación

- suite completa: 1.164 passed, 1 skipped, 79 deselected;
- compileall, `git diff --check` y `docker compose config -q`: pass;
- el contrato HTTP de FPL conserva una sola primitiva GET; la excepción de escritura queda
  acotada al adaptador de alertas y ese módulo no compone endpoints FPL.

## Evidencia viva

- checkout, imagen API/worker y metadata alineados en `ccdfeb8`;
- secreto instalado deshabilitado y sanitizado como `local_only`; no se configuró ni llamó un
  endpoint externo;
- job `job_40c8273d175a4c2e9845c77246e21003`, 6/6 checks, output
  `40b7504e75b15f38cbc9ae6ef1c5792d2b4f48f964d3a7296294c50d922e1509`;
- replay exacto `reused`; misma clave con razón distinta: exit 2 y conflicto sin segundo job;
- API y Prometheus: `local_only`, `mova_alert_channel_configured 0`;
- readiness 15/22 pass, 7 pending, 0 blocked: rehearsal `pass`, destino real `pending`;
- watchdog `ok`, cero delivery pendiente/dead; doctor 22/22 y safety `safe_to_wait`;
- PostgreSQL `pgimport_50b7adfc3865426596218585b9d6a301`: 55/55 y paridad de
  contenido `pass`;
- API y PostgreSQL saludables; browser quedó apagado; controles `shadow/A0`, kill switch activo,
  compliance pendiente y browser writes deshabilitado;
- backup previo SQLite `/opt/orbital/backups/mova-fpl/20260831T040609Z` y PostgreSQL
  `/opt/orbital/backups/mova-fpl/postgres/20260831T040621Z`;
- backup posterior SQLite `/opt/orbital/backups/mova-fpl/20260831T041008Z` y PostgreSQL
  `/opt/orbital/backups/mova-fpl/postgres/20260831T041009Z`.

Durante el rollout se detectó que el wrapper seguía fijado al tag anterior aunque el checkout ya
estaba actualizado. No hubo mutación operativa: los primeros comandos rechazaron la opción antes
de abrir jobs. Se corrigió `MOVA_GIT_SHA`/`MOVA_IMAGE_TAG`, se reconstruyó una imagen canónica y
sólo entonces se ejecutó la evidencia listada.

## Activación pendiente

El deploy instala un secreto deshabilitado y debe reportar `local_only`. Para cerrar el gate hace
falta una decisión humana de destino y owner, provisionar el secreto fuera de Git y ejecutar un
ping vivo con acuse. La URL no debe aparecer en CLI, logs, artifacts, actas ni process args.

El rehearsal no concede A1, no altera kill switch, compliance o browser writes y no toca FPL.
