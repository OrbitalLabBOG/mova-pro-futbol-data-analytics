---
type: deployment-evidence
name: "HV1-09I — Independent agent queue watchdog"
created: 2026-08-31
updated: 2026-08-31
tags: [mova, fpl, agents, watchdog, observability, incidents, cost]
status: verified-live
---

# HV1-09I — Independent agent queue watchdog

## Problema cerrado

HV1-06D evitó nuevos replays de requests huérfanos, pero el incidente original demostró que
`doctor` y `watchdog` podían permanecer verdes mientras Codex se ejecutaba repetidamente. La
prevención y la detección compartían demasiado destino: si el importador fallaba, no existía un
sensor independiente.

## Contrato

`assess_agent_queue` observa `inbox/` directamente y valida, sin leer ni exponer el prompt:

- path regular y no symlink;
- nombre e ID allowlisted;
- tamaño máximo de 1 MiB;
- JSON objeto, schema e identidad coherentes;
- fila durable en `research_runs` o `decision_deliberations` después de 60 segundos;
- estado todavía activo;
- ausencia de resultados archivados o tombstones en cuarentena;
- progreso de requests registrados sin resultado antes de 2.100 segundos.

Una violación produce únicamente `request_id`, motivo y edad sanitizados. El watchdog abre un P1
`Agent queue integrity unhealthy` mediante `open_incident_once`, entrega por el outbox vigente y
devuelve `degraded`. La siguiente corrida sana resuelve la misma causalidad. El watchdog nunca
mueve, repara ni borra archivos: su independencia es de observación.

Superficies nuevas:

- `mova watchdog` incluye `agent_queue` y resolución por dominio;
- `mova doctor` añade `agent_queue_integrity` como PASS/WARN;
- `GET /api/v1/agent-queue` responde 200 sano y 503 ante anomalía;
- `mova_agent_queue_healthy`, `mova_agent_queue_requests` y
  `mova_agent_queue_anomalies`;
- `drill resilience` amplía su contrato de 6 a 10 checks con P1/delivery/dedupe/recovery.

## Verificación

- suite completa: 1.173 passed, 1 skipped, 79 deselected;
- 42 pruebas focalizadas de watchdog, API, doctor, alerts, readiness y scorecard: pass;
- compileall, `node --check`, `docker compose config` y `git diff --check`: pass;
- producción `8bc74bd`, checkout, env, engine y research alineados;
- cola viva: `requests=0`, `anomalies=0`, `healthy=true`;
- API 200 y métricas `healthy=1`, `requests=0`, `anomalies=0`;
- watchdog vivo `ok`, cero entregas pendientes y cero incidentes abiertos;
- doctor 23/23; safety `safe_to_wait`;
- drill `job_7f31084fb4de47b0815027b1485acb14`: 10/10,
  `output_sha256=0457d5e15c477cfcb10ec99018f3bb049fb436e85a351322c7cfdbf8de563599`,
  `runtime_mutated=false`;
- replay exacto: `reused`; misma clave con otra identidad: `conflict`, exit 2;
- readiness 15/23, 8 pending, 0 blocked;
- PostgreSQL `pgimport_71a03e9895674f499cdfb33b5a76b12c`: 55/55 y paridad pass;
- backup previo SQLite `/opt/orbital/backups/mova-fpl/20260831T045057Z` y PostgreSQL
  `/opt/orbital/backups/mova-fpl/postgres/20260831T045057Z`;
- backup posterior SQLite `/opt/orbital/backups/mova-fpl/20260831T045405Z` y PostgreSQL
  `/opt/orbital/backups/mova-fpl/postgres/20260831T045406Z`.

## Autoridad y límites

No se abrió un incidente sintético en producción: el P1 se probó en una base y cola efímeras. El
destino externo continúa `local_only`; por tanto una anomalía real queda durable en SQLite,
journald y métricas, pero no tiene aún entrega fuera del VPS. La corrección no toca FPL y conserva
`shadow/A0`, kill switch activo, compliance pendiente y browser writes deshabilitado.
