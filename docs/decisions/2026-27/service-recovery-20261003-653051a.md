---
type: operations
name: "MOVA FPL — cuatro ensayos reales de recuperación de servicios"
created: 2026-10-03
status: verified-service-drills
owner: Julián Zuluaga
---

# Recuperación de servicios — 03/10/2026

Julián autorizó ejecutar secuencialmente los cuatro ensayos: API, PostgreSQL,
browser y caída combinada. Se usaron los scripts allowlisted del runtime
`653051ae28b1d03f6d568ee99fc4b40f060ced8b`, con claves nuevas y evidencia
original importada. No se cambiaron las imágenes ni los controles de autoridad.

| Escenario | Controles aprobados | Tiempo registrado por el script |
| --- | --- | --- |
| API | 5/5 | 25 s |
| PostgreSQL | 8/8 | 17 s |
| Browser | 9/9 | 33 s |
| Combinado | 13/13 | 49 s |

Los timestamps, jobs y hashes de las evidencias están en el JSON adjunto.
El campo `downtime_seconds` de API incluye el ensayo hasta terminar sus
comprobaciones; no es una medición independiente de indisponibilidad. Los
otros scripts miden desde la parada hasta la recuperación de endpoints.
Estos tiempos tampoco representan RTO de reconstrucción de un VPS nuevo.

PostgreSQL conservó la API disponible, integridad SQLite y estado privado,
y pasó la paridad después de recuperarse. Browser conservó sesión autenticada,
fingerprint privado, controles fail-closed y estado inicial del servicio.
El combinado detuvo realmente los tres servicios y verificó integridad,
paridad, sesión, imágenes y fingerprints después de recuperarlos.
Las cuatro evidencias declaran `fpl_state_mutated=false`.

Se conservó el backup v2 previo de hoy: SQLite `20261003T102102Z`, PostgreSQL
`20261003T102113Z`, snapshot externo `9d4c1c7921fb` (prefijo del registro restic).
No se restauraron datos sobre las bases vivas.

## Fallo de contención encontrado y corregido

Durante el ensayo PostgreSQL, el tick programado del 03/10 a las 23:40:05 UTC
intentó tomar el lock del worker que ocupaba el drill. El flock interno no
especificaba `-E 75`, devolvió 1 y systemd marcó el tick como fallo.
El lock de capacidad externo ya devolvía 75, pero no cubría el lock interno.

Se cambió el flock interno a `-n -E 75` en la unidad base y en el drop-in
`90-capacity.conf` del VPS; la unidad base ahora declara también
`SuccessExitStatus=75`. Se recargó systemd. El código 1 del worker sigue siendo
fallo; sólo la contención se omite. La prueba controlada con el lock ocupado
produjo `Result=success / ExecMainStatus=75`; el tick normal posterior produjo
`Result=success / ExecMainStatus=0`.

Las copias anteriores de ambas unidades están protegidas bajo
`/opt/orbital/backups/mova-fpl/service-recovery-20261003/`. El cambio operativo
de systemd se aplicó sobre el runtime 653051a sin desplegar nuevas imágenes;
la corrección canónica de la unidad se conserva en este cambio de Git.

## Alcance pendiente

Los cuatro escenarios de servicios tienen evidencia nueva de la revisión actual.
El gate conjunto exige además reboot y permanece pendiente hasta renovarlo.
La skill `mova-fpl-operator` exige preparación con TTL y autorización explícita
separada antes de reiniciar el VPS. No se preparó ni ejecutó reboot en esta sesión.
Tampoco se acredita reconstrucción en host vacío. Las evidencias históricas se
conservan sin editar ni backfillear.

## Cierre verificado

Doctor a las 23:55:28 UTC (18:55:28 Bogotá): **24 PASS / 0 WARN / 0 FAIL**,
observabilidad disponible. Cockpit a las 23:55:53 UTC: `healthy`, safety
`safe_to_wait`, cero incidentes/alertas críticas y cero jobs fallidos en 24 horas.
Tick nuevo completado a las 23:55:14 UTC. Las cuatro evidencias nuevas son
válidas para `653051a`; sólo reboot carece de revisión/fecha originales válidas.
El gate de restore externo sigue passing. La comprobación SSH inicial agotó
el tiempo de conexión; el reintento y los diagnósticos posteriores completaron
correctamente, sin reiniciar servicios por esa incidencia de acceso.
