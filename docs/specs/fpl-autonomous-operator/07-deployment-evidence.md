---
type: project
name: "MOVA FPL Autonomous Operator 2026/27 — Deployment Evidence"
created: 2026-08-22
updated: 2026-08-22
tags: [mova, fpl, deployment, vps, observability, audit]
status: active-shadow
---

# Acta del primer despliegue shadow

## Resultado

El control plane MOVA FPL quedó desplegado en el VPS y operativo contra la temporada
2026/27. El collector oficial, snapshot, motor de decisión, persistencia, API local,
métricas, auditoría, backup verificado, watchdog y browser aislado pasaron sus smokes.
No se ejecutó ninguna escritura ni autenticación en FPL.

## Identidad del release

| Evidencia | Valor |
| --- | --- |
| Host | VPS Orbital `72.60.245.2` |
| Checkout | `/opt/orbital/services/mova-fpl` |
| Git | `26e974259efe2a39d795aa304a2e0f21c57396b6` |
| Engine image | `sha256:2306e4aea14c74f1385bbc9438a4a11fc0cbfd6bb21370481cfe5ef4e81b33d7` |
| Browser image | `sha256:20e3e8fd4ed1a915e1b490ff0b377ea6b7644402c273ea46d98c885c0243c951` |
| SQLite del runtime | `3.53.4` |
| CBC | `2.10.8` |
| agent-browser | `0.26.0` |

Las etiquetas OCI de ambas imágenes reportaron `org.opencontainers.image.revision=26e9742`.
El host conserva SQLite 3.45.1, pero no opera las bases: todos los jobs pasan por el gate
del contenedor.

## Controles efectivos

| Control | Valor | Consecuencia |
| --- | --- | --- |
| `mode` | `shadow` | produce propuestas, no ejecuciones |
| `action_level` | `A0` | sólo lectura/análisis |
| `compliance_gate` | `pending` | bloquea promoción |
| `kill_switch` | `true` | bloquea cualquier writer |
| `browser_writes` | `false` | el browser no puede confirmar cambios |

Los cinco valores fueron persistidos como `runtime_control_changed`, con actor, razón,
timestamp, payload hash y audit ID. El browser no monta `ops.db`, no expone CDP y sólo
publica noVNC en loopback mientras está encendido.

## Pruebas y evidencia operativa

### Suite y build

- Suite local: `692 passed, 2 deselected`.
- `docker compose config --quiet`: pasó.
- Units renderizadas: `systemd-analyze verify` pasó.
- Imagen engine: Python 3.13.5, SQLite 3.53.4 y CBC 2.10.8.
- Artefactos DB/modelos transferidos: 10/10 hashes SHA-256 coincidentes.

### Primer tick VPS

| Campo | Resultado |
| --- | --- |
| Job | `job_3c71547952cd4785b28971abb768dcad` |
| Correlation ID | `corr_1070ffdb5b3e49fbaed0c36b70f16040` |
| Estado | `completed` |
| Temporada / jornada | `2026-27` / GW2 |
| Deadline oficial observado | `2026-08-28T17:30:00Z` |
| Fase | `baseline` |
| Snapshot | `2026-27/gw02/20260822T223006Z` |
| Decision ID | `decision_b94587860c9c401aa3bbc51d270b6c9c` |
| Decision artifact SHA-256 | `9d92e1d6b4020873abff7938ced62b6488d326b261b7398d73b75e736438bf40` |
| Resultado shadow | 54.7 xP; borrador propone Wildcard |

La propuesta de Wildcard y 12 cambios es una salida algorítmica para revisión, no una
decisión aprobada. Debe reconciliarse con el estado autenticado, noticias y estrategia de
chips antes del deadline. Los gates actuales hacen imposible que el tick la ejecute.

### Persistencia y recuperación

- Migración `schema_migrations=1` aplicada dentro de SQLite 3.53.4.
- API `/readyz` devolvió `ready`; `/healthz` devolvió `ok`.
- Métricas reportaron `mova_up=1`, último tick sano, GW2, cero incidentes abiertos y
  outbox vacío.
- Backup online creado en `/opt/orbital/backups/mova-fpl/20260822T223115Z` con
  `ops.db`, `trace.db`, `fpl_canonical.db`, tamaños y SHA-256 en manifest.
- El primer drill detectó un error en el wrapper de restore; se corrigió la invocación del
  CLI y el drill repetido devolvió `integrity=ok` sobre la copia read-only.
- Watchdog independiente pasó con último tick `completed`.

### Browser y red

- Browser aislado abrió `https://fantasy.premierleague.com/en/` y obtuvo el snapshot
  interactivo de la página oficial pública.
- No hubo login, MFA, cookie importada, navegación privada ni click de escritura.
- Tras el smoke el contenedor browser quedó detenido.
- El único listener MOVA permanente observado fue `127.0.0.1:8787`; no hubo listener
  en `6080`, `9222` ni `9223` después de apagar el browser.

## Automatización instalada

| Unit | Cadencia / función |
| --- | --- |
| `mova-fpl-stack.service` | mantiene API local |
| `mova-fpl-tick.timer` | dispara tick idempotente cada 5 minutos |
| `mova-fpl-backup.timer` | backup diario verificado, 35 días de retención |
| `mova-fpl-watchdog.timer` | integridad y frescura cada 15 minutos |

El tick interno adapta el trabajo a la fase: baseline 6 h, research 3 h, refresh 1 h,
preflight 15 min y urgent 5 min. `flock`, claves de idempotencia y ledger evitan solapes y
repetición material.

El primer disparo automático de `mova-fpl-tick.timer` terminó con código 0. Reconoció el
snapshot de 302 segundos, registró un nuevo job/correlation ID y devolvió
`work=skipped_cadence` con `cadence_seconds=21600`; esto verifica que el timer funciona sin
repetir el collector ni los modelos cada cinco minutos.

## Límites y siguientes gates

- Falta autenticar el perfil persistente con MFA manual y verificar que corresponde a
  `entry_id=3609854`; esto no se hará sin una sesión supervisada.
- Research/news tiene esquema y puertos de integración, pero aún no tiene el pipeline
  completo ni autorización para alterar decisiones.
- Alerting conserva outbox/incidentes, pero falta una ruta externa con acuse y pruebas P0/P1.
- El backup es local; falta copia cifrada off-host y restore drill desde esa copia.
- Falta acumular shadow por varias jornadas, deadline drills y pruebas de reboot/caos.
- No se habilitan `A1+`, writes ni cambios de chip/equipo hasta nueva aprobación explícita.

Este acta certifica readiness de **G1 y base de G2 en shadow**; no declara cumplidos G3–G6.
