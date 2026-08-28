---
type: runbook
name: "MOVA FPL — contrato del operador"
created: 2026-08-23
updated: 2026-08-28
tags: [mova, fpl, operator, cli, observability, contract]
status: active
---

# Contrato del operador MOVA FPL

HV1-01 expone el runtime mediante comandos versionados. La salida JSON usa
`schema=mova-fpl-operator-v1` y `schema_version=1.0`; los consumidores deben rechazar una major
desconocida y tolerar campos adicionales dentro de la misma versión.

## Ejecución

En el VPS, el wrapper obtiene un probe sanitizado de systemd/Docker y ejecuta el CLI dentro de la
imagen aprobada:

```bash
mova status
mova status --json
mova doctor
mova doctor --json
mova doctor --json --no-network
mova data status
mova data coverage
mova analytics status
mova analytics run
mova strategy status
mova strategy prepare
mova strategy research due
mova strategy research enqueue
mova strategy research import
mova review gw --package /app/decisions/fpl/2026-27/gwNN_closeout.json \
  --actor julian --reason "..." --idempotency-key "..."
```

En desarrollo, `mova` es el console script de `pyproject.toml`. Allí `host.available=false` es
normal si no existe un probe; no se monta el socket Docker ni D-Bus dentro del engine.

`status` siempre es observación y no llama la red. `doctor` tampoco migra ni repara: valida
configuración, SQLite, heartbeat, estado privado, datos/modelos, recursos, backup, servicios,
revisión desplegada, PostgreSQL shadow cuando está configurado, perfil browser y un GET público a FPL. Retorna 1 cuando existe al menos un
`FAIL` requerido; los `WARN` no cambian el exit code.

## Semántica de `status`

| Sección | Contenido |
| --- | --- |
| `runtime` | temporada, team id, SHA, SQLite y controles efectivos |
| `gameweek` | GW, deadline, segundos restantes y fase recalculada |
| `data` | fuentes, data service PostgreSQL, cobertura, team state, FTs, banco, chips y datasets |
| `models` | releases registrados, versión, estado y hash |
| `research` | conteo de señales y conflictos vigentes del ciclo |
| `strategy` | último manifiesto sellado y corridas de research del ciclo |
| `decision` | última decisión sellada, política, estado, xP y fingerprint |
| `decision_envelope` | manifest real, hash, candidato seleccionado y estado `blocked/staged` |
| `execution` | última ejecución browser y evidencia, si existe |
| `operations` | heartbeat, salud, fallos 24 h, incidentes, outbox y migrations |
| `host` | unidades, API, browser y revisiones; `available=false` fuera del wrapper |

`overall_status` es `healthy`, `degraded` o `critical`. Se degrada ante heartbeat, estado privado
o fuente pública vencidos y fallos recientes. Un incidente P0/P1 abierto lo vuelve crítico. Los
motivos se enumeran en `status_reasons`, sin obligar al consumidor a inferirlos de texto humano.

`gameweek.readiness` es independiente de la salud técnica. Vale `preliminary` cuando la jornada
anterior todavía no está `finished` y `data_checked`; en ese estado se puede investigar y comparar
escenarios, pero no promover chips ni transferencias. `prior_unstarted_fixtures` hace visible si
incluso quedan partidos por comenzar.

Las actas muestran por separado todos los jugadores que salen y entran y expresan el coste de hits
en puntos. Una cifra como `1 hit` nunca debe confundirse con `−1 punto`: bajo las reglas vigentes
equivale a `−4 puntos`.

## Semántica de `doctor`

Cada check tiene:

```json
{
  "name": "scheduler_heartbeat",
  "status": "PASS",
  "required": true,
  "summary": "worker heartbeat is fresh",
  "detail": {}
}
```

- `PASS`: evidencia observada cumple el contrato.
- `WARN`: componente opcional, check omitido o condición que requiere atención sin bloquear.
- `FAIL`: contrato incumplido. Si `required=true`, el comando termina con código 1.

Los schemas completos están en [status v1](../contracts/operator-status-v1.schema.json) y
[doctor v1](../contracts/operator-doctor-v1.schema.json).

## Tiempos del collector

Cada refresh público registra `fetch_fpl_bootstrap_events` y `fetch_fpl_fixtures` como pasos
separados. El primero contiene el resumen de eventos y el estado dinámico de jugadores; el
segundo contiene el calendario y estado de los partidos. Ambos conservan duración, tamaño y
SHA-256 sin guardar el payload en logs.

```bash
curl -s 'http://127.0.0.1:8787/api/v1/steps?limit=50' | python -m json.tool
curl -s http://127.0.0.1:8787/metrics | grep -E '^mova_(tick_last|collector_step).*duration'
```

`mova_tick_last_duration_seconds` mide el wall time del último tick y
`mova_collector_step_duration_ms{step,status}` conserva los pasos de la última corrida que sí
refrescó, aunque ticks posteriores se omitan por cadencia. Permite separar red, sellado y modelos. Los
mismos pasos salen en journald como JSON con `job_id`, `correlation_id`, `duration_ms` y detalle
sanitizado.

El servicio ampliado FPL/odds/WhoScored se opera con `mova collect` y expone salud en
`data.service`, `/api/v1/data` y métricas `mova_data_*`. Su contrato y diagnóstico están en el
[runbook del data service](data-service.md).

La capa de modelo se opera exclusivamente con `mova analytics`: `project` sella la última
proyección causal antes del deadline, `reconcile` evalúa GWs oficiales con `data_checked`, y
`run` hace ambas de forma idempotente. El contrato read-only vive en `/api/v1/analytics`,
`/api/v1/analytics/scorecards`, `/api/v1/analytics/gw/<GW>` y métricas `mova_model_*`.
Interpretación, umbrales y recuperación están en el
[runbook analítico](analytics-service.md).

El cierre estratégico usa `mova review gw` después de `finished + data_checked`. Exige package,
actor, razón y clave idempotente; persiste settlement/review en el writer SQLite y exporta la
atribución a la traza. Si no existió batch predeadline, el resultado es retrospectivo y no cuenta
como scorecard causal.

El contexto pre-deadline usa `mova strategy`: `plan` activa una revisión explícita del plan
de temporada; `prepare` sella fuentes, team state, proyección, plan y research en un
`CycleManifest`; `research enqueue` publica una solicitud sin secretos; `research import`
valida el brief y lo incorpora. El worker Codex no accede a DB, navegador, repo ni credenciales
de datos. Contrato y recuperación en
[contexto estratégico](strategic-research.md).

El lifecycle shadow de HV1-06A genera tres candidatos y un validador determinista. Sus endpoints
read-only son `/api/v1/decision-envelopes`, `/api/v1/decision-candidates` y
`/api/v1/decision-checks`; Prometheus expone `mova_decision_envelope_status` y
`mova_decision_blocking_checks`. Un envelope `blocked` es un resultado seguro esperado, no un
fallo del tick. Contrato, checks y recuperación en
[lifecycle de decisión](decision-lifecycle.md).

## Probe del host

`deploy/bin/host-probe.py` registra exclusivamente estados de unidades, salud de API/PostgreSQL,
presencia del perfil browser, presencia booleana del auth/cola de research y revisiones de
checkout/imagen. No lee env, cookies, HTML, logs, argumentos de
procesos ni secretos. Su salida atómica vive en
`/var/lib/mova-fpl/runtime/host-probe.json`, es consumida como solo lectura por el engine y vence a
los diez minutos.

El wrapper `deploy/bin/mova` actualiza ese probe para `status` y `doctor`. Si falla un check del
host, diagnosticar desde el host; no ampliar privilegios del contenedor.

## Rollout y rollback

Para desplegar el control plane se construye una imagen con el mismo SHA del checkout, se ejecutan
`status/doctor`, se reemplaza el API y se vuelven a ejecutar ambos comandos. La DB no cambia de
schema salvo una migración versionada. Ante regresión de HV1-06A, restaurar checkout e imagen
anterior; la migración 007 es aditiva y los envelopes nuevos pueden permanecer como evidencia.
