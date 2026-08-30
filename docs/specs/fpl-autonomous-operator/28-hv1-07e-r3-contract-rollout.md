---
type: evidence
name: "HV1-07E — contrato R3 fail-closed"
created: 2026-08-30
updated: 2026-08-30
tags: [mova, fpl, autonomy, browser, transfers, chips, safety]
status: deployed-shadow
---

# HV1-07E — contrato R3 fail-closed

## Resultado

Se implementó y desplegó el contrato determinista para transferencias, hits y poderes sin crear
un entrypoint capaz de escribir en FPL. Producción permanece `shadow/A0`, `kill_switch=true`,
`browser_writes=false` y `compliance=pending`.

El corte entrega:

- command bundle R3 ligado a plan, fingerprints y lifecycle apply-once;
- compilador de UI que revalida plantilla, posiciones, targets, precios, banco, hits y chip;
- probe autenticado `/en/transfers` read-only, limitado a IDs numéricos y salida allowlisted;
- driver host tipado con review exacto, una confirmación irreversible máxima y sin retry;
- herramienta `browser-r3-driver.py --validate-contract-only`, sin browser ni subprocess;
- capability R3 `implemented`, entrypoint apagado y `0/3` rehearsals;
- readiness R3 `pending` en vez de `blocked`, sin promoción automática.

## Contrato de seguridad

La UI productiva observada separa `Wildcard/Free Hit Play`, reemplazos `Remove/Add player` y
`Make Transfers`. El probe no selecciona ninguno. La vista duplica algunos controles entre pitch
y tabla, por lo que el contrato exige al menos quince controles de salida y concilia los quince
elementos por API autenticada; nunca depende de refs efímeros ni de un conteo visual exacto.

Antes del commit deben coincidir: elementos out/in únicos, tipo posicional por par, metadata de
target, cuotas finales 2/5/5/3, banco no negativo, hits según transfers libres y disponibilidad
del poder. Desde la primera confirmación cualquier error es `ambiguous`; no hay retry ni rollback
automático ficticio.

## Evidencia

| Evidencia | Resultado |
| --- | --- |
| suite completa previa al rollout | `1014 passed, 1 skipped, 79 deselected` |
| pruebas focales tras ajustes DOM | `41 passed` |
| feature commits | `5608194`, `ee59ba4`, `312ef84` |
| revisión desplegada en `main` | `a762a3ea` |
| probe vivo R3 | `status=pass`, 9/9 checks, 15 picks, target exacto |
| readiness vivo | 8 pass, 6 pending, 0 blocked; elegibilidad A0 |
| doctor vivo | 22 PASS, 0 WARN, 0 FAIL |
| imagen API/browser | `a762a3ea` |
| backup predeploy | `/opt/orbital/backups/mova-fpl/20260830T220414Z` |
| backup postdeploy | `/opt/orbital/backups/mova-fpl/20260830T221050Z` |

Durante la inspección el browser se detuvo al terminar y el estado del equipo no fue mutado.
No se guardaron cookies, storage, HTML autenticado ni snapshots de sesión.

## Pendiente explícito

HV1-07 no está promovido. Faltan rehearsals verificables para capitanía, XI/banca y R3, además
del diseño y prueba del entrypoint real R3. Estos pendientes son evidencia temporal/operativa, no
permisos implícitos para cambiar A0 o habilitar escrituras.
