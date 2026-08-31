---
type: deployment-evidence
name: "HV1-12B — Destination-bound live alert proof"
created: 2026-08-31
updated: 2026-08-31
tags: [mova, fpl, alerts, idempotency, outbox, readiness]
status: verified-live-fail-closed
---

# HV1-12B — Destination-bound live alert proof

## Problema corregido

El gate de HV1-12 distinguía adaptador y configuración, pero todavía podía considerar listo un
secreto nunca probado. Eso era evidencia insuficiente para autonomía desatendida.

## Contrato

- `mova alerts test --actor --reason --idempotency-key` exige canal configurado;
- sin configuración devuelve `not_configured`, exit 2, cero llamadas y cero jobs;
- crea un evento `alert_channel_probe` P3, no un incidente falso;
- reclama exclusivamente su `outbox_id`; no drena P0/P1 ni eventos vecinos;
- persiste job, audit, outbox, fingerprint de 128 bits y resultado 2xx sin URL/token;
- replay exacto devuelve `reused` y cero llamadas; identidad distinta con la misma clave devuelve
  conflicto;
- un fallo queda auditado y reintentable, pero no se convierte después en pass retroactivo;
- rotar el destino cambia el fingerprint e invalida evidencia anterior;
- CLI/API/Prometheus exponen `live_test` y `mova_alert_channel_live_proven`;
- readiness exige `EXTERNAL_ALERT_CHANNEL_LIVE_PROVEN` además del drill y la configuración;
- el scorecard tiene dimensión `alerting` explícita.

## Evidencia de implementación

- suite completa: 1.167 passed, 1 skipped, 79 deselected;
- 296 pruebas focalizadas de alerts/readiness/scorecard/API/HTTP: pass;
- compileall, `git diff --check` y `docker compose config -q`: pass;
- fixtures prueban no-config, entrega, replay, conflicto, redacción y fallo reintentable.

## Límite

La producción sigue `local_only`; por diseño no se ejecutará un live-ping ni se fabricará un
pass hasta que el owner elija un destino real. Este trabajo no cambia FPL, controles, compliance,
kill switch ni browser writes.

## Evidencia viva

- producción, checkout e imagen alineados en `bc12145`;
- `mova alerts test` bajo `local_only`: exit 2, `not_configured`, `external_calls=0`,
  `runtime_mutated=false`;
- conteo `alert_channel_live_ping` antes/después: 0→0; no fabricó job ni pass;
- CLI/API: `local_only`, `live_test.status=missing`; Prometheus:
  `mova_alert_channel_configured 0` y `mova_alert_channel_live_proven 0`;
- readiness 15/23 pass, 8 pending, 0 blocked; dimensión `alerting` 1/3, pending;
- PostgreSQL `pgimport_e362484df5064088994326a8e08131e3`: 55/55 y paridad pass;
- doctor 22/22, watchdog `ok`, safety `safe_to_wait`; API/PostgreSQL saludables y browser
  apagado;
- controles intactos: `shadow/A0`, kill switch activo, compliance pendiente y browser writes
  deshabilitado;
- backup previo SQLite `/opt/orbital/backups/mova-fpl/20260831T042057Z` y PostgreSQL
  `/opt/orbital/backups/mova-fpl/postgres/20260831T042058Z`;
- backup posterior SQLite `/opt/orbital/backups/mova-fpl/20260831T042313Z` y PostgreSQL
  `/opt/orbital/backups/mova-fpl/postgres/20260831T042314Z`.

La evidencia viva demuestra el fail-closed productivo. El 2xx real sigue deliberadamente
pendiente hasta que exista un destino autorizado; no se sustituye con el fixture hermético.
