---
type: deployment-evidence
name: "HV1-09M — Final runtime closeout"
created: 2026-08-31
updated: 2026-08-31
tags: [mova, fpl, agent, recovery, reboot, postgres, readiness, audit]
status: verified-live
---

# HV1-09M — Cierre verificable del runtime

## Resultado

El runtime autónomo read-only quedó sano y recuperable en el VPS sobre `b4ca25b`. Se corrigieron
dos fallos reales de integración, se procesó una corrida agentic física, se refrescó el estado
privado, se ejecutó un reboot real autorizado y se sincronizó PostgreSQL después de la operación.
No se habilitaron writes ni se modificó el equipo FPL.

Este cierre no declara autonomía productiva A3. El estado correcto permanece `shadow/A0`, con 15
gates aprobados, 10 pendientes y cero bloqueados. Los pendientes dependen del settlement oficial,
de evidencia longitudinal en jornadas distintas o de destinos/credenciales externos todavía no
elegidos.

## Fallos corregidos

### Cola agentic compartida

El engine (`uid=10001`) creaba `research/receipts` y `research/permits` con modo `2750`; el worker
de research (`uid=10002`) podía leer pero no escribir el receipt. El timer generaba permisos y se
detenía antes de invocar Codex. `research-cycle.sh` repara ahora ambos directorios mediante
`install -d -m2770 -o10002 -g10001`, y bootstrap los precrea con el mismo contrato.

La recuperación viva produjo un único intento `attempt_add3d72482d24b30ae4fca1d245fbe50`, con
receipts `started/finished`, 24.378 tokens observados, autorización terminada y cero requests o
anomalías pendientes. El resultado fue importado de forma fail-closed: Strategist/Critic bloquearon
la propuesta y eligieron `primary_alternative`; no hubo intervención aplicada ni ejecución browser.

### Precedencia de configuración host/container

`collect-private-team-state.sh` cargaba `deploy.env` antes de `runtime.env`; una ruta interna del
contenedor podía sobrescribir la fuente host de configuración y romper el mount Compose. El script
carga ahora runtime primero y deploy después. El refresh autenticado terminó con
`job_d424c1bfd52e4eb89fa83d792019dbe5`, snapshot
`teamstate_4f454e93f16348bbbd8f9bab51bf8f6a`, 15 jugadores, banco 0, valor 100,3, dos
transferencias libres y cuatro chips disponibles. El fingerprint se mantuvo en
`ac16f6e3...c144b111`, confirmando lectura sin cambio.

## Reboot real

La preparación creó backups y selló revisión, boot ID, controles y team state. Tras la autorización
de Julián, `systemctl reboot` cambió el boot ID de
`cb7ae9fe-7efb-4fe6-ae14-fd815c205290` a
`251c6d98-a2fb-42f5-a3da-17e2484894b8`. La unidad boot-time terminó con código 0 y publicó:

| Evidencia | Resultado |
| --- | --- |
| Job | `job_1c7cfb92a1e9466599c90cc7a9a9959f` |
| Artifact SHA-256 | `7a000fdf2d38ddb2e25d1ed07d19749d6354f632f1f654367ab7b6e9baffb2c2` |
| Duración preparación→verificación | 221 s |
| Checks | 11/11 pass |
| Scheduler/timers | tick nuevo y 8/8 timers activos |
| Datos | SQLite íntegro; PostgreSQL con paridad; team fingerprint idéntico |
| Controles | shadow/A0, compliance pendiente, kill switch on, writes off |
| FPL | `fpl_state_mutated=false` |

Los demás contenedores del VPS también volvieron; `systemctl --failed` quedó vacío. Una preparación
auxiliar creada accidentalmente al consultar el wrapper fue identificada por su actor/razón,
archivada como `cancelled` sin ejecutar otro reboot y el path pending quedó ausente.

## Verificación de cierre

- commits funcionales: `ae5fb8b` y `b4ca25b`;
- suite completa: 1.213 passed, 1 skipped, 79 deselected;
- `mova doctor`: 23 pass, 0 warn, 0 fail;
- watchdog: `ok`, cola agentic healthy, 0 anomalies, 0 requests;
- readiness: 15 pass, 10 pending, 0 blocked sobre 25;
- host recovery: 5/5 escenarios completos;
- PostgreSQL import final `pgimport_b1a2bbff2b714585adf241221b02c930`;
- paridad final: 57/57 tablas, 56 exactas y una por invariantes;
- backup post-reboot SQLite `/opt/orbital/backups/mova-fpl/20260831T151518Z`;
- backup post-reboot PostgreSQL `/opt/orbital/backups/mova-fpl/postgres/20260831T151519Z`;
- API y PostgreSQL healthy; 8 timers activos; cero unidades fallidas;
- no existe `reboot-recovery.pending.json`.

## Pendientes honestos

1. El ciclo GW3 sigue preliminar hasta el settlement oficial de GW2.
2. Research calibrado, rehearsals browser y ciclos PostgreSQL requieren tres jornadas realmente
   distintas; repetir GW3 no cuenta.
3. Alertas externas necesitan un destino y owner reales, además de live ping.
4. Backup cifrado off-host necesita repositorio, credenciales, owner y restore drill.
5. Compliance y promoción A1/A2/A3 requieren decisiones explícitas separadas.

Ninguno de estos puntos justifica inventar observaciones, credenciales o autoridad. El sistema
puede seguir recolectando, analizando, investigando y auditando autónomamente en A0 mientras los
gates maduran.
