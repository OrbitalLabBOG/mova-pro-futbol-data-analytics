---
type: deployment-evidence
name: "HV1-09C — API recovery drill"
created: 2026-08-31
updated: 2026-08-31
tags: [mova, fpl, chaos, api, recovery, idempotency]
status: implemented-pending-live-rollout
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

## Evidencia previa al rollout

- pruebas dirigidas: 21 pass;
- suite completa: `1098 passed, 1 skipped, 79 deselected`;
- import allowlisted, rechazo de revision/status/checks/path/downtime inválidos y consumo atómico
  del inbox cubiertos;
- `compileall`, sintaxis shell y `git diff --check`: pass.

Suite completa y evidencia viva se anexarán sólo tras el deploy y la recuperación observada.
