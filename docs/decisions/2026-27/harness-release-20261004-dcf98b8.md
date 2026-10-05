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
