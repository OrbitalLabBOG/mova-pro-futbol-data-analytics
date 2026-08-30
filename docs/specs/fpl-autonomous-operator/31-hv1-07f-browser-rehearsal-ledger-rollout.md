---
type: rollout-evidence
name: "MOVA FPL — HV1-07F browser rehearsal ledger"
created: 2026-08-30
updated: 2026-08-30
tags: [mova, fpl, browser, rehearsal, readiness, audit]
status: verified
---

# HV1-07F — browser rehearsal ledger

## Resultado

Se desplegó un ledger append-only de rehearsals por `cycle_id`, capacidad y versión contractual.
Un pass sólo cuenta una vez por GW; retries, nuevas idempotency keys o evidencia duplicada no
inflan readiness. El importador exige hashes reproducibles, artifacts fuente presentes,
allowlist de campos y `writes_attempted=false`.

SQLite migration 016 y PostgreSQL shadow migration 018 quedaron aplicadas. CLI, API y Prometheus
exponen el ledger. `rehearsal-captaincy-probe` convierte únicamente el probe sanitizado vigente;
no acepta HTML, cookies, storage ni campos desconocidos.

## Evidencia viva

- producción: revisión `7f08fec7`, checkout e imagen alineados;
- suite hermética: 1.026 pass, 1 skip y 79 deselected;
- doctor: 22/22 pass, 0 warn, 0 fail;
- paridad PostgreSQL: 53 tablas, 52 exactas, 1 agregada, 0 fallos;
- rehearsal: `rehearsal_7dc61d9d804a640b7b316eb6`, GW3, captaincy R2;
- probe: sesión autenticada, 15 picks, 15 player controls, 15 switch controls, orden posicional,
  11 player sheets y C/VC conciliados; los 12 checks pasaron;
- retry con la misma llave devolvió `reused=true` y el contador permaneció en 1;
- readiness: captaincy `1/3`; lineup `0/3`; R3 `0/3`;
- browser detenido después del probe; backup posterior `20260830T231433Z`.

El primer intento reveló que el progreso de un build de Compose podía contaminar stdout. Se
corrigió el wrapper para reservar stdout al JSON y enviar toda salida de Compose a stderr antes
de aceptar evidencia.

## Autoridad

No hubo `Save`, transferencia, hit, chip ni cambio de alineación. Producción conserva
`shadow/A0`, `kill_switch=true`, `browser_writes=false` y `compliance=pending`. El rehearsal no
promueve autonomía ni habilita lineup/R3; faltan GWs independientes y una decisión explícita de
autoridad.
