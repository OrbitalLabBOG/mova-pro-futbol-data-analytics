---
type: project
name: "MOVA FPL Autonomous Operator 2026/27 — Deployment Evidence"
created: 2026-08-22
updated: 2026-08-23
tags: [mova, fpl, deployment, vps, observability, audit]
status: active-shadow
---

# Acta del despliegue shadow y autenticación supervisada

## Resultado

El control plane MOVA FPL quedó desplegado en el VPS y operativo contra la temporada
2026/27. El collector oficial, snapshot, motor de decisión, persistencia, API local,
métricas, auditoría, backup verificado, watchdog y browser aislado pasaron sus smokes.
El corte inicial no autenticó ni escribió en FPL. La adenda del 22 de agosto autenticó el
perfil manualmente, verificó la cuenta y demostró persistencia tras recrear el contenedor;
no ejecutó ninguna escritura sobre el equipo.

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

### Adenda de browser persistente

| Evidencia | Valor |
| --- | --- |
| Git / etiquetas OCI | `26dc084797974c5329b4d19adda0111d7da39093` / `26dc084` |
| Engine image | `sha256:e3f967c88a4f67dcc762775b27e028d4aeb981e303d17bd2acebb457fc72f523` |
| Browser image | `sha256:3e384243a1c6768173307e067c87332e60d94e31500968a47a817f7e8a37a63f` |
| Browser | Chromium 151 + agent-browser 0.26.0 |
| Perfil | `/var/lib/mova-fpl/browser-profile` |
| Cuenta verificada | `losmillosFPL`, `entry_id=3609854` |

El login Google se completó manualmente por noVNC. El launcher automatizado fue sustituido
por un único Chromium normal, visible y supervisado; agent-browser se adjunta posteriormente
por CDP en `127.0.0.1:9222` dentro del contenedor. Esto evita una segunda instancia sobre el
perfil y conserva la compatibilidad con OAuth. No se exportaron contraseñas, cookies,
storage ni archivos de estado.

### Adenda API-first del estado privado — 23 de agosto de 2026

| Evidencia | Valor |
| --- | --- |
| Runtime Git / etiquetas OCI | `0c6a566` / `0c6a566` |
| Migraciones operativas | `schema_migrations=3` bajo SQLite 3.53.4 |
| Fuente de verdad del equipo | `/api/my-team/3609854/` autenticada dentro del browser aislado |
| Última observación validada | `2026-08-23T00:49:17.823Z` |
| Fingerprint de estado | `fc790ac5...` |
| Estado observado | GW2; 15 jugadores; banco £0.0M; valor £100.0M; 1 transferencia libre; 0 realizadas |
| Chips disponibles | Triple Captain, Bench Boost, Free Hit y Wildcard |

El collector privado ejecuta el request dentro de la sesión ya autenticada y sólo devuelve
un allowlist estricto de plantilla, precios, banco, transferencias, chips y deadline. No
extrae cookies, local storage, tokens, credenciales, perfil Google ni PII. Cada captura se
sella con manifest y hashes antes de importarse a la base operativa.

Dos observaciones sucesivas (`00:44:44.375Z` y `00:49:17.823Z`) produjeron el mismo
fingerprint porque el equipo no cambió, pero quedaron almacenadas como capturas distintas.
Esto valida simultáneamente detección de no-cambio y frescura real del dato. La migración 3
elimina la deduplicación temporal que antes podía ocultar una observación reciente.

El dry-run posterior consumió explícitamente este estado autenticado, construyó una decisión
válida de 54.7 xP y volvió a proponer Wildcard con una mejora estimada de 16.1 xP. Esa salida
es sólo una hipótesis del modelo: no fue aprobada ni ejecutada y debe contrastarse con
noticias, minutos esperados, estrategia de chips y horizonte de varias jornadas.

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
publica noVNC en loopback mientras está encendido. CDP escucha sólo en loopback interno del
contenedor y no tiene mapping al host.

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

- El smoke inicial abrió la página oficial pública sin autenticación ni escritura.
- En la sesión supervisada, Julián completó Google OAuth manualmente; ORBIX no recibió ni
  escribió credenciales o MFA.
- `/en/my-team` devolvió `Pick Your Fantasy Football Team` y una lectura acotada del DOM
  confirmó simultáneamente `losmillosFPL` y `3609854`.
- Chromium cerró de forma controlada, el contenedor fue recreado con la imagen `26dc084` y
  `/en/my-team` volvió a abrir autenticado sobre el mismo perfil.
- API y browser quedaron `healthy`; noVNC escucha en `127.0.0.1:6080` del host y CDP sólo en
  `127.0.0.1:9222` del contenedor. No existe CDP público.
- Los timers `tick`, `watchdog` y `backup` continuaron activos después del despliegue.

## Automatización instalada

| Unit | Cadencia / función |
| --- | --- |
| `mova-fpl-stack.service` | mantiene API local |
| `mova-fpl-tick.timer` | dispara tick idempotente cada 5 minutos |
| `mova-fpl-private-state.timer` | evalúa cada 5 min; captura adaptativa 6 h → 1 h → 15 min → 5 min |
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

- El perfil persistente ya está autenticado y verificado para `entry_id=3609854`. Google o
  FPL pueden expirar/revocar la sesión; cualquier reautenticación vuelve a ser humana.
- Research/news tiene esquema y puertos de integración, pero aún no tiene el pipeline
  completo ni autorización para alterar decisiones.
- Alerting conserva outbox/incidentes, pero falta una ruta externa con acuse y pruebas P0/P1.
- El backup es local; falta copia cifrada off-host y restore drill desde esa copia.
- Falta acumular shadow por varias jornadas, deadline drills y pruebas de reboot/caos.
- No se habilitan `A1+`, writes ni cambios de chip/equipo hasta nueva aprobación explícita.

Este acta certifica readiness de **G1, base de G2 y el prerrequisito de identidad browser de
G4**. No declara cumplidos G3–G6 ni autoriza escrituras FPL.

La adenda API-first amplía la base de G2 con estado privado exacto y auditable. Al finalizar
la validación, el browser quedó detenido; el timer lo inicia únicamente para capturar,
consulta la API y lo vuelve a detener. Los controles permanecen en `shadow`, `A0`,
`compliance_gate=pending`, `kill_switch=true` y `browser_writes=false`.

La cadencia fija inicial de diez minutos se considera evidencia de commissioning, no diseño
final. El release siguiente instala un gate adaptativo: su evaluación liviana ocurre cada
cinco minutos, pero Chromium sólo se inicia cuando vence el umbral de la fase o ante una
captura pre/post acción forzada. La validación y el despliegue efectivo de ese release se
registran en una adenda separada para no reescribir la evidencia histórica.

### Adenda de cadencia adaptativa — 23 de agosto de 2026

| Evidencia | Resultado |
| --- | --- |
| Runtime Git / etiquetas OCI | `684e5da` / `684e5da` en engine y browser |
| Timer evaluador | activo; `OnCalendar=*:2/5` |
| Gate baseline real | `due=false`, `snapshot_fresh`, cadencia 21.600 s, edad 155 s |
| Duración observada del gate | aproximadamente 2 s, sin iniciar Chromium |
| Captura forzada de commissioning | `teamstate_de1cd64c33624155bb208a5dbdca8b77` |
| Auditoría del bypass | `team_state_capture_trigger`, payload `{"trigger":"forced"}` |
| Estado después del smoke | sólo API activa; browser detenido; `ops.db integrity=ok` |

La configuración efectiva elevó `MOVA_PRIVATE_STATE_MAX_AGE_SECONDS` de 900 a 21.600 como
techo absoluto. Collector y motor comparten la misma política: 6 horas normalmente, 1 hora
en las últimas 24 horas, 15 minutos en las últimas 3 horas y 5 minutos en los últimos 30
minutos. El motor usa el menor valor entre fase y techo, por lo que la relajación baseline no
debilita la frescura cerca del deadline.

El smoke forzado hizo únicamente el GET autenticado y produjo el mismo fingerprint
`fc790ac5...`: no hubo cambio de equipo. El evento `forced`, el job y el snapshot quedaron
correlacionados en el ledger. Los timers `tick`, `private-state`, `watchdog` y `backup`
quedaron activos; API `/readyz` respondió `ready`, no había incidentes ni outbox pendiente.
Los controles siguieron en `shadow`, `A0`, `compliance_gate=pending`, `kill_switch=true` y
`browser_writes=false`.
