---
type: deployment-evidence
name: "HV1-09C — API recovery drill"
created: 2026-08-31
updated: 2026-08-31
tags: [mova, fpl, chaos, api, recovery, idempotency]
status: verified-live
---

# HV1-09C — API recovery drill

## Objetivo

Probar una caída real y reversible del API local sin detener workers, PostgreSQL, timers, browser
ni modificar FPL. El escenario cierra una parte no temporal de WP-008 y no cuenta como GW.

## Diseño

`deploy/bin/api-recovery-drill.sh`:

1. carga la revisión/tag aprobados y exige `/readyz` sano;
2. toma un `flock` host y consulta la clave antes de cualquier stop; un replay completado sale
   `reused` sin repetir la caída;
3. instala un trap que recrea el API ante cualquier salida;
4. detiene sólo `api` y prueba que el endpoint sea inalcanzable;
5. recrea el mismo servicio, espera readiness y verifica revisión e integridad SQLite;
6. produce evidencia JSON sin logs, env, secretos, HTML ni payloads privados;
7. la importa con actor, razón e idempotency key.

El importador acepta exclusivamente `api_recovery`, cinco checks exactos, timestamps con zona,
downtime ≤120 s, revisión igual al runtime y `fpl_state_mutated=false`. El archivo debe estar en
`host-drills/inbox`, se canonicaliza por SHA-256, se mueve a `imported/` y el job persiste métricas.

## Límites

El drill sí reinicia un contenedor de observabilidad; por eso es host-only y explícito. No toca
controles, equipo, sesión, collector o modelos. No prueba caída de DB, browser/DOM, save ambiguo o
reboot completo, que permanecen abiertos.

## Evidencia de verificación

- pruebas dirigidas: 21 pass;
- suite completa: `1098 passed, 1 skipped, 79 deselected`;
- import allowlisted, rechazo de revision/status/checks/path/downtime inválidos y consumo atómico
  del inbox cubiertos;
- `compileall`, sintaxis shell y `git diff --check`: pass.
- revisión desplegada y verificada en checkout, imagen y etiqueta OCI: `8f7b2d1`;
- primer ensayo sobre `f5dcda0`: la API se recuperó, pero el import rechazó escribir en
  `host-drills/imported` por ownership incorrecto. El defecto quedó corregido antes del segundo
  ensayo con un preflight reproducible de ambos directorios y prueba de regresión;
- ensayo vivo aprobado: job `job_2b0f255871c74ee3852752c4d6f61678`, downtime 7 s, cinco de
  cinco checks, `fpl_state_mutated=false` y artefacto SHA-256
  `808084dd0ee2793f2c7420386803853b34600b7aa8fb76ff3428917b173afc9d`;
- replay con la misma idempotency key: `reused=true`, mismo job y `StartedAt` del contenedor
  sin cambios; no se repitió la caída;
- `mova doctor`: 22 pass, 0 warn, 0 fail; watchdog timer activo; `mova safety`:
  `safe_to_wait`, sin alertas abiertas;
- readiness: 10 pass, 6 pending, 0 blocked; permanece A0/shadow por gates explícitos y
  temporales, no por fallo de este escenario;
- PostgreSQL: import `pgimport_1b1954e2184a4b628b271c403a36832c`, paridad 54/54;
- backup posterior: job `job_6698226b2b0547bb9a273112c5c8bb7e`, ruta
  `/opt/orbital/backups/mova-fpl/20260831T014635Z`.

El archivo del primer intento permanece en el inbox como evidencia diagnóstica no importada. No
cuenta como prueba aprobada y no altera el único job canónico de este escenario.
