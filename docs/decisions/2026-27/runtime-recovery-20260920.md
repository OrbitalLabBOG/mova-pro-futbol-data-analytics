---
type: operations-record
name: MOVA FPL — recuperación del runtime del 20 de septiembre de 2026
created: 2026-09-20
updated: 2026-09-20
status: complete
tags: [mova, fpl, runtime, recovery]
---

# Recuperación del runtime — 20 de septiembre de 2026

## Alcance y controles

Julián pidió restablecer la operación completa del proceso y verificarla. La
cuenta FPL permanece bajo `shadow/A0`, `kill_switch=true`,
`browser_writes=false` y `compliance=pending`. Reactivar timers o reparar
observabilidad no cambia esos controles.

El VPS opera como `ubuntu` en `/opt/orbital/services/mova-fpl`. El checkout
tenía SHA `6a32ce6`, dos hotfixes de scripts host y `compose.override.yaml`
sin versionar. Se conservaron esos tres cambios. La imagen activa antes de la
recuperación estaba etiquetada `6a32ce6`, pero declaraba revisión interna
`cccc563`; el doctor mostraba `deployment_revision WARN`.

## Diagnóstico previo

El 20 de septiembre, alrededor de 19:14 UTC, el doctor informó 20 PASS, 2 WARN
y 2 FAIL. Los FAIL correspondían a los timers analytics/research deshabilitados
y a resultados fallidos de analytics/watchdog. API, PostgreSQL y las cuatro
fuentes de datos estaban sanos; el backup local era reciente. La captura privada
tenía más de 42 horas de antigüedad.

- Analytics falló el 17 de septiembre en `analytics_reconcile` por
  `psycopg.errors.ConnectionTimeout`. PostgreSQL pasó después los checks de
  conectividad, roles, integridad y paridad.
- El watchdog abrió un P0 `Scheduler heartbeat unhealthy` a las 19:17:18 UTC
  al ver el tick más reciente en `running`. El tick terminó bien a las
  19:18:42 UTC. `assess()` trataba cualquier tick sin `finished_at` como caída.
- La captura privada forzada devolvió `FPL_AUTH_REQUIRED` el 20 de septiembre.
  Hace falta renovar la sesión humana antes de probar nuevamente el GET privado.
- Analytics y research seguían disabled desde la contención de capacidad del
  17 de septiembre. Collector, tick, private-state, watchdog, backup y
  PostgreSQL sync tenían timers activos.

## Corrección preparada

En el VPS se creó la rama `codex/mova-runtime-recovery-20260920` desde
`6a32ce6`. El commit `4a8c5e0` modifica `watchdog.assess()` para considerar
sano un tick `running` dentro del umbral de 20 minutos y abrir la alerta si
permanece ejecutándose más tiempo. Una prueba nueva cubre ejecución, atasco y
recuperación. El commit `a8cfa7d` aplica la misma semántica a `status` y
`doctor`, para que una ejecución normal no parezca un heartbeat fallido.
Las 36 pruebas cercanas pasaron en el checkout local.

## Verificación final

- Suite completa local tras ambas correcciones: `1765 passed, 79 deselected`
  en 25,71 s. La suite cercana del watchdog, contrato del operador y cockpit:
  `36 passed`.
- Imágenes engine, browser y research `4a8c5e0` construidas; API y browser
  recreados. `/readyz` devolvió
  `{"status":"ready"}`; `docker inspect` confirmó imagen y revisión
  `4a8c5e0`, con health `healthy`. Después se construyeron las tres imágenes
  `a8cfa7d` y se recreó el API en esa revisión. Se conservaron las imágenes
  anteriores y una copia
  root-only de `deploy.env` en
  `/opt/orbital/backups/mova-fpl/runtime-recovery-20260920/`.
- Analytics manual terminó `Result=success`, exit 0, job
  `job_08d54acbb29846d393d6743de336a271`. Generó proyecciones de GW6 y
  mantuvo GW5 en `waiting_for_data_checked`; no evaluó ni cerró prematuramente
  la jornada.
- Research manual terminó `Result=success`, exit 0. Procesó cero requests y
  devolvió `outside_deliberation_window` para GW6, sin gasto agentic nuevo.
- Analytics y research timers quedaron enabled/active con los drop-ins de
  capacidad: analytics cada dos horas y research cada 30 minutos. Collector,
  tick, watchdog, backup y PostgreSQL sync también permanecen activos.
- Watchdog manual terminó `status=ok`; cockpit de 19:37 UTC mostró cero
  incidentes abiertos, revisión `4a8c5e0`, analytics/data/PostgreSQL healthy y
  controles FPL intactos en A0. Doctor posterior: 22 PASS, 1 WARN
  (`private_team_state` stale) y 1 FAIL (`systemd_service_results` debido al
  fallo privado previo), antes de renovar la sesión.
- La comprobación HTTP devolvió 200 para `/readyz` y el dashboard público,
  mientras `/api/v1/cockpit` externo siguió en 404.
- Un tick forzado y auditado en modo shadow (`job_da45ea4651404cbd94c35206488b8712`)
  corrió de 19:45:53 a 19:49:17 UTC y terminó `completed`, sin error.
  Durante esa ejecución, el watchdog respondió `status=ok`,
  `latest_tick_status=running`, `tick_age_seconds=36` y no abrió incidente.
  Tras el despliegue `a8cfa7d`, cockpit mostró cero incidentes, revisión
  coincidente y API healthy. Doctor: 22 PASS, 1 WARN, 1 FAIL; ambos pendientes
  se deben al acceso privado aún sin autenticar.
- Tras completar Julián el login humano, la primera captura forzada encontró
  `FPL_AUTH_INTERACTION_REQUIRED` durante el retorno SSO. Se esperó a que
  Chromium regresara a `fantasy.premierleague.com` y se hizo un único
  reintento supervisado. El job `job_c3015a11070f4b9ba0aa488cfaadedd3`
  terminó `completed` a las 19:59 UTC, con 15 jugadores, GW6, un traspaso
  libre y fingerprint
  `4e124b6efd6c983e8df7480407a5776c4813fe2374b336b6de05cd78f0865452`.
  El ingestor aceptó el estado y borró el marcador de cooldown.
- Se limpió el resultado fallido anterior de `mova-fpl-private-state.service`.
  El doctor de 20:01 UTC informó `overall_status=healthy`: **24 PASS,
  0 WARN, 0 FAIL**. El timer privado y los timers analytics, research y
  watchdog siguieron `active`; la API siguió `healthy`.

## Resolución del acceso privado

La captura inicial confirmó `FPL_AUTH_REQUIRED`; no se copió ni alteró el
perfil. Se habilitó un túnel local `127.0.0.1:6080` para el login humano.
El timer privado se detuvo **temporalmente** durante la preparación del login
para evitar que un intento automático cerrara Chromium. Se volvió a activar a
las 19:43 UTC: los ocho timers quedaron activos. Julián completó la
autenticación y la captura posterior verificó los 15 picks y el fingerprint.
El doctor final quedó sano. El navegador se detuvo al terminar la captura,
conforme al wrapper; el perfil persistente se conservó.

Los controles de autonomía siguen en `shadow/A0` con writes deshabilitados.
Esta recuperación operativa no equivale a promoción A2/A3 ni a cierre oficial
de GW5, que depende de `data_checked` de FPL.

## Persistencia de la sesión browser

El 20 de septiembre a las 20:05 UTC se activó
`MOVA_BROWSER_KEEP_RUNNING=1` en `/etc/mova-fpl/deploy.env`. El collector ya
soportaba esta opción: en su `cleanup` deja de detener Chromium después de la
captura. El perfil sigue montado en
`/var/lib/mova-fpl/browser-profile` con permisos `0700`; `compose.yaml` ya
tenía `restart: unless-stopped`. El browser se inició y quedó `running` y
`healthy`. noVNC permanece publicado sólo en `127.0.0.1:6080` del VPS y los
writes de FPL siguen deshabilitados.

El primer ensayo coincidió con el retorno automático de SSO tras arrancar
Chromium; el collector lo bloqueó con `FPL_AUTH_INTERACTION_REQUIRED`. Cuando
la página regresó a Fantasy, un reintento supervisado completó la captura
`job_1a995c3ce30041c3ae724b8eedda101e` a las 20:06 UTC: 15 picks y el
mismo fingerprint
`4e124b6efd6c983e8df7480407a5776c4813fe2374b336b6de05cd78f0865452`.
Después del `cleanup`, el contenedor siguió `running/healthy` con política
`unless-stopped`; `doctor` informó 24 PASS, 0 WARN y 0 FAIL. El marcador de
cooldown quedó borrado por la ingesta exitosa.

Mantener Chromium vivo evita el arranque y retorno SSO en cada captura; no
extiende por fuerza la vigencia que Premier League o Google asignen a la
autenticación. El timer privado continuará verificando frescura y fallará de
forma explícita si se pierde el acceso. Este modo retiene hasta 1,25 GiB de
RAM asignada al contenedor y conserva noVNC en loopback. No se almacenaron
credenciales nuevas ni se modificaron cookies manualmente.

Rollback: existe una copia root-only de `deploy.env` previa al cambio en
`/opt/orbital/backups/mova-fpl/runtime-recovery-20260920/deploy.env.before-keep-browser`.
Para volver al modo on-demand, retirar únicamente
`MOVA_BROWSER_KEEP_RUNNING=1` de `deploy.env` y detener el browser mediante
`sudo deploy/bin/browser-session.sh stop`; después comprobar el timer privado
y `mova doctor`. El perfil autenticado no debe borrarse en ese rollback.

## Auditoría de estabilidad del VPS

Entre 20:10 y 20:16 UTC se comprobó un host con 2 vCPU, load de 0,86–1,02,
7,8 GiB de RAM total, aproximadamente 4,4 GiB disponibles y 42 GiB libres
en disco (57 % usado). El swap conservaba 1,2 GiB ocupados, pero la muestra
`vmstat 1 5` no mostró entradas de swap ni espera de I/O; el tiempo ocioso de
CPU estuvo entre 67 % y 93 %. El PSI `cpu.some` del host fue elevado
(aproximadamente 30–52 %), mientras `cpu.full` fue 0; las métricas de los
contenedores MOVA no mostraron saturación sostenida. Se deja como señal a
vigilar, no como prueba de falta de capacidad actual.

No había unidades systemd fallidas ni errores OOM/I/O recientes en el kernel.
API, PostgreSQL y browser estaban `healthy`; el browser consumía cerca de
635 MiB y mantenía sus límites de Compose. El único worker MOVA observado era
la ejecución de analytics de las 20:10 UTC; salió con código 0 a las 20:10:51
y no dejó contenedor worker activo. El private-state timer de las 20:12 UTC
salió con código 0 y `snapshot_fresh`, sin captura repetida. Cuatro
contenedores experimentales de voz estaban detenidos desde el 17 de
septiembre; uno de ellos registra `OOMKilled=true` histórico. Ninguno usaba
recursos en esta auditoría. Se observaron rechazos SSH transitorios al abrir
varias conexiones paralelas, pero el servicio siguió activo, el dashboard
respondió HTTP 200 y el acceso SSH se recuperó; el journal de las últimas
24 horas no mostró autenticaciones fallidas. No hay evidencia de una caída
del VPS durante esta revisión.

El doctor sí detectó una ventana de `scheduler_heartbeat FAIL`: el último
tick completo superó 1.200 segundos porque el timer de capacidad corría cada
15 minutos y la ejecución de las 20:00 UTC se omitió por lock. El tick de las
20:15 UTC terminó `status=0`. Se conservó el lock de admisión y sólo se cambió
el calendario en
`/etc/systemd/system/mova-fpl-tick.timer.d/90-capacity.conf` de cada 15 a
cada 5 minutos, con `Persistent=false`. El timer quedó `active` y el doctor
posterior volvió a `healthy`, 24 PASS, 0 WARN y 0 FAIL, con heartbeat de 70
segundos. Hay copia root-only del drop-in anterior en
`/opt/orbital/backups/mova-fpl/runtime-recovery-20260920/tick-90-capacity.conf.before-heartbeat-fix`.
El intervalo corto da oportunidades de heartbeat aun cuando una corrida
coincida con otro job; el lock mantiene el límite de una tarea intensiva a
la vez. El primer disparo programado tras el cambio corrió de 20:20:12 a
20:20:19 UTC con `ExecMainStatus=0`; el siguiente quedó programado para
20:25:08 UTC. No dejó worker activo. El doctor posterior informó 24 PASS,
0 WARN y 0 FAIL, con heartbeat de 29 segundos; browser, API y PostgreSQL
seguían `healthy`, todos con `RestartCount=0`.
