---
type: operations-record
name: MOVA FPL — recuperación del runtime del 20 de septiembre de 2026
created: 2026-09-20
updated: 2026-09-20
status: in_progress
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
recuperación. Las 35 pruebas cercanas pasaron en el checkout local.

## Verificación final

- Suite completa local: `1764 passed, 79 deselected` en 24,56 s. La suite
  cercana del watchdog, contrato del operador y cockpit: `35 passed`.
- Imágenes engine, browser y research `4a8c5e0` construidas; API y browser
  recreados. `/readyz` devolvió
  `{"status":"ready"}`; `docker inspect` confirmó imagen y revisión
  `4a8c5e0`, con health `healthy`. Se conservó la imagen anterior y una copia
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

## Acceso privado pendiente

La captura forzada confirmó `FPL_AUTH_REQUIRED`; no se copió ni alteró el
perfil. El navegador aislado `mova-fpl-browser:4a8c5e0` está saludable y
se habilitó un túnel local `127.0.0.1:6080` para que Julián complete el login.
El timer privado se detuvo **temporalmente** durante la preparación del login
para evitar que un intento automático cerrara Chromium. Se volvió a activar a
las 19:43 UTC: los ocho timers quedaron activos. El servicio privado conservó
`Result=exit-code` porque el cooldown impide reintentos sin autenticación;
Chromium permaneció saludable. Tras autenticación: ejecutar captura privada
forzada, verificar 15 picks y fingerprint, resetear el estado fallido del
servicio y repetir el doctor. Sin ese paso, no declarar el runtime plenamente
restaurado.
