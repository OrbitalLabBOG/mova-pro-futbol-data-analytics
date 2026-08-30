---
type: rollout-evidence
name: "MOVA FPL — HV1-02C PostgreSQL runtime role separation"
created: 2026-08-30
updated: 2026-08-30
tags: [mova, fpl, postgres, security, least-privilege, audit]
status: verified
---

# HV1-02C — identidades PostgreSQL runtime separadas

## Resultado

El owner quedó reservado a migraciones/imports y se provisionaron dos identidades efectivas con
secretos Docker distintos. `mova_app_runtime` hereda `SELECT/INSERT/UPDATE`, sin `DELETE/TEMP`;
`mova_readonly_runtime` hereda únicamente `SELECT`, carece de `TEMP` y abre transacciones read-only
por defecto. Ambas tienen límites de conexión y timeouts defensivos.

La provisión exige actor, razón y llave idempotente, prueba conexiones y privilegios reales y
sella un artifact sin material secreto. El drill de cutover fue repetido usando readonly como
reader candidato. Status, doctor, dashboard, readiness y Prometheus propagan la matriz sanitizada.

## Evidencia viva

- revisión probada en producción: `2a6d6a23`; checkout, imagen y health alineados;
- PostgreSQL migration 019 aplicada; 19/19 migraciones vigentes;
- provisión: `pgroles_bb4e6cbc7bab4e89ab8acb36465ceade`;
- job exitoso: `job_1ec82a88121b40049fa2f61b2cd71adb`;
- app: select/insert/update `true`; delete/temp `false`;
- readonly: select `true`; insert/update/delete/temp `false`; default read-only `on`;
- tres rutas de secreto distintas; ninguna contraseña en job, artifact, API o logs;
- retry de provisión: `reused` con el mismo job y artifact;
- artifact SHA-256: `c36d4eb7c0bdd7b8329f2537311459d0a6021c800e6dc598826a9959ee8f6415`;
- drill readonly: `pgcutover_fde81d69a7bd4caf8c6df546d7a82515`, 7/7 checks,
  rollback verificado y writer no mutado;
- import posterior: `pgimport_d7ef521be37042ffa8d63c8741769f74`, 53/53 tablas,
  52 exactas, 1 agregada, 0 fallos;
- restore drill posterior: `20260830T234924Z`, restauró en base temporal y la eliminó;
- suite hermética final: 1.052 pass, 1 skip y 79 deselected;
- doctor: 22/22 pass; readiness: 9 pass, 6 pending, 0 blocked;
- Prometheus: `mova_postgres_role_separation_status{status="pass"}=1`.

El primer intento de rotación falló porque PostgreSQL no admite un bind parameter en
`ALTER ROLE ... PASSWORD`. El job fallido permanece en auditoría. La corrección usa composición
segura de identificador/literal; una ejecución posterior del mismo tipo pasó. Health distingue
fallas activas de recuperadas sin borrar historia.

## Autoridad y pendientes

El writer continúa en SQLite. Producción conserva `shadow/A0`, kill switch activo, browser writes
apagado y compliance pendiente. HV1-02 sigue abierto por tres GWs independientes, backup cifrado
off-host y aprobación explícita del cambio de writer. Q-04 exige que el usuario autorice el destino
off-host; este rollout no subió datos a servicios externos.
