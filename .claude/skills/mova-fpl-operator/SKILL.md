---
name: mova-fpl-operator
description: "Operar, diagnosticar y explicar el harness autónomo MOVA FPL mediante el CLI mova, sus contratos JSON y los runbooks del VPS. Usar para salud, datos, modelos, equipo, controles, jobs, incidentes o despliegue; no usar para escoger jugadores ni para hacer clicks en FPL."
metadata:
  vertical: mova
  type: skill
  repo: mova-pro-futbol-data-analytics
  updated: 2026-08-30
---

# MOVA FPL Operator

Opera el control plane a través de su fachada versionada. En el VPS usa `/usr/local/bin/mova`;
en desarrollo usa el console script del entorno editable. No abras SQLite directamente para una
consulta ordinaria: `mova` y `/api/v1/status` son el contrato estable.

## Orientación mínima

1. Lee `AGENTS.md` del repo.
2. Ejecuta `mova status --json` y conserva `schema_version`, `generated_at` y
   `overall_status` al reportar.
3. Si el estado es degradado, incompleto o contradictorio, ejecuta `mova doctor --json`.
4. Lee [docs/operations/operator.md](../../../docs/operations/operator.md) para interpretar
   el contrato y [docs/operations/vps.md](../../../docs/operations/vps.md) solo si hay que
   desplegar, revisar systemd, backups o browser.
5. Para recolectar, revisar cobertura o diagnosticar FPL/odds/WhoScored, lee
   [docs/operations/data-service.md](../../../docs/operations/data-service.md).
6. Para proyectar, reconciliar una GW o interpretar scorecards/drift, lee
   [docs/operations/analytics-service.md](../../../docs/operations/analytics-service.md).
7. Para cerrar una GW, atribuir una intervención y registrar feedback, lee
   [docs/operations/gameweek.md](../../../docs/operations/gameweek.md). Ejecuta `mova review gw`
   solo con `finished + data_checked`, package versionado, actor, razón e idempotency key.
8. Para activar un plan, sellar el manifiesto o investigar noticias, lee
   [docs/operations/strategic-research.md](../../../docs/operations/strategic-research.md).
   El brief de Codex es candidato hasta que el importador determinista lo valide.
9. Para clasificar riesgo, sellar un diff o diagnosticar un bloqueo previo al browser, lee
   [docs/operations/execution-preflight.md](../../../docs/operations/execution-preflight.md).
   `mova execute` conserva preflight, lease apply-once y verifier; el driver de clicks continúa
   separado y sujeto a controles.
10. Para revisar propuestas, uso/costo o promover una hipótesis a memoria validada, lee
    [docs/operations/continuous-improvement.md](../../../docs/operations/continuous-improvement.md).
    `mova improve` nunca aplica la hipótesis al runtime.

`status` no prueba red ni muta estado. `doctor` hace checks acotados y un único GET público a
FPL; usa `--no-network` cuando la ejecución deba ser hermética. Un `FAIL` requerido devuelve
código 1 y bloquea decisiones o despliegues dependientes. Un `WARN` se declara y se evalúa por
contexto; nunca se presenta como `PASS`.

## Fuentes de verdad

- Git: código, contratos, configuración de ejemplo, skills y runbooks.
- VPS: estado operativo, bases, artefactos, backups, logs y browser persistente.
- `ops.db`: ledger vigente hasta el cutover PostgreSQL de HV1-02.
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
- propuesta de mejora atascada: consultar `mova improve status`; no saltar `testing`, no aceptar
  sin evidencia/rollback y no confundir una lección aceptada con un despliegue.
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
