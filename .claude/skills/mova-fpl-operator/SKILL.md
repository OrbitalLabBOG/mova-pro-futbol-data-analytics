---
name: mova-fpl-operator
description: "Operar, diagnosticar y explicar el harness autónomo MOVA FPL mediante el CLI mova, sus contratos JSON y los runbooks del VPS. Usar para salud, datos, modelos, equipo, controles, jobs, incidentes o despliegue; no usar para escoger jugadores ni para hacer clicks en FPL."
metadata:
  vertical: mova
  type: skill
  repo: mova-pro-futbol-data-analytics
  updated: 2026-08-31
---

# MOVA FPL Operator

Opera el control plane a través de su fachada versionada. En el VPS usa `/usr/local/bin/mova`;
en desarrollo usa el console script del entorno editable. No abras SQLite directamente para una
consulta ordinaria: `mova` y `/api/v1/status` son el contrato estable.

## Orientación mínima

1. Lee `AGENTS.md` del repo.
2. Ejecuta `mova status --json`, `mova readiness`, `mova harness scorecard` y
   `mova harness workflow`; conserva `schema_version`,
   `generated_at`, `overall_status` y `activation.technical_eligible_level` al reportar.
   `readiness` separa capacidad técnica de autoridad: nunca interpreta elegibilidad como
   promoción. Usa `mova readiness --require-level A1|A2|A3` como gate automatizable; exit 2
   significa evidencia insuficiente, no un permiso para rebajar requisitos. El scorecard une
   calidad, costo, aprendizaje y roles sin crear policy nueva. `blocked` exige atención;
   `pending` puede ser evidencia temporal pendiente. Nunca confundas su `readiness_pass_ratio`
   con probabilidad de éxito ni con permiso de ejecución.
   El workflow explica el orden de Researcher → Optimizer/Validator → Strategist/Critic →
   Policy → Executor/Verifier → Reviewer. Un stage `complete` con outcome `blocked` y un
   `execute_verify=skipped_policy` es fail-closed correcto; una fila en `violations` sí es una
   contradicción operativa y bloquea. `runtime_mutated=false` debe permanecer explícito.
3. Si el estado es degradado, incompleto o contradictorio, ejecuta `mova doctor --json`.
   Para una respuesta compacta usa `mova safety` o `/api/v1/safety`: `unsafe` exige atención
   inmediata, `attention_required` exige leer `reasons`, y `safe_to_wait` sólo describe el estado
   observado; nunca eleva permisos ni reemplaza `readiness`.
4. Lee [docs/operations/operator.md](../../../docs/operations/operator.md) para interpretar
   el contrato y [docs/operations/vps.md](../../../docs/operations/vps.md) solo si hay que
   desplegar, revisar systemd, backups o browser.
5. Para recolectar, revisar cobertura o diagnosticar FPL/odds/WhoScored, lee
   [docs/operations/data-service.md](../../../docs/operations/data-service.md).
6. Para entrenar un candidato, proyectar, explicar, reconciliar una GW o interpretar
   scorecards/drift, lee
   [docs/operations/analytics-service.md](../../../docs/operations/analytics-service.md).
   Usa `mova model status|train|predict|explain|evaluate`. `train` debe devolver
   `runtime_mutated=false`: jamás copies el candidato al bundle activo ni omitas el release gate.
7. Para cerrar una GW, atribuir una intervención y registrar feedback, lee
   [docs/operations/gameweek.md](../../../docs/operations/gameweek.md). Ejecuta `mova review gw`
   solo con `finished + data_checked`, package versionado, actor, razón e idempotency key.
8. Para activar un plan, sellar el manifiesto o investigar noticias, lee
   [docs/operations/strategic-research.md](../../../docs/operations/strategic-research.md).
   Verifica `mova strategy status.memory_summary`: debe provenir de GWs anteriores y lecciones
   validadas; nunca se reemplaza con historial de chat. El brief de Codex es candidato hasta que
   el importador determinista lo valide. Consulta `mova strategy research coverage`: un brief v2
   exige fetch independiente, locator sellado y cobertura exacta del foco; v1 es legacy no medido.
9. Para clasificar riesgo, sellar un diff o diagnosticar un bloqueo previo al browser, lee
   [docs/operations/execution-preflight.md](../../../docs/operations/execution-preflight.md).
   `mova execute` conserva preflight, lease apply-once y verifier; `execute ui-plan` sólo compila
   DOM después del claim. Consulta `mova execute status.browser_driver`: capitanía tiene entrypoint
   pero no autonomía promovida; XI/banca tiene contrato tipado con entrypoint deshabilitado hasta
   rehearsals; R3 y controles DOM no probados permanecen fail-closed.
   Para registrar cobertura browser viva de XI/R3 usa `mova execute rehearsal-capability-probe`
   únicamente sobre probes sanitizados generados por el host. Esto no prueba el commit ni promueve
   entrypoints, autonomía o controles.
10. Para revisar propuestas, uso/costo, memoria validada o releases de modelos, lee
    [docs/operations/continuous-improvement.md](../../../docs/operations/continuous-improvement.md).
    `mova improve transition` nunca aplica la hipótesis al runtime. El único aplicador soportado es
    `mova improve release` para bundles `minutes+points`, tras shadow pareado; no sirve para código,
    guardrails ni permisos. Antes de encolar trabajo agentic,
    consulta `mova cost report`; un exceso agregado o reserva huérfana es un bloqueo real y no se
    fuerza. Un `job_overrun_observed` histórico exige revisar prompt/budget con evidencia, pero no
    se presenta como exceso agregado mientras GW y mes sigan `within_budget`. Registra la
    revisión con `mova cost overrun --reservation-id ... --to reviewed --action ... --actor ...
    --reason ... --idempotency-key ...`. No uses `waived` automáticamente ni declares
    `resolved` sin `--followup-reservation-id`: la base exige una corrida posterior equivalente,
    liquidada y dentro del límite.
    Revisa `semantic_reuse.*_avoided_uses` y `/api/v1/deliberation-bindings` cuando la
    deliberación parezca repetitiva. Un binding `semantic_reuse` es éxito idempotente: no vuelvas
    a encolar ni borres el ledger para forzar otra llamada.
    `mova review auto` solo procede con settlement final y scorecard baseline; `not_ready` es el
    resultado correcto para una GW preliminar.
11. Para diagnosticar persistencia, ejecuta `mova postgres status` y `mova postgres verify`, y
    lee [docs/operations/postgres-shadow.md](../../../docs/operations/postgres-shadow.md).
    `storage.read_parity=pass` requiere hashes de contenido, no solo conteos. El gate de tres
    ciclos usa GWs distintas extraídas de las claves auditadas; snapshots y reintentos dentro de
    una misma GW no cuentan. El writer sigue siendo SQLite hasta que los gates de ciclos, backup
    off-host y cutover/rollback se aprueben.
    `mova postgres drill` prueba únicamente el cutover/rollback de lectura sobre snapshots
    sellados; un pass no cambia el writer ni autoriza promoción.
    Antes del drill, `mova postgres roles` debe mostrar separación `pass`: owner para
    migraciones/imports, app sin DELETE y readonly con transacciones read-only por defecto.

`status` no prueba red ni muta estado. `doctor` hace checks acotados y un único GET público a
FPL; usa `--no-network` cuando la ejecución deba ser hermética. Un `FAIL` requerido devuelve
código 1 y bloquea decisiones o despliegues dependientes. Un `WARN` se declara y se evalúa por
contexto; nunca se presenta como `PASS`.

Las alertas se consultan con `mova alerts status`; `mova alerts channel` muestra si el destino
externo está `configured`, `local_only` o `invalid` sin revelar URL ni token. El watchdog entrega
automáticamente las pendientes usando leases y retry: conserva journald y, sólo si el secreto
opt-in es válido, exige también un webhook HTTPS. Una entrega `sent` no equivale a acuse humano. Para
reconocer un incidente usa `mova alerts acknowledge --incident-id ... --actor ... --reason ...`.
No marques como resuelto lo que sólo fue reconocido. Para revisar basura transitoria usa `mova
maintenance cleanup`; el modo normal es dry-run. `--apply` exige actor, razón e idempotency key y
nunca debe ampliarse a formatos de evidencia.

Un watchdog `down` abre y entrega un P0 deduplicado; `degraded` significa que el heartbeat puede
estar sano pero la entrega falló o existe un evento `dead`. Tras reparar el sink usa `mova alerts
retry --outbox-id ... --actor ... --reason ...`; nunca reintentes un evento `sent` o
`acknowledged`. Para comprobar la ruta sin falsificar un incidente vivo ejecuta `mova drill
resilience` con actor, razón e idempotency key. El resultado válido declara
`runtime_mutated=false` y todos sus checks en true. `mova readiness` debe reflejarlo como
`RESILIENCE_DRILL_PROVEN=pass`; un acta Markdown no sustituye ese job.

Antes de A1 ejecuta `mova drill alert-channel --actor ... --reason ... --idempotency-key ...`.
Debe declarar seis checks, `external_calls=0` y `runtime_mutated=false`. Ese pass cubre el
adaptador, no un destino real: `EXTERNAL_ALERT_CHANNEL_CONFIGURED` sólo pasa cuando un owner y un
webhook autorizado están provisionados en `/etc/mova-fpl/alert-webhook.json` y ensayados en vivo.
No copies esa URL a logs, Git, actas o argumentos de proceso.

Después de provisionar el secreto ejecuta una sola vez `mova alerts test --actor ... --reason
... --idempotency-key ...`. Debe devolver `pass`, `delivered=true`, un outbox `sent` y el
fingerprint mostrado por `mova alerts channel`. Replay exacto debe ser `reused` con
`external_calls=0`; nunca cambies la clave sólo para ocultar un fallo. La prueba reclama únicamente
su P3 y no debe despachar alertas vecinas. Si falla, repara el sink, deja que el outbox conserve
retry y usa una clave nueva para producir evidencia limpia. Readiness sólo pasa
`EXTERNAL_ALERT_CHANNEL_LIVE_PROVEN` para el fingerprint actualmente configurado.

El chaos drill real del API se ejecuta exclusivamente desde el host con
`deploy/bin/api-recovery-drill.sh ACTOR REASON IDEMPOTENCY_KEY`; no improvises `docker stop` sin
su trap. El script importa evidencia mediante `mova drill import-host`. Confirma después
`doctor`, revisión checkout/imagen, watchdog y paridad PostgreSQL. Este drill no cubre DB,
browser, DOM, save ambiguo ni reboot.

La caída real de PostgreSQL usa exclusivamente
`deploy/bin/postgres-recovery-drill.sh ACTOR REASON IDEMPOTENCY_KEY`. El script toma todos los
locks de writers, conserva API/SQLite, verifica el fingerprint privado y exige paridad posterior;
exit 75 significa que difirió sin detener el servicio. `mova readiness` sólo pasa
`HOST_RECOVERY_DRILLS_PROVEN` cuando API y PostgreSQL tienen jobs canónicos aprobados. El drill no
prueba snapshot corrupto, DOM/save ambiguo, combinación de fallos ni reboot.

La recuperación real del perfil browser usa exclusivamente
`deploy/bin/browser-recovery-drill.sh ACTOR REASON IDEMPOTENCY_KEY`. Sólo es válida con controles
fail-closed A0; realiza lecturas autenticadas antes/después, prueba noVNC/CDP indisponibles,
conserva el fingerprint privado y restaura el estado inicial on-demand. No captures ni copies su
estado temporal. Readiness exige los aislados y el combinado en `HOST_RECOVERY_DRILLS_PROVEN`.

El outage conjunto usa `deploy/bin/combined-recovery-drill.sh ACTOR REASON IDEMPOTENCY_KEY` y
requiere backup previo. Detiene API+PostgreSQL+browser bajo locks, conserva SQLite, recupera los
tres y compara paridad/fingerprints. `HOST_RECOVERY_DRILLS_PROVEN` exige cuatro escenarios:
API, PostgreSQL, browser y combinado. Replay/conflict debe resolverse antes de pedir locks de
servicio; si un replay retorna 75, hay drift del wrapper y no debe improvisarse otro outage.

Para probar snapshot inválido usa `mova drill snapshot --actor ... --reason ...
--idempotency-key ...`. Es hermético y debe declarar diez checks, `fixture_only=true` y
`runtime_mutated=false`; no improvises corrupción sobre `postgres-imports/`. Readiness sólo pasa
`SNAPSHOT_REJECTION_PROVEN` con un job completado y no acepta una nota Markdown como sustituto.

Para ensayar deriva DOM y save ambiguo usa `mova drill browser-failure --actor ... --reason ...
--idempotency-key ...`. Debe declarar al menos diez checks completos, `fixture_only=true` y
`runtime_mutated=false`; no abre el browser ni autoriza clicks. Confirma después
`BROWSER_FAILURE_DRILL_PROVEN=pass`, `doctor`, `safety` y los controles A0 intactos. Esta evidencia
no aumenta los contadores de rehearsals vivos.

Para comprobar el grafo agentic sin gastar tokens ni fabricar una GW usa `mova drill
orchestration --actor ... --reason ... --idempotency-key ...`. Debe pasar al menos doce checks,
declarar `external_calls=0` y `runtime_mutated=false`. Replay exacto reutiliza el job; la misma
clave con actor/razón distintos es conflicto. Este drill prueba policy y dependencias, no cuenta
como research, rehearsal browser, settlement ni aprobación de autonomía.

## Fuentes de verdad

- Git: código, contratos, configuración de ejemplo, skills y runbooks.
- VPS: estado operativo, bases, artefactos, backups, logs y browser persistente.
- `ops.db`: ledger y writer vigente hasta el cutover PostgreSQL explícitamente aprobado.
- Supabase: seguimiento PM exclusivamente; nunca runtime ni memoria del agente.

No confíes en un SHA documental si `status.runtime.git_sha`, el probe del checkout y la revisión
de la imagen discrepan. No declares un modelo disponible por estar mencionado en documentación:
`doctor.model_artifacts` debe verlo y posteriormente su release deberá estar registrado.

## Autoridad y seguridad

Consultar `status`, `doctor`, API de solo lectura, métricas y logs es lectura. `control`, deploy,
rollback, restauración y cualquier acción browser cambian estado y requieren que la petición los
autorice. Toda modificación de control exige `--actor` y `--reason`; no edites el env para saltar
el ledger.

El operador no elige jugadores. Para estrategia y modelos usa `fpl-expert`; para ejecutar una
decisión ya aprobada en la web usa `fpl-web-ops`. Con `kill_switch=true`, `shadow/A0`, compliance
pendiente o `browser_writes=false`, limita el browser a login y lecturas.

## Diagnóstico por síntoma

- `scheduler_heartbeat FAIL`: revisar timer, service y journald antes de lanzar otro tick.
- `autonomous_data_service FAIL/WARN`: ejecutar `mova data status`; aislar
  `fpl_official`, `football_data_odds`, `whoscored_schedule` o `whoscored_events` y revisar su
  último run. No fuerces `all` cuando basta reintentar una fuente.
- `private_team_state WARN`: refrescar por el collector autenticado; no sustituirlo por datos
  inventados ni tocar el perfil.
- `canonical_database`, `trace_database` o `model_artifacts FAIL`: bloquear una decisión basada
  en modelos hasta restaurar y verificar el componente.
- `analytics` sin scorecard: ejecutar `mova analytics status`; si la GW no está `data_checked`,
  esperar. `insufficient` durante las primeras seis referencias no es drift. Ante `alert`, leer
  `drift.reasons` y componentes antes de proponer reentrenamiento; no promover automáticamente
  una variante shadow.
- `deployment_revision WARN`: no asumir qué código corre; comparar checkout, imagen y SHA
  aprobado antes de reconstruir.
- `research_worker FAIL`: verificar timer, cola y presencia sanitizada del auth; nunca
  mostrar, copiar a Git ni incluir el archivo de autenticación en evidencias.
- research coverage parcial: inspeccionar `fetch_error_code`, `coverage.groups`, conflictos y
  sujetos `not_checked`; no convertir una cita de search en evidencia ni rebajar el gate multi-GW.
- propuesta de mejora atascada: consultar `mova improve status`; no saltar `testing`, no aceptar
  sin evidencia/rollback y no confundir una lección aceptada con un despliegue.
- release de modelo atascado: consultar `mova improve release status`; comprobar hashes, variante
  shadow y scorecards pareados. Nunca editar `active_model_bundle` con `mova control` para saltar
  el gate.
- `host_probe WARN`: usar el wrapper del host; no montar Docker socket o D-Bus dentro del engine.
- API FPL `FAIL`: conservar la última evidencia, declarar la pérdida de frescura y no forzar una
  corrida que parezca vigente.

`mova collect <fuente> --force` es una mutación del ledger y exige `--actor`, `--reason` e
`--idempotency-key`. El collector sólo lee fuentes externas; no concede autoridad para clicks o
escrituras en FPL. Código 2 significa corrida degradada y código 75 lock/cadencia conocida, no
éxito pleno.

`mova review gw` es una mutación post-settlement. Una GW sin batch inmutable predeadline solo
admite review retrospectivo; nunca backfillea `model_evaluation_runs`. Después del cierre puede
exportar ops/trace a PostgreSQL shadow mediante el import auditado, fuera del deadline.

Después de un cambio ejecuta la prueba cercana, `pytest -q`, smoke de Docker y nuevamente
`mova doctor --json`. Actualiza Supabase solo con evidencia ya verificada.
