---
type: deployment-evidence
name: "HV1-12B — Destination-bound live alert proof"
created: 2026-08-31
updated: 2026-08-31
tags: [mova, fpl, alerts, idempotency, outbox, readiness]
status: implementation-verified
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
