---
type: deployment-evidence
name: "HV1-09D — PostgreSQL recovery drill"
created: 2026-08-31
updated: 2026-08-31
tags: [mova, fpl, chaos, postgres, recovery, idempotency]
status: verified-live
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

## Evidencia verificada

- candidato del drill `237357b`; hardening de conflicto JSON desplegado en `a78ff16`;
- suite completa: `1106 passed, 1 skipped, 79 deselected`; validación dirigida 24 pass;
- sintaxis shell, Compose, `compileall` y `git diff --check`: pass;
- backup previo: job `job_a224ad9881a747ff9e1d28074a4a1a05`, ruta
  `/opt/orbital/backups/mova-fpl/20260831T020006Z`;
- ensayo vivo: job `job_48f63b5ab68a4fad81045e5070b69b7b`, downtime 7 s, ocho de
  ocho checks y artefacto SHA-256
  `5f0c026a4bdf50fafbb2d470b54932f17aeacd699070db8b56377f495c3d56e1`;
- el contenedor conservó ID e imagen; API respondió durante la caída; fingerprints privado
  antes/después: `078c12ce4fd35b966ef76bf1829d50627fd4f946453de6f66c20c4f587e13b85`;
- replay: mismo job y `StartedAt` sin cambios; identidad distinta: `status=conflict`, exit 2 y
  ningún restart;
- import posterior `pgimport_39e3959ffdbd462b8a0eff1a2a775139`: 54/54; read parity pass;
- `mova doctor`: 22 pass, 0 warn, 0 fail; watchdog activo; `mova safety`: `safe_to_wait`;
- readiness: 11 pass, 6 pending, 0 blocked sobre 17; `HOST_RECOVERY_DRILLS_PROVEN=pass`,
  elegibilidad conservada en A0;
- backup posterior: job `job_f4244f0acefd4cd39154357db7de4bcc`, ruta
  `/opt/orbital/backups/mova-fpl/20260831T020448Z`.
