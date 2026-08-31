---
type: deployment-evidence
name: "HV1-09L — Reboot recovery gate"
created: 2026-08-31
updated: 2026-08-31
tags: [mova, fpl, reboot, recovery, systemd, idempotency, readiness]
status: verified-live-pending-drill
---

# HV1-09L — Reboot recovery gate

## Problema corregido

La spec exigía un reboot real para G2, pero `HOST_RECOVERY_DRILLS_PROVEN` pasaba con cuatro caídas
de servicios dentro del mismo boot. Esa evidencia prueba recuperación de componentes, no el orden
de arranque del host, timers persistentes ni reanudación del scheduler. Readiness podía por tanto
sobreestimar la madurez.

## Contrato desplegado

El gate exige ahora cinco escenarios: `api_recovery`, `postgres_recovery`, `browser_recovery`,
`combined_recovery` y `reboot_recovery`. Las cuatro evidencias históricas permanecen válidas, pero
el conjunto queda `incomplete` 4/5.

La fase de preparación:

1. consulta idempotencia antes de mutar;
2. exige API/PostgreSQL y ocho timers activos;
3. exige controles exactos shadow/A0 fail-closed;
4. crea backups forzados SQLite/artefactos y PostgreSQL;
5. sella boot ID, revisión, último tick, controles y fingerprint privado;
6. publica un pending atómico con TTL de diez minutos;
7. termina declarando `reboot_executed=false`.

La fase boot-time sólo corre si existe pending. Exige boot ID distinto y que el reboot haya
iniciado dentro del TTL; después verifica API, PostgreSQL, ocho timers, un tick nuevo, quick-check,
paridad, revisión, controles, team state e unicidad de idempotency keys. La evidencia contiene once
checks allowlisted, `fpl_state_mutated=false` y se importa por el contrato host existente. Un
pending vencido se archiva sin crear job ni pass.

## Verificación

- suite focal: 45 passed;
- suite completa: 1.201 passed, 1 skipped, 79 deselected;
- Bash syntax, bytecode y diff checks válidos;
- escenario alterado, timeout >1.200 s, fingerprint distinto y checks parciales rechazados;
- prueba explícita: cuatro escenarios producen `incomplete`, 4/5;
- commit funcional, checkout e imagen viva: `2c83df9`;
- unidad renderizada y validada por systemd, enabled e inactiva sin pending;
- `host-status reboot_recovery`: `due`, exit 75, sin crear job;
- doctor 23/23, watchdog `ok`, safety `safe_to_wait`;
- readiness vivo: 14 pass, 9 pending, 0 blocked; host recovery 4/5;
- PostgreSQL 24 con paridad 57/57;
- backup pre SQLite `/opt/orbital/backups/mova-fpl/20260831T061527Z` y PostgreSQL
  `/opt/orbital/backups/mova-fpl/postgres/20260831T061457Z`;
- backup post SQLite `/opt/orbital/backups/mova-fpl/20260831T061644Z` y PostgreSQL
  `/opt/orbital/backups/mova-fpl/postgres/20260831T061645Z`.

## Límite deliberado

No se creó pending ni se reinició el VPS. El reboot afecta otros servicios del host y requiere
autorización explícita separada. Hasta ejecutarlo, el estado correcto es pending; este rollout
mejora la veracidad y deja lista la prueba, no fabrica su resultado. A0, kill switch y browser
writes permanecen intactos.
