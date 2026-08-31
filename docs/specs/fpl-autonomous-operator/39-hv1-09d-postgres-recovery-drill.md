---
type: deployment-evidence
name: "HV1-09D — PostgreSQL recovery drill"
created: 2026-08-31
updated: 2026-08-31
tags: [mova, fpl, chaos, postgres, recovery, idempotency]
status: implemented-pending-live-rollout
---

# HV1-09D — PostgreSQL recovery drill

## Objetivo

Probar una caída real, acotada y reversible de PostgreSQL sin perder continuidad del control
plane SQLite, disponibilidad del API ni estado privado FPL. Este escenario cierra la porción DB
del chaos básico de WP-008; no cambia el writer del harness ni cuenta como un ciclo de GW.

## Contrato

`deploy/bin/postgres-recovery-drill.sh` se ejecuta únicamente desde el host y:

1. toma un lock propio y los cinco locks de servicios que pueden escribir SQLite/PostgreSQL;
2. consulta la identidad `(scenario, actor, reason, idempotency_key)` antes de cualquier stop;
3. verifica PostgreSQL, paridad 54/54, API y fingerprint del último team state;
4. instala un trap de recuperación y detiene exclusivamente `postgres`;
5. exige que un cliente real no pueda conectar, mientras API y SQLite siguen sanos;
6. levanta la misma imagen, espera `pg_isready`, revalida paridad y compara fingerprints;
7. importa evidencia allowlisted con ocho checks y `fpl_state_mutated=false`.

El importador separa las claves por escenario, rechaza sustitución API/DB, checks extra o
faltantes, revisión distinta, downtime mayor a 180 s y cualquier cambio en el hash del estado
privado. Un job fallido no se presenta como replay exitoso. El gate máquina
`HOST_RECOVERY_DRILLS_PROVEN` exige tanto `api_recovery` como `postgres_recovery` aprobados antes
de considerar A1+.

## Seguridad y límites

El drill no apaga timers ni mata procesos: si cualquier writer está activo, el lock devuelve 75 y
la prueba se difiere. No toca browser, controles, equipo, modelos, credenciales, volumen
PostgreSQL ni configuración. El trap recrea el servicio ante toda salida intermedia. Sigue
pendiente probar snapshot inválido, browser/DOM, save ambiguo, combinaciones y reboot completo.

## Evidencia previa al rollout

- validación dirigida: escenarios API/DB, sustitución, fingerprints, timing e identidad;
- suite completa y smoke Docker se anexarán después de cerrar el commit candidato;
- sintaxis shell, `compileall` y `git diff --check`: pass.

