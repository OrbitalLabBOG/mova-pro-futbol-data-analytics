---
type: audit-and-iteration
name: MOVA FPL — auditoría del harness y programa de cierre
created: 2026-10-04
status: implementation-in-progress
owner: julian
---

# Auditoría e iteración de cierre

## Goal y alcance

Auditar código, runtime, logs, skills y updates; cerrar los gaps resolubles en
código y operación A0; preparar la aceptación que requiere ventanas reales,
reautenticación supervisada o autoridad separada. El goal permanece activo
mientras falten cambios y verificación de esta iteración. No promete que todas
las condiciones de autonomía puedan cerrarse durante una pausa de calendario.

La hoja de ruta sigue siendo [readiness y rollout](../../specs/fpl-autonomous-operator/04-readiness-and-rollout.md).
Este documento registra hallazgos y el orden de trabajo; no crea tareas PM,
cambia responsables, aumenta presupuestos ni promueve controles.

Skills revisadas: entrada `proyecto`, adaptador MOVA FPL de Orbital OS,
AGENTS y skill canónica/adaptador nativo del proyecto, PM y Supabase para
seguimiento. La cadena de fuentes y los límites de reboot/escrituras están
explícitos. La skill resumida dice “tres GWs” pero el runbook/código exige
todas las históricas medidas passing; el expediente de H08 debe reconciliar
esa explicación antes de anunciar una ruta de aceptación viable.

## Corte vivo

Cockpit generado `2026-10-05T02:58:24+00:00` (4 de octubre, 21:58 Bogotá):

- VPS `4917df0`; Git `main` incorpora PR190 (`3a620d1`), todavía no desplegada.
- Readiness 19 pass, 5 pending, 3 blocked; `attention_required`.
- A0/shadow, kill switch activo, browser writes deshabilitadas.
- Último tick completed, cero jobs fallidos de ops en el listado de 24 h;
  un incidente abierto, cero P0/P1. Una corrida de una fuente puede fallar
  mientras el job global termina degraded; son ledgers distintos.
- Analytics healthy y PostgreSQL healthy; data service degraded.
- Researcher 1.10.0 activo, Astra/medium. 1.12.0 es candidato registrado.
- Research medido: cuatro GWs, cero passing. Último import operacional del
  22 de septiembre: 48% cobertura/evidencia. Un estado imported/complete no
  prueba vigencia ni calidad para la siguiente ventana.
- Cola íntegra; ventana de research abre el 9 de octubre a las 05:00 Bogotá.
- GW: 2.310.934 tokens y 24 usos restantes. Pareado necesita 3M y tres usos
  contando reserva operacional: faltan 689.066 tokens. No se encoló.
- Rehearsals: capitanía 0/3, lineup 0/3, R3 1/3. Closeout v2 vivo: cero.

Logs del collector: `ingest_d07e4ce1f0484b528af1ce352d812267`, 4 de octubre
20:30:52–20:32:37 UTC, falla mensual `25544/202703: HTTP 403`. El código descubre
el stage del sitio; no es un ID de stage fijo en configuración. El log demuestra
el rechazo HTTP, no su causa del lado del proveedor. FPL/odds y eventos siguen
operando; eventos conserva 50/50 cobertura sobre partidos finalizados.

DR: reporte `2026-10-05T02:02:49.087192+00:00`, seis checks pass; backups
SQLite/PG `20261004T222410Z`/`20261004T222420Z`, snapshot externo
`a4e2f53285be`, upload `22:28:11 UTC`. Edad de datos al medir 13.119 s.
Los cuatro escenarios de servicios y restore externo están ligados a 4917df0.
Reboot pendiente de evidencia válida; reconstrucción desde host vacío no probada.

Supabase leído por conector: último update `2026-09-29T04:43:40.775899+00:00`;
current_status describe 7144cdd. AC01/02/03 siguen in_progress; AC04 blocked por
`FPL_CAPTAIN_CHECKBOX_MISSING`; AC05/08 abiertos y AC09 todo. Varias notas
históricas conservan cifras anteriores. No usar esas notas como estado vigente.

### Recuperación operacional durante la auditoría

Un único `collect schedule --force`, actor `julian`, razón de auditoría,
idempotency `harness-audit-20261004-schedule-recovery-01` completó en
`job_aa096610153c4a93975c12d86d04060a`. Descubrió 380 partidos, 380 IDs únicos
y 50 finalizados; fetch 114.803 ms de duración según el campo `duration_ms`
(114,803 segundos). El 403 anterior puede ser transitorio; el retry exitoso
no demuestra su causa del lado del proveedor ni una solución permanente.

Corte posterior `2026-10-05T03:10:59+00:00` (4 de octubre, 22:10 Bogotá):
doctor exit 0, 24 PASS/0 WARN/0 FAIL; operator/data/analytics/PostgreSQL healthy;
cero incidentes; readiness 21 pass/5 pending/1 blocked; safety y workflow
safe_to_wait, sin violaciones. Runtime sigue 4917df0 y controles A0 intactos.
La corrección local de caché y el nuevo sensor DR no causaron esa recuperación:
no están desplegados. El reintento usó el collector previamente instalado.

## Hallazgos de código y contratos

| ID | Hallazgo / evidencia | Consecuencia y cierre |
| --- | --- | --- |
| H01 | `collect_schedule` sustituye caché antes de `validate_schedule` | Validar antes de publicar. Una respuesta parcial no puede contaminar eventos. |
| H02 | `cursor_is_due` espera la cadencia completa desde un fallo: 24 h para calendario | Diseñar retry de lectura por clase de error, bounded y con cooldown; el 403 no autoriza evasión ni retry continuo. Mantener health degraded hasta fetch completo válido. |
| H03 | `doctor.recent_backup` selecciona cualquier directorio por mtime, umbral 36 h | Puede escoger releases o postgres y reportar frescura falsa. Usar edad del snapshot y RPO 7 h del reporte del host. |
| H04 | DR JSON horario no entra a status/cockpit/watchdog | Proyección allowlisted; edad sigue avanzando entre reportes, expiración 90 min, revisión exacta, P1 deduplicado y resolución sólo tras observación vigente. Ningún pass prueba reconstrucción total. |
| H05 | PR190 agrega guías al workflow; cockpit descarta timing/recovery | Exponer ambos contratos y desplegar. Sigue siendo orientación; no declarar recuperación automática por esa guía. |
| H06 | `attention_required` se titula “Operación estable con pendientes” | Mostrar que la operación requiere atención, con causas visibles. |
| H07 | Research completo en workflow significa imported, aunque sea viejo o parcial | Separar terminalidad, aplicabilidad al manifest y calidad/frescura. Antes del próximo slot, mostrar refresh pendiente sin falsear el import histórico ni disparar trabajo fuera de ventana. |
| H08 | `research_coverage` exige que pase cada GW medida de todo el historial | Tres GWs nuevas passing no satisfacen el criterio actual. Preparar decisión versionada de cohorte futura; conservar fallos y conflictos históricos, preregistrar versión/policy/GWs. Sin aprobación del contrato, no cambiar gate ni backfillear evidencia. |
| H09 | `strategy.due` no repite un slot ya intentado, incluso si terminó rejected/failed | Recuperación agentic requiere contrato auditable: distinguir fallo antes de inferencia, inferencia con consumo incierto y rechazo de contenido. Reserva y permiso nuevos sólo dentro del slot, capacidad y límite de intentos. |
| H10 | Guard lógico observa consumo después de eventos del proveedor | Es reactivo; no garantiza corte físico en el límite. Recibos, charge conservador al cancelar, límites de salida/contexto y reserva deben reflejar esa limitación. No cerrar overruns originales con un job de límite elevado. |
| H11 | Browser R2 bloqueado por contrato físico de checkbox | Inspección sanitizada de UI actual y semántica de controles; corregir adapter sólo con evidencia. No reemplazar “checkbox ausente” por heurísticas que permitan Save. |
| H12 | Updates PM y algunas notas del programa están desfasadas del runtime | Preparar corte nuevo tras release verificable; mantener notas históricas, estados abiertos y IDs existentes. No cerrar ACs por instalar cambios. |
| H13 | `AgentBrowser.run` usa subprocess sin timeout; wrapper R2 invoca driver/captura sin timeout explícito | Lease/cutoff de begin no acota una llamada ya bloqueada. Establecer un deadline absoluto compartido y tiempo máximo por llamada, reservar post-state y finalizar ambiguo tras apply sin repetir Save. |

## Iteración completa por paquetes

### 1. Datos y observabilidad — AC01/03/07

Cerrar H01/03/04/05/06, definir retry H02 y volver a recolectar únicamente
calendario con actor/reason/idempotency. Si sigue 403, conservar incidente y
última caché válida; registrar la dependencia externa. La causa del proveedor
no puede darse por solucionada con un cambio de health o una caché antigua.

Aceptación: caché intacta ante calendario inválido; reportes missing, malformed,
stale, future, fuera de RPO o de otra revisión nunca pass; reloj de edad de
backup sigue corriendo; una falla persistente produce un único incidente y
un reporte fresco válido lo resuelve; status, doctor y cockpit concuerdan.

### 2. Recuperación de ciclo — AC03

Inventariar cada excepción contra scheduler/worker/host entrypoint, no contra
la guía. H07 añade proyección; H09 ya tiene recuperación física acotada. Verificar límites: entrada,
resultado terminal, cutoff, cooldown, máximo de intentos, reserva/permiso,
idempotency y alerta. Auth expirada escala para login supervisado. Save
ambiguo exige post-state y ledger; jamás retry automático de confirmación.

Aceptación: no dos requests/reservas para el mismo intento; reinicio no deja
worker o autorización huérfanos; ninguna recuperación agenda una decisión
vencida; budget insuficiente termina sin inferencia; salida inválida queda
sellada/quarantined. Los escenarios herméticos validan contratos, no AC08 vivo.

### 3. Calidad y economía — AC02

Terminar expediente H08/10, protocolo pareado existente con manifest fresco,
misma entrada y máximo de exposición por brazo; admisión preserva un job
operacional completo también frente a encolados concurrentes. No elevar
allowance para hacer caber el experimento. Resolver conflictos sólo con
documentos originales fechados/verificados; insuficiencia es un resultado.
H08 tiene una [propuesta ADR-011](../../specs/fpl-autonomous-operator/decisions/ADR-011-prospective-research-acceptance.md)
para una cohorte prospectiva inmutable por contrato. No aprobada ni aplicada;
no cambia gates ni declara resueltos conflictos históricos.

Aceptación: contrato longitudinal predeclarado; releases comparables, mismos
model/effort/schema/budget; conservación de sujetos baseline aceptados; recibos
completos y metering coherente; utilidad causal separada de cobertura. Tres
GWs independientes reales y deliberación sobre envelope vigente siguen siendo
evidencia futura, no resultado del experimento ni del replay.

### 4. Browser — AC04/05

H11/13 primero: lectura DOM sanitizada, contrato capitanía y lineup, adapter
productivo sobre UI observada. R3 conserva dependencia de R2; revisar tiempos
acotados de cada llamada del driver y del wrapper antes del apply boundary.
La ausencia de un control debe bloquear precommit. Timeout/crash tras aplicar
se clasifica ambiguo y se reconcilia antes de cualquier otra confirmación.

El ledger exige tres ciclos/GWs distintos por capacidad y versión; sus probes
browser read-only/validate-only sí cuentan para los gates de capacidad cuando
cumplen el contrato, pero no prueban guardado. La aceptación de ejecución
controlada exige adicionalmente pre-state/preview exactos, una sola confirmación,
reload y post-state. El montaje manual no suma rehearsals del driver. Entry point
y autoridad se habilitan explícitamente después de la evidencia aplicable.

### 5. Release, recuperación y skills — AC01/06/07

Consolidar cambios en main, CI, SHA/digest/override inventariados, backup,
rollback y doctor; predeclarar ventana de estabilidad sobre la revisión final.
Desplegar guías y sensor DR juntos. Renovar pruebas DR para el nuevo SHA:
las pruebas de 4917df0 no pasan automáticamente a otro release.

Reboot: preparar de nuevo y pedir autorización explícita separada según la
skill; el sello anterior expiró. Host vacío: restauración completa con artefactos
de auditoría externos, auth supervisada y medición RTO. Preparar recursos y
procedimiento no acredita su ejecución. No abrir nuevo host ni coste por este
documento. Mantener alertas reales dedup/retry, sin confundir entrega y lectura.

Actualizar skill canónica del proyecto y adaptar Orbital OS sólo donde corresponda.
No duplicar contratos ni anunciar tools web nuevas. PM se reconcilia con el
corte vivo posterior, conservando responsables/colas y todo el historial.

### 6. Expediente y jornada completa — AC08/09

Preparar matriz por AC/capacidad/versión/GW/SHA; evidencia disponible, faltante
y acción de desbloqueo. Compliance, A1/A2/A3 y límites deportivos son decisiones
explícitas registradas. AC08 exige una GW posterior a promoción hasta review y
siguiente ciclo sin comandos de rescate. No puede cerrarse antes de esa GW.

## Implementación y verificación local

H01/02/03/04/05/06/07/13 implementados en la rama de esta iteración.
Validación final completa: **1.972 passed, 1 skipped, 79 deselected** en
33,22 s con la configuración canónica (excluye slow/integration_data).
Compilación Python, `bash -n`, `docker compose config --quiet` y
`git diff --check` pasan. Respuestas begin perdidas (backend claimed/applying),
fracciones de tiempo futuro y proyección DR incluidas en esa suite.
El contenedor browser desplegado tiene `/usr/bin/timeout`.

| Gap | Cierre local / límite de aceptación |
| --- | --- |
| H01 | Caché se publica tras validar; payload inválido conserva bytes anteriores. |
| H02 | Retry read-only 5xx/timeout/conexión: 15/30 min; desde tercero, cadencia normal. 403/429/calidad/desconocidos conservan cadencia; odds separado. |
| H03/04 | Sensor DR allowlisted, RPO 7 h, edad avanza, máximo 90 min y revisión comprobada. Doctor/cockpit/status y P1 dedup/resolución usan la misma observación. |
| H05/06 | Cockpit conserva contratos timing/recovery/evidence y título attention_required. |
| H07 | Import terminal, edad, ratios, política y match de manifest aparecen separados. No se alteró vigencia ni admisión. |
| H08 | ADR-011 propuesta, no aprobada. Gate actual y evidencia histórica intactos. Requiere decisión de Julián y jornadas prospectivas reales. |
| H09 | Auditoría posterior identifica `AgentAttemptService`: máximo dos intentos físicos operacionales, permiso/reserva preintento, recibos inmutables, cutoff y quarantine/terminalización por agotamiento. Experimento fallido admite uno. No se duplicó scheduler; rechazo de contenido permanece terminal. |
| H10 | Guard reactivo sigue siendo limitación física del proveedor. Recibos y charge conservador existentes no se confunden con hard cap. Follow-up equivalente original y capacidad disponible siguen pendientes. |
| H11 | Lectura VPS intentada sin Save; timeout de navegación impidió alcanzar los controles. No se cambió selector con evidencia insuficiente. Doctor de agent-browser: 6 pass/1 warn/0 fail; limpió archivos de un daemon terminado. No acredita controles ni rehearsal. |
| H12 | Skill/runbooks actualizados; identidad SSH de skill web corregida a ubuntu. Corte PM vivo conserva estado del 29/09: preparar update verificable posterior a release. |
| H13 | Gate T−15m, lease truncada, reloj compartido driver, timeout dentro/fuera del contenedor y reserva 30 s. Respuesta begin perdida se clasifica atómicamente sin despachar Save; no repite confirmación. Driver versionado 2026.10.1. |

Estos resultados son locales, **no desplegados**. Las pruebas herméticas no suman
rehearsals reales ni sustituyen aceptación de runtime. El nuevo driver no hereda
rehearsals de otra versión. El sensor DR añade salud/P1, no autoridad ni un nivel
nuevo. Release, smoke de imagen, estabilidad y nuevos drills ligados a SHA final
permanecen pendientes.

## Límites del cierre

Mientras dure esta iteración: shadow/A0, kill switch on, writes off. Preparar
promoción y cambiar software no equivalen a promover. El objetivo es eliminar
dependencia humana rutinaria, manteniendo escalamiento real para auth,
proveedores, ambigüedad y autoridad. Toda aceptación pendiente debe conservar
causa, evidencia y próximo evento verificable; no se rellena con documentación.


## Corte técnico posterior — 5 de octubre de 2026

La continuidad detallada se conserva en [acta de release](harness-release-20261004-dcf98b8.md).
PR191 instaló los ocho cambios de datos/observabilidad/recovery/clock en dcf98b8;
PR192/194/195 incorporan estabilización de startup, stages, locks y transporte
read-only. PR195, acd84a9, pasó suite 2.025/1 skipped/79 deselected y CI.
Captura privada → probe física candidata PASS a 07:09 UTC, sin Save, con CPU
restaurada a 0,25. La revisión final se encuentra en aceptación de release/DR;
no describir aún esos cinco drills ni la estabilidad como completados.

PM consultado de nuevo por conector Supabase el 5 de octubre: proyecto
`cbd36dc4-0c1a-45ad-9134-1019e99639e4`, current_status continúa fechado
29/09 y describe 7144cdd. Epic `632a0e4c-e44e-4f98-b3ee-a1e2e357b63f`
sigue in_progress. R2 `e716c251-bdd3-4ee4-957a-e553d300104f` conserva blocked
por checkbox missing; research `b14c9d93-5175-4645-b6ed-328dc2d34f1f`,
continuidad `7a0397a3-56c5-46da-9567-db28007a113a`, release
`6aea32b2-b1d7-4dfb-9b80-fc92352da8af` y jornada completa
`7dca6314-9b77-460e-a126-11b852e86ef4` siguen in_progress; promoción
`4a5e96b3-c7a9-4d8b-979a-0ce3ca65643b` todo. No hubo escritura PM.

Preview del próximo update: sustituir el motivo DOM ausente por el corte
físico final y su cobertura real, sin cerrar R2 ni tareas longitudinales.
Conservar responsables, colas, fechas y porcentaje; enlazar acta/SHA/CI/DR.
El transporte read-only satisfactorio no prueba el cliente de escritura,
Save/recarga/post-state ni promoción. Preparar publicación sólo con el corte
final verificable; este texto no es un update ya enviado a Supabase.
