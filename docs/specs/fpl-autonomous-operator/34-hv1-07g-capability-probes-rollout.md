---
type: rollout-evidence
name: "MOVA FPL — HV1-07G capability probes"
created: 2026-08-30
updated: 2026-08-30
tags: [mova, fpl, browser, rehearsal, lineup, transfers, safety]
status: verified-shadow
---

# HV1-07G — probes vivos de lineup y R3

## Resultado

El ledger browser ya no depende de redactar evidencia manual para XI/banca o R3. El comando
`mova execute rehearsal-capability-probe` admite únicamente `lineup|r3`, limita la fuente al
artifact root y deriva un artifact sellado desde dos contratos DOM allowlisted.

- Lineup exige los quince picks, controles de jugador y switch, posiciones `1..15`, índices
  `0..14`, elementos únicos, nombres conciliados y orden visual exacto.
- R3 exige quince picks, al menos un target explícito, metadata completa de cada target,
  búsqueda, controles de salida, `Wildcard Play`, `Free Hit Play` y `Make Transfers`.
- Ambos rechazan campos extra, team_id incorrecto, timestamps futuros, probes fallidos, fuentes
  fuera del root y hashes físicos alterados.
- El resultado siempre declara `writes_attempted=false`; el comando no contiene primitivas CDP,
  clicks ni promoción de controles.

## Evidencia viva GW3

| Evidencia | Resultado |
| --- | --- |
| revisión productiva | `9b06eef`, checkout/API/browser alineados |
| suite hermética | `1056 passed`, `1 skipped`, `79 deselected` |
| doctor | 22/22 pass, 0 warn, 0 fail |
| lineup | `rehearsal_c2b977813248bc80d191cc12`, 7/7 checks |
| R3 | `rehearsal_663fa709e6525a523105f715`, 12/12 checks |
| captaincy previa | `rehearsal_7dc61d9d804a640b7b316eb6`, 12/12 checks |
| idempotencia | ambos replays devolvieron `reused=true` y conservaron `1/3` |
| conciliación | squad pick-team y transfers idéntico, 15/15 elementos |
| PostgreSQL shadow | import `pgimport_5c5c9871570449f696978859824ee101`; 3/3 rehearsals exactos |
| paridad total | 53 checks, 52 exactos, 1 agregado, 0 fallos |
| backup pre/post | `20260831T000436Z` / `20260831T000658Z` |
| navegador al cierre | detenido; noVNC y CDP no publicados |

El probe R3 usó los doce targets del último plan sellado, pero no pulsó `Remove player`,
`Add player`, `Make Transfers`, chips ni confirmación. El probe lineup reutilizó la captura viva
pick-team y no ejecutó swaps ni `Save`. El estado de squad observado fue idéntico antes y después
entre ambas superficies.

## Autoridad y pendiente

Este corte eleva evidencia, no autoridad. Readiness queda en 9 pass, 6 pending, 0 blocked y
elegibilidad técnica A0. Producción conserva `shadow/A0`, `kill_switch=true`,
`browser_writes=false`, `compliance=pending`; lineup/R3 siguen con
`host_entrypoint_enabled=false`.

Faltan dos GWs independientes por capacidad. Además, aun con `3/3`, la promoción requerirá una
decisión explícita y evidencia separada del flujo material: swaps/commit para lineup y staging,
review y confirmación apply-once para R3. Ningún contador activa esos caminos automáticamente.
