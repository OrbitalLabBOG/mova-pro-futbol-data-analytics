---
type: rollout-evidence
name: "MOVA FPL — HV1-02B reversible PostgreSQL read cutover"
created: 2026-08-30
updated: 2026-08-30
tags: [mova, fpl, postgres, cutover, rollback, audit]
status: verified
---

# HV1-02B — cutover/rollback reversible de lectura

## Resultado

Se desplegó un drill idempotente que prueba PostgreSQL como reader candidato sobre el último
snapshot SQLite importado y verificado. El selector es finito y local al proceso; siempre ejecuta
`sqlite_baseline → postgres_candidate → sqlite_rollback` y no puede modificar la configuración
del writer. Drift o indisponibilidad del candidato fallan cerrado.

El drill compara conteo y SHA-256 para siete contratos críticos: controles, ciclo, estado del
equipo, research, decision envelope, execution plan y rehearsals browser. Persiste job, audit y
artefacto sellado; API y Prometheus exponen su estado sin credenciales.

## Evidencia viva

- producción: revisión `18d6080d`, checkout e imagen alineados y saludables;
- suite hermética: 1.040 pass, 1 skip y 79 deselected;
- doctor: 22/22 pass, 0 warn, 0 fail;
- drill: `pgcutover_3ccf783c3444491aa5acee0a7b69475b`;
- job: `job_84dd9d545eb34b6ba85b7dce81722820`;
- import fuente: `pgimport_a052578acf384455b7e0bcf049b19f50`;
- contratos del drill: 7/7 pass, rollback verificado y writer no mutado;
- artefacto SHA-256: `99c38eb6d9070593d7f1eb01055d371831a816a1b4e8f0fd9c67f4e7aa002768`;
- contenido SHA-256: `fb19218a8ccfa62dc46f490c987601a4bb739ccfff4195778b1f360df060451a`;
- retry exacto: devolvió `reused` con el mismo job y artefacto;
- Prometheus: lifecycle `completed=1` y `rollback_verified=1`;
- réplica posterior: `pgimport_d1c7beb3dc28453a89c8353999de4411`, 53/53 tablas,
  52 exactas, 1 agregada y 0 fallos;
- readiness: 8 pass, 6 pending y 0 blocked;
- backups PostgreSQL antes/después: `20260830T232941Z` y `20260830T233142Z`.

## Autoridad y pendientes

El writer continúa siendo SQLite. Producción conserva `shadow/A0`, `kill_switch=true`,
`browser_writes=false` y `compliance=pending`. Este corte satisface el ensayo reversible del
read-path, pero no autoriza dual-write ni promoción del writer. HV1-02 permanece abierto hasta
acumular tres GWs independientes, disponer de backup cifrado off-host y roles LOGIN separados,
y recibir aprobación explícita para cualquier cambio de writer.
