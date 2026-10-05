---
type: release-verification
name: MOVA FPL — cierre de iteración dcf98b8
created: 2026-10-04
status: verification-in-progress
owner: julian
---

# Release y expediente de cierre

## Identidad y aceptación

PR #191 integrada: `dcf98b8555ddc848258c13bfd64db5da29c4c423`.
CI de PR: run `37260316950`, pass. CI de main: run `37260422288`, success
sobre ese SHA. Suite local final: 1.972 passed, 1 skipped, 79 deselected,
33,22 s; slow/integration_data excluidos por configuración canónica.
La [auditoría H01–H13](harness-autonomy-audit-20261004.md) conserva causas,
implementación y límites. Esta acta seguirá `verification-in-progress`
hasta observar despliegue, doctor, drills renovados y estabilidad.

## Construcción y procedimiento

Build en checkout aislado `/opt/orbital/builds/mova-fpl-dcf98b8`; el checkout
operacional permaneció en 4917df0 durante la construcción; el cutover a dcf98b8
terminó el 05/10 a las 04:07 UTC (04/10, 23:07 Colombia). Docker usa
builder legacy en este host; el primer build fue interrumpido antes de instalar
por no tener límites explícitos. Reanudación secuencial con `--cpu-period=100000
--cpu-quota=50000 --memory=768m`; no se cambió la capacidad de los servicios.
Una sesión SSH se interrumpió antes de producir la imagen; se reanudó
la construcción en la unidad temporal `mova-fpl-build-dcf98b8`, con
log local y los mismos límites. El runtime no cambió por esos intentos.
Digest del Debian del stage SQLite observado: `sha256:3783cc01769c7b2b1b83a5c5ad96c815348e28ed7da68e2e3687004faa906251`.
Ese FROM sigue usando tag mutable en el código: documentar el digest observado
no lo convierte en fuente fijada para futuras construcciones. Runtime Python,
SQLite/checksum y restantes imágenes base conservan sus contratos fijados.

Script de release preparado en `/opt/orbital/ops/mova-release-dcf98b8.sh`:
smoke sin red/credenciales/bases productivas; backups SQLite/PG; copia privada
de configuración/override; pausa de timers y locks de writers/capacidad;
checkout/tag concordantes; migración idempotente, API y browser recreados;
rollback de código/configuración por trap; reposición de timers y reporte DR.
No restaura ni reemplaza bases vivas durante rollback. La disponibilidad de
rollback se verificará separadamente de haberlo ejercido.

Override inventariado SHA256 `d0ee00f0cb50d42aafa3243fd5895fd8aab47068ab1299a1b20c82555bb110ac`.
Diez timers estaban activos antes de la operación. La ventana de estabilidad
será **30 minutos posteriores al último drill disruptivo** sobre dcf98b8,
con al menos tres observaciones fechadas de doctor/status/workflow y al menos
un tick concluido. Se predeclara aquí; no se acreditan minutos anteriores.

## Inventario de imágenes instaladas

| Imagen | ID local |
| --- | --- |
| engine:dcf98b8 | `sha256:22d373630f27f369dde92b9dd7d649be05a014e34932f91df6203344c397552d` |
| browser:dcf98b8 | `sha256:b34a345338a3a4ae47b3dbac4a4a891bc2539ab6f7559cc2ed6b3bb1952d98e4` |
| research:dcf98b8 | `sha256:4774242ef6015de894f677db658531ceac30cae134e49b374ad2cbbe5a91d36b` |

## Smoke de imagen aislada

Engine `dcf98b8` construido; guard SQLite 3.53.4 pass. Smoke sin red, sin
credenciales y sin bases del runtime: migraciones 1–21 y resilience drill
**10/10 checks true**, status pass, `runtime_mutated=false`.
Primer intento aislado omitía inicializar la base temporal y falló antes del
drill; se corrigió el procedimiento, sin cambiar ni restaurar datos vivos.
Job del ledger **efímero** `job_61b43d8208d24755bc1658656c2f4900`;
no es un drill ni evidencia de alerta/DR del VPS. Las tres imágenes se construyeron; unidad build terminó success/0, active/exited.
agent-browser 0.26.0 y codex-cli 0.153.4 comprobados sin red.
Unidad de release `mova-fpl-release-dcf98b8` terminó success/0, active/exited.
Checkout e imágenes concordantes; status posterior healthy, controles shadow/A0,
kill switch on, browser writes off. Backup SQLite `20261005T040155Z`,
job `job_8acd71afd5cd4175af4652521a2d9590`; PG `20261005T040210Z`.

Datos vivos anteriores al deploy: publicación del collector
`2026-10-05T03:45:36.791+00:00`, cuatro fuentes healthy, cero fallos consecutivos.
Eventos se recuperó por el ciclo programado (last success 03:45:45 UTC),
sin forced retry adicional. Conserva la distinción con el rescue del calendario.

## Pendientes de aceptación que no cubre instalar software

- H08: decisión sobre ADR-011 y cohorte prospectiva preregistrada. Gate histórico actual intacto.
- H10: follow-up equivalente de overruns y reserva operacional real. No ampliar allowance.
- H11: browser DOM aún sin prueba física válida; timeouts y error CDP de navegación,
  sin Save. Doctor de agent-browser: 6 pass/1 warn/0 fail; limpieza de archivos
  de daemon terminado. No se cambió selector ni sumaron rehearsals.
- AC04/05: ledger de tres GWs por capacidad/versión con probes físicos read-only.
  Esos probes cuentan para sus gates, pero no prueban commit. Ensayos controlados
  de ejecución/guardado tienen aceptación adicional; lineup y R3 mantienen entrypoint off.
- AC07: reboot nuevo exige preparación vigente y autorización explícita separada;
  reconstrucción desde host vacío no probada, sin provisión de recursos/costes.
- AC08/09: jornada completa real y promoción/compliance explícitos.
- H12: update PM preparado después del corte final; skill proyecto exige petición
  explícita para escribir PM. Esta iteración conserva Supabase read-only.

## Preview de update PM

Proyecto `cbd36dc4-0c1a-45ad-9134-1019e99639e4`. Borrador, no insertado.

**Título:** Iteración harness H01–H13: release dcf98b8 y aceptación pendiente.

**Contenido provisional al 05/10 04:32 UTC:** PR #191 integrada y dcf98b8
instalada; H01/02/03/04/05/06/07/13 implementados, H09 ya existente verificado.
Doctor 25 PASS/0 WARN/0 FAIL; suite desplegada 1.972 passed. Restore externo
8/8 (425 s, downtime cero), API 5/5 (23 s), PG 8/8 (19 s), con pruebas nuevas
ligadas al SHA. Browser/combinada y estabilidad todavía pendientes; browser
perdió contexto durante la redirección inicial y el GET posterior a la espera
corregida respondió 403. Login humano solicitado y arreglo local f0ba402 preparado,
no desplegado. Research histórico 4 GWs medidas/0 passing, ADR-011 propuesta sin
aprobar; follow-up equivalente de overruns sigue pendiente. Autoridad shadow/A0,
kill switch on, writes off, compliance pending. Readiness 21 pass/5 pending/1 blocked
al 04:28 UTC. Reboot exige autorización separada; host vacío y jornada completa
no probados. Conservar AC01/02/03/05/08 in_progress, AC04 blocked y AC09 todo;
no cerrar por tests ni heredar pruebas. Último update PM observado: 29/09.
Actualizar este preview con el corte final y revisar esquema/estado vivos antes
de cualquier inserción explícitamente solicitada; no sobrescribir historia.


## Verificación posterior al despliegue

Doctor dcf98b8: **25 PASS / 0 WARN / 0 FAIL**, incluidos snapshot/RPO,
observación DR, checkout/imagen, fuentes, PostgreSQL y privados. Cockpit
`2026-10-05T04:14:01+00:00`: workflow safe_to_wait, violations vacías,
ocho recovery_contracts y timing/recovery en los nueve stages. Research muestra
import terminal del 22/09, ratios 0,48/0,48, manifest_matches_current=false y
permits_execution=false; no falsea frescura/calidad. Sensor DR del
04:07:51 UTC ligado al SHA final, seis checks pass, edades extrapoladas
local 726 s / remota 20.991 s, host_reconstruction_proven=false.

Inspección offline del Codex 0.153.4 instalado: esquema generado sin red,
sin auth montada; `TurnStartParams` no tiene campo directo de límite de tokens.
El wrapper sigue interrumpiendo al recibir uso acumulado. No se concluye que
ninguna configuración futura pueda acotarlo, ni se acredita un hard cap físico;
H10 conserva ese límite y exige follow-up equivalente con metering real.

Restore externo `harness-dcf98b8-offsite-restore-01`: PASS **8/8**, 425 s,
interrupción cero, 04:10:32–04:17:37 UTC; unidad active/exited success/0.
Job `job_700d67d31ff74d619bfb067c41492b69`, artifact SHA256
`e4c617577f86def14b7cd6304c72e10c629285fe8ffdcbd239128b6fadad5e67`.
Restore aislado de tres SQLite, PostgreSQL y modelos; runtime sin mutación.
No acredita reconstrucción de host vacío ni reboot.

API `harness-dcf98b8-api-recovery-01`: PASS **5/5**, 23 s de interrupción,
04:21:15–04:21:38 UTC; unidad active/exited success/0.
Job `job_c76d5f5fb07848bfb3a3120b605e5611`, artifact SHA256
`08bf7f629081e3db995742522e56a6617b69e138aacc1a6a378d369eef08bd86`.
Primer despacho usó por error un nombre de script inexistente; systemd lo
rechazó antes de ejecutar. Se corrigió a api-recovery-drill.sh con la misma clave;
no hubo outage adicional ni evidencia acreditada por ese rechazo.
Los demás drills y estabilidad siguen pendientes.

PostgreSQL `harness-dcf98b8-pg-recovery-01`: PASS **8/8**, 19 s de interrupción,
04:26:04–04:28:57 UTC; unidad active/exited success/0.
Job `job_afaa9b85abb4472f9bdd8b66273afbb0`, artifact SHA256
`4847c87be1ec0eb05ab5e90a103ad48941dc847e83bed8b90a874b0a25a6bf8d`.
Los primeros despachos se aplazaron con exit 75 antes de outage por locks
worker/private-state; la misma unidad y clave se reutilizaron. No se borraron locks.

Browser dcf98b8: primer intento de recuperación falló a las 04:25:12 UTC
con `CDP error (Runtime.evaluate): Inspected target navigated or closed`;
no llegó a importar una prueba passing. Trap detuvo el browser (estado inicial);
OOMKilled=false. No se imputa este fallo a autenticación ni a selector sin prueba.
Suite repetida tras corrección documental: 1.972 passed, 1 skipped,
79 deselected, 37,86 s.

Disponibilidad de rollback comprobada sin ejecutarlo: las imágenes engine/browser/
research:4917df0 siguen presentes y las copias privadas de deploy.env/override
existen. SHA del override posterior coincide con el anterior
`d0ee00f0cb50d42aafa3243fd5895fd8aab47068ab1299a1b20c82555bb110ac`.
Diez timers FPL programados siguen presentes; los timers de otros productos
(mova-mlflow y mova-football) no pertenecen a este release.
El browser instalado reportó Chromium **154.0.8037.92**, agent-browser **0.26.0**.

Lectura GET posterior a espera por `/en/`, 04:32:51 UTC: **HTTP 403**, sin
pérdida de contexto, sin Save ni datos privados persistidos. Julián indicó
que puede autenticar ahora: noVNC preparado mediante túnel loopback, timer
privado pausado temporalmente para no cerrar el handoff. Debe reanudarse
tras verificar sesión o cancelar el handoff. Arreglo f0ba402 aún no desplegado;
suite local 1.973 passed, 1 skipped, 79 deselected, 35,76 s. Cambiar SHA requiere
renovar la aceptación final y las pruebas que dependen de revisión.

Follow-up de arranque: [PR #192](https://github.com/OrbitalLabBOG/mova-pro-futbol-data-analytics/pull/192), CI run 37264258191 pass (1m13s), integrada como 8820c56306f616b24e78a6e9248d3ad720ad2f07 a las 04:38:10 UTC. Imágenes finales en construcción; cutover pendiente del handoff de autenticación.

CI de main para 8820c56: run **37264381284 success**. Build aislado en unidad
`mova-fpl-build-8820c56`, Type=oneshot/RemainAfterExit, timeout 1.800 s;
lock de capacidad y límites 0,5 CPU/768 MiB. No cambiar checkout ni browser
del handoff durante construcción. La preparación no acredita instalación.

Build final 8820c56 terminado success/0 active/exited a las 04:40 UTC.
Smoke efímero sin red/credenciales/bases vivas: migraciones 1–21, SQLite 3.53.4,
resilience 10/10 PASS, runtime_mutated=false;
job efímero `job_b34955a675c34e92b238ddcff3880a48`.
No acredita un drill productivo ni entrega externa de alertas.

| Candidato 8820c56 | ID local |
| --- | --- |
| engine | `sha256:204c6515d56d81be232a272fee57abbe17fce831e8f1e24eef8852406d665717` |
| browser | `sha256:75bf9646ee21cc2c5af96c663cbd47a7aeb2c810a49db290595f29e33440ffea` |
| research | `sha256:3cb9da6188dc7ed2f7339c561a96a5ee696abcc1fcd54ea955d953389b59c180` |

No desplegado todavía: handoff de autenticación sigue abierto.

## Fuente local de skills

El adapter Orbital OS apunta al checkout hermano principal
mova-pro-futbol-data-analytics. Su HEAD observado es c86e76e y contiene cambios
locales de skill, AGENTS, browser, collector, contratos y tests. No se reseteó
ni sincronizó a ciegas. La fuente actual de esta iteración es main/8820c56 y el
worktree aislado mova-fpl-dr-hardening; el VPS permanece dcf98b8 hasta el cutover.
Una nueva sesión debe contrastar SHA/fuente al cargar la skill: las modificaciones
integradas en Git no significan que ese checkout local antiguo esté actualizado.
Resolver la sincronización local exige preservar y reconciliar esos cambios;
no acreditar una prueba desde una skill vieja o desde un archivo sin desplegar.

Skill del checkout principal reconciliada con la fuente 8820c56 mediante
three-way; único conflicto resuelto: updated 12/09 → 04/10. El bloque local de
orientación se conserva íntegro, SHA256
`f65169edd0191c1ee8162d9bb5c49270255dfb76bb7c12caa141b77b6a3f7a0c`.
Skill resultante SHA256
`b60de8659137ad8a4b49174b52b0209fb3295803c6697408923931173cb9fea0`.
Sólo cambió esa skill en el checkout antiguo; no se reseteó código ni se sincronizó
su HEAD. Suite de ese checkout antiguo: **1.766 passed, 79 deselected, 27,03 s**;
no sustituye la suite de 1.973 del candidato. Check harness Orbital:
15 documentos/13 máquinas/111 transiciones/32 checks/13 requisitos PASS;
`./orbital check` 3 tests PASS, failures vacías. Son checks offline, no gates vivos.
La orientación local se incorpora también a la fuente Git, con anchor de cockpit;
no registra funciones ni modifica autoridad.

Handoff revalidado: el túnel SSH de la sesión CLI había terminado (handle
49767 terminal y puerto local ausente). Se sustituyó por unidad user systemd
`mova-fpl-login-tunnel-20261004`, active/running, RuntimeMaxSec 3.600 s;
HTTP local noVNC 200 comprobado. No se reinició el browser ni se tocó su perfil.
Unidad/timer remoto `mova-fpl-login-handoff-expiry-20261004` cierra el browser y
reanuda private-state.timer tras 60 min si el handoff sigue abierto. Cancelar ese
timer al completar login/cleanup; no dejarlo para una sesión posterior.
Suite actual repetida tras reconciliación canónica: 1.973 passed, 1 skipped,
79 deselected, 39,82 s. Check documental y orbital check PASS.

## Corte posterior: autenticación confirmada y probe aún pendiente

La observación 403 de las 04:32 es histórica. A las
**2026-10-05T04:53:46.742Z**, el GET privado respondió HTTP 200 con
15 picks. Captura canónica posterior: job
`job_5d8642cbafba4381b52807d51801fa6e`, snapshot
`teamstate_5449d227bbf74c00a7f1e6586053b455`. Se cerraron el túnel
y el timer temporal de handoff; private-state.timer quedó reanudado.
No se escribieron credenciales ni se despachó Save.

El acceso privado no acredita la cancha. El probe monolítico falló primero
por espera insuficiente del checkbox; el selector nativo de Captain/Vice Captain
sí se observó después. Una espera ampliada dentro de una sola evaluación agotó
el timeout CDP. Se investiga un helper local con etapas independientes, reloj
total de 90 s y llamadas de máximo 25 s, contrato DOM .10.1 y R2 .10.2.
Sus tests sintéticos no cuentan como rehearsals. El ensayo en frío todavía
falló en page_gate: ruta /en/my-team, cero controles de cancha, GET privado 200.
No hay probe vivo PASS ni evidencia nueva importada al ledger.

El runtime sigue dcf98b8; las imágenes 8820c56 siguen siendo candidatas
sin cutover. El cierre de browser/combined DR y la ventana de estabilidad
de 30 min continúan pendientes. El pin del Debian del stage SQLite y el
helper por etapas aún son cambios locales, no capacidades desplegadas.

Diagnóstico adicional: en frío, tras la navegación la cancha permaneció
vacía y finalmente renderizó 15 controles de jugador y 15 switches, con
identidad de equipo coincidente. No fue pérdida de sesión. El candidato
arranca Chromium directamente en My Team y sustituye la espera CDP larga
por consultas cortas, reservando 40 s del reloj total para las fichas.
Suite del candidato: **1.994 passed, 1 skipped, 79 deselected, 34,92 s**.
El positivo de la cancha no sustituye la verificación completa de las 11
fichas ni cuenta como rehearsal.

PR #194 integrada como `ed39afcb4d345f92c1c89b1825a37fb6f1fc3e7c`
(CI 37268510857 PASS, 1 min). Las tres imágenes candidatas se construyeron
en `mova-fpl-build-ed39afc`, terminal active/exited, exit 0. Engine
`sha256:a0739239f82474755216981977a5df8ddade3002a6b3a782f3fe483db42a59c3`;
browser `sha256:4c10f2764f869477ed599c35cf66b0bd49e426c062e0380c990c066398280d60`;
research reutiliza el digest 3cb9da6188dc. No se hizo cutover.

La inspección de fichas aun con cancha precargada falló por CDP timeout.
El siguiente follow-up separa apertura, lectura y cierre de cada ficha en
llamadas breves y conserva el reloj de 90 s. El primer ensayo con arranque
directo ed39afc todavía agotó page_gate a los 50,85 s; se restauró y comprobó
el browser dcf98b8 detenido. Se ensaya ahora la secuencia efectiva del host,
con captura privada de máximo 45 s antes del probe. Ningún fallo es rehearsal.

Riesgo adicional de concurrencia: el host R2 no adquiría los locks compartidos
con el collector privado. El follow-up los reserva, en orden privado/capacidad,
antes del claim. Contención retorna 75 sin intento ni lease. Tests sintéticos
de ambas contenciones PASS; no autoriza ejecución A0 ni altera los gates.

La captura privada previa al probe agotó 45 s con el candidato a 0,25 CPU.
Con préstamo temporal a 0,50 CPU completó, pero la lectura de la tercera
ficha agotó CDP. A 0,75 CPU se observaron nueve fichas antes de un timeout:
las etapas sanas de las fichas 7 y 8 tardaron 0,44–0,93 s, y sheet_state de
la ficha 9 tardó 25,55 s. No se interpretó como checkbox inexistente ni
como éxito. El cleanup volvió a crear el browser dcf98b8 detenido.

El follow-up permite una sola relectura de DOM puro ante el timeout conocido
CDP, nunca una segunda apertura/cierre/GET/Save. Conserva el reloj original
y la etapa del error primario aunque la limpieza posterior termine. El
préstamo propuesto es de máximo 0,50 CPU, requiere ambos locks heredados y
restaura el cap anterior al salir. Ambos límites se comprueban con fixtures;
el ensayo completo con relectura y 0,50 CPU sigue pendiente.


## Diagnóstico del transporte — 5 de octubre, 07:00 UTC

La actualización experimental de agent-browser 0.26.0 a 0.38.2, las lecturas
DOM síncronas y un batch por ficha no produjeron un probe completo. Los fallos
conservaron los límites y no sumaron rehearsals. La versión nueva tampoco
prueba que el timeout del cliente anterior esté corregido en este flujo.
La imagen experimental no se promovió; el CLI fijado sigue en 0.26.0.

Una conexión CDP directa, con Chromium 154.0.8037.92 y préstamo temporal
0,50 CPU, completó la misma inspección en **64,586 s**: cinco checks de cancha,
las once fichas y seis checks de capitanía PASS; GET final sin cambios.
No hubo diálogo JavaScript ni Save. Esta comparación apoya sustituir el
transporte del probe; no identifica por sí sola el defecto interno del cliente.
Es una prueba diagnóstica, no un import al ledger de aceptación.

El candidato conserva un target FPL único y fijo, una conexión, un whitelist
de etapas sin JS arbitrario, límite por llamada 25 s y reloj global 90 s.
No exporta auth, no acepta diálogos, no cierra Chromium ni cambia autoridad.
El host valida el mismo esquema y los mismos picks/controles antes de publicar.
La ruta captura privada → probe y la restauración física del préstamo CPU
siguen en comprobación antes del merge/cutover. Suite: **2.019 passed,
1 skipped, 79 deselected**, 38,02 s; incluye transporte fake sin red/credenciales.

El sensor DR detectó correctamente la discrepancia temporal entre checkout
instalado y browser candidato durante un ensayo, abriendo P1. Se restauró el
browser dcf98b8 detenido; reporte DR fresco 06:16:12 UTC, seis checks PASS.
El watchdog programado resolvió el incidente tras observar la corrección:
status a 06:43:48 UTC healthy, cero incidentes y tick completed 06:40:10 UTC.
Los siguientes previews pausan sólo el timer del sensor durante su ventana,
con trap de restauración; no silencian alertas ni simulan una revisión coincidente.


La secuencia canónica **captura privada → probe** completó a
`2026-10-05T07:09:09.483920+00:00` con agent-browser 0.26.0 (collector) y
CDP directo fijo (probe): todos los checks PASS. El cap NanoCpus medido
tras collect y tras probe fue exactamente **250000000**; el wrapper sólo
prestó 0,50 CPU mientras poseía ambos locks. Cleanup terminal exit 0,
browser instalado dcf98b8 detenido. El ensayo usó la imagen ed39afc con
los dos archivos de transporte candidatos; aún no prueba el release final
ni suma un rehearsal importado. No requiere promover el CLI experimental.


Revisión previa al release: los drills browser/combined también reservan
privado/capacidad antes de cualquier outage, heredan FD9/FD8 para el préstamo
acotado de las lecturas y limitan cada captura a 45 s. Contención retorna 75
sin caída; replay de un drill ya importado conserva su salida previa a los
locks. Seis regresiones adicionales PASS; suite **2.025 passed, 1 skipped,
79 deselected**, 37,24 s. Los nuevos drills físicos siguen pendientes del
release final; esta suite no se presenta como evidencia de recuperación real.


## Release final acd84a9 — en verificación

PR195 integrada `2026-10-05T07:15:57Z`, SHA completo
`acd84a9c3241bc93b9860dc732d7f57dd189484b`; CI 37276568318 PASS,
1 min 15 s. Build `mova-fpl-build-acd84a9` terminal active/exited, exit 0.
Engine `sha256:98a0326933097fb88a4c4d45b1c8431ed32ab51ce96ba0bba70d7602e53d2fda`;
browser `sha256:1b41d333be3f7d845c2db3a003bfdfee77ba7fc4526fc737e0a2de09744785bf`;
research `sha256:3cb9da6188dc7ed2f7339c561a96a5ee696abcc1fcd54ea955d953389b59c180`.
Smoke aislado sin red/auth/datos productivos: diez checks PASS.

Primer cutover: `mova-fpl-release-acd84a9` terminó exit 28. La API devolvió
un readiness válido en el loop de arranque, pero la comprobación inmediata
siguiente agotó 2 s. El endpoint conserva `OpsDB.quick_check()`; no se cambió
ni se sustituyó por healthz. Rollback automático de código/configuración
verificado: checkout y labels dcf98b8, API running/healthy, cero restarts,
browser detenido y diez timers activos. Readiness posterior 200, 1,120 s;
dos muestras adicionales 1,121/1,484 s. Migraciones nuevas aplicadas: cero.
No se reemplazaron bases. El rollback pasó de disponible a ejercitado en
esta incidencia; no demuestra reconstrucción ni reboot.

Segundo intento usa un backup SQLite distinto (idempotency `release-acd84a9-backup-02`)
y nuevo backup PG. La aceptación de arranque sigue el timeout 5 s del healthcheck
existente, exige tres respuestas 200 consecutivas y tiene reloj global 180 s.
No altera los 30 min predeclarados de estabilidad **posteriores al último drill
disruptivo del SHA final**; no reutilizar la ventana de dcf98b8 ni acortarla.
El segundo intento está en `mova-fpl-release-acd84a9-attempt2`; no se reinicia
mientras siga activating/start. DR de los cinco escenarios e import de probe
sobre el SHA final continúan pendientes hasta su aceptación física.


Segundo intento terminal active/exited, exit 0: runtime **acd84a9**, status
healthy, controles exactos shadow/A0/kill true/writes false/compliance pending.
Tres readiness consecutivos 200: **1,331845 / 2,783886 / 1,493985 s**;
la muestra de 2,78 s confirma el riesgo del límite de cliente anterior de 2 s.
Override idéntico y timers restaurados. CI main 37276778873 SUCCESS.

Probe final `2026-10-05T07:35:44.002910+00:00`, unidad
`mova-fpl-browser-proof-acd84a9`, terminal exit 0. Captura privada ingested en
`job_5d580a7464e64d958ab5da825a9f2fdc`. Todos los checks de cancha/capitanía
PASS, GET final sin cambios. El inbox privado conserva el source; no se publica
su contenido. Imports del ciclo real **2026-27-gw06**, R2 **2026.10.2**:

| Capacidad | Rehearsal | Hash de evidencia sellada | Modo |
| --- | --- | --- | --- |
| captaincy | rehearsal_8af6285e4047cfa8680a7598 | 89a823b6908e0500755a7f841528f3aa939a752c53ccb4d8bee2c63852afb790 | read_only_probe |
| lineup | rehearsal_a4e4ab3959a4ec808cca304d | c36b7918540f8c628daddd65362b7b90fc2db75f9ea3a99199f3671b37a2cf28 | read_only_probe |

Cobertura **1/3 por capacidad**, no tres por repetir GW6. No Save ni cambios
FPL; CPU restaurada a 250000000 NanoCpus y browser detenido. H11 ya tiene
contrato DOM y lectura física válida; esta evidencia no prueba el transporte
de escritura ni aceptación de commit/reload/post-state bajo autoridad.

API recovery final 07:37:37–07:38:02 UTC: **5/5 PASS, downtime 25 s**,
job `job_381393fac3d445ffbb632f3efbab312b`, evidencia
`6fc9371b65cdd96cb7cdeecbb9e84dfe5ff1de7c9775dc1098d6c84b3a3a9e99`.
PostgreSQL, browser, combined, offsite y ventana final siguen en ejecución/
verificación secuencial; no reutilizar sus proofs de la revisión anterior.


PostgreSQL recovery final 07:42:54–07:45:34 UTC: **8/8 PASS**, endpoint
caído **19 s**, job `job_1dd68e3f59e44b199183194bbeda5242`, evidencia
`bd17d7a274e4ae2caa3328fa66df353164a4795cc2cf87ab010a4102dd0464d5`.
Browser recovery 07:48:16–07:50:34 UTC: **9/9 PASS**, endpoint caído
**17 s**, job `job_129b6b8dfab84fd8bf62b3c31d854d57`, evidencia
`07daa8f4776b0c61830d32fb90c9b404b9038528dd2c81a5f863be38531e5ab5`.
Autenticación y fingerprint del equipo antes/después coinciden; controles A0
conservados, revisión acd84a9 y browser inicial detenido restaurado.


Combined recovery final 07:53:06–07:57:28 UTC: **13/13 PASS**, endpoint
conjunto caído **57 s**, job `job_98dcf0cd4d964f138675aa6fa61e75f5`, evidencia
`998568d9251d52b6038732fa6183a1378474a576bb6be08ae943471d33cb304e`.
API/PG/browser restaurados, sesión y equipo sin cambios, browser vuelto a su
estado inicial detenido y controles A0. Es el último drill disruptivo previsto.
La ventana nueva exige 1.800 s posteriores, cuatro muestras programadas
0/5/15/30 min de status/doctor/workflow/readiness/caps/restarts/OOM, y un tick
completed con finished_at posterior al inicio. El restore externo aislado
puede correr dentro de esa ventana: no provoca una caída de servicios.
