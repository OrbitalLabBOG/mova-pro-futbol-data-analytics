---
type: workpack
name: "WP-007 — Observabilidad, alertas y runbooks"
created: 2026-08-21
updated: 2026-08-31
tags: [mova, fpl, workpack, observability, runbooks]
status: active-shadow
---

# WP-007 — Observabilidad, alertas y runbooks

## Objetivo

Instrumentar la cadena completa y hacer visibles salud, deadline, fuentes, decisión,
ejecución, modelo e incidentes.

## Dependencias

WP-001/002; instrumentación incremental de WP-003..006.

## Entregables

- logs JSON, endpoint Prometheus-compatible y muestras de salud persistidas;
- propagación de IDs de correlación engine↔browser;
- dashboards Now/Decision/Operations/Learning/Audit;
- alert rules P0–P3, dedup, outbox y acuse;
- runbooks enlazados y post-GW automático;
- retention/cleanup con dry-run.

## Criterios de aceptación

- correlación continua desde tick hasta verify;
- scheduler muerto alerta por last success, no por ausencia manual;
- labels pasan audit de cardinalidad y secretos;
- cada P0/P1 se dispara en test y tiene acuse/cierre;
- dashboard permite saber en <60s si el equipo está seguro;
- telemetría caída no borra ledger ni habilita writes;
- cleanup nunca elimina evidencia decisiva o incidente abierto.

## Estado verificado

Logs JSON, correlation/job IDs, health persistido, Prometheus, doctor/readiness y runbooks ya
operan en shadow. El ledger agentic distingue consumo real, reservas activas y cargos estimados;
además detecta overruns por job y reservas huérfanas sin liberar presupuesto.

HV1-10C hace que “consumo real” signifique ejecuciones físicas, no subjects lógicos. Cada start
liquidado cuenta como uso; los tokens con evidencia son exactos y los hard-kills se estiman por
intento. El reporte evita duplicar la fila lógica de costo, mantiene compatibilidad `legacy` y
expone por separado `charged_tokens` y `charged_estimate_tokens`.

HV1-10D evita descubrir el exceso después de gastar: cada llamada requiere un permiso corto del
host con budget/deadline recalculados. El worker falla 75 sin permiso; receipts v2 cierran el
lifecycle del permiso y las métricas publican estados `preparing|authorized|started|finished|expired`.
Bloqueos repetidos del mismo subject/ordinal/causa reutilizan evidencia y no inflan auditoría.

HV1-10B convirtió los overruns detectados en un lifecycle auditable, idempotente y replicado a
PostgreSQL. El scorecard diferencia `open`, `reviewed_pending` y `closed`; sólo una corrida
posterior equivalente dentro del límite permite resolver. El primer caso real permanece
`reviewed_pending` hasta obtener esa evidencia temporal.

HV1-11 añadió una lectura unificada del grafo agentic por CLI/API/Prometheus. Distingue stages
completos con outcome fail-closed de violaciones causales, y enlaza roles LLM con coordinador,
policy, executor, verifier y reviewer deterministas sin capturar contenido de inferencia.

HV1-01B agregó `mova safety`, `/api/v1/safety` y la tarjeta de seguridad del dashboard; el
resultado reúne deadline, gates, frescura, incidentes y outbox en una sola lectura. P0 y P1 tienen
tests de entrega/fallo, el outbox recupera leases, reintenta y permite acuse auditado. `mova
maintenance cleanup` opera por defecto en dry-run y su allowlist sólo considera `.tmp`,
`.partial` y `.tmp-*`; symlinks y evidencia canónica quedan fuera. El workpack conserva
HV1-12 implementó el adaptador externo sin elegir proveedor: secreto Docker opt-in, HTTPS
credential-free, destino público, payload allowlisted, timeout, error hacia el outbox y estado
sanitizado por CLI/API/Prometheus. `mova drill alert-channel` prueba seis invariantes sin red y
readiness separa `ALERT_CHANNEL_DRILL_PROVEN` de `EXTERNAL_ALERT_CHANNEL_CONFIGURED`.

`active-shadow`: falta elegir owner/destino autorizado, provisionar el secreto y ensayar una
entrega viva con acuse. Hasta entonces el estado correcto es `local_only`; journald conserva la
ruta local y A1+ permanece bloqueado por evidencia pendiente.

HV1-12B corrigió un falso positivo residual: un secreto sintácticamente válido ya no basta para
promoción. `mova alerts test` crea un P3 auditado, reclama sólo su outbox_id y liga el 2xx al
fingerprint de 128 bits del destino. Replay no llama red; identidad distinta colisiona; rotar el
destino invalida la evidencia previa. Readiness agrega `EXTERNAL_ALERT_CHANNEL_LIVE_PROVEN` y el
scorecard agrupa los tres gates bajo `alerting` en vez de `other_readiness`.

HV1-09B endurece el scheduler muerto: `mova watchdog` abre/deduplica P0, intenta la entrega y
devuelve fallo también cuando el sink falla o existe outbox `dead`. `mova alerts retry` ofrece
recuperación explícita y auditada; reconocer un incidente también puede cerrar un evento `dead`
sin confundirlo con delivery. El rehearsal `mova drill resilience` verifica P0→delivery→dedup→
recovery en una base efímera y persiste sólo el job/resultado del ensayo en el ledger real.
