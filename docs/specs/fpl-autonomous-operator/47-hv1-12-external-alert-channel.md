---
type: deployment-evidence
name: "HV1-12 — External alert channel foundation"
created: 2026-08-31
updated: 2026-08-31
tags: [mova, fpl, alerts, webhook, security, observability]
status: implementation-verified
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

## Activación pendiente

El deploy instala un secreto deshabilitado y debe reportar `local_only`. Para cerrar el gate hace
falta una decisión humana de destino y owner, provisionar el secreto fuera de Git y ejecutar un
ping vivo con acuse. La URL no debe aparecer en CLI, logs, artifacts, actas ni process args.

El rehearsal no concede A1, no altera kill switch, compliance o browser writes y no toca FPL.
