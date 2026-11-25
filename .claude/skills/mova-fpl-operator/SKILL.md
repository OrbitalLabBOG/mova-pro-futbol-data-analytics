---
name: mova-fpl-operator
description: "Operar MOVA FPL en modelo copiloto (ADR-021): leer el catálogo `mova tools`, armar el brief semanal, proponer la decisión a Julián, registrar memoria y cerrar la GW; además salud, datos, modelos, incidentes y rollout del VPS. No usar para escoger jugadores sin el motor ni para hacer clicks en FPL."
metadata:
  vertical: mova
  type: skill
  repo: mova-pro-futbol-data-analytics
  updated: 2026-11-25
---

# MOVA FPL Operator — copiloto

Un asistente de IA (el Grok Bot de Julián, que orquesta Claude Code para cambios de código)
opera MOVA cada GW con tools y memoria. **Nada se escribe en FPL sin el OK explícito de
Julián.** Spec vigente: [ADR-021](../../../docs/specs/fpl-autonomous-operator/decisions/ADR-021-copilot-operating-model.md).
Runbook paso a paso: [gameweek.md](../../../docs/operations/gameweek.md).

En el VPS usa `/usr/local/bin/mova`; en desarrollo, el console script del venv. No abras
SQLite a mano: `mova` y `/api/v1/*` son el contrato. Reporta siempre fecha, SHA observado
(`status.runtime.git_sha`) y `operating_model`; los cortes documentados no son salud viva.

## Primera lectura

1. `mova tools --json` → catálogo `mova-tools-v1`: nombre, argv, side effect, contrato JSON
   y si necesita datos del VPS. Es la fuente de verdad de la superficie; la tabla de abajo
   es un resumen.
2. `mova status --json` → `operating_model` debe ser `copilot`. Si dice
   `scheduled_delivery`, detente y avisa a Julián: el opt-in legacy está activo.
3. `mova week brief --gw N --json` → secciones `cycle`, `authority`, `squad`, `flags`,
   `projections`, `acta`, `strategy_reasons`, `research_signals`, `lessons`, `execution`,
   `open_decisions`. Cada sección trae `status` (`ok|missing|degraded|error|skipped`) y
   `needs_vps`; `overall` es `ready|partial|empty`. Nunca rellenes una sección `missing`
   con memoria de chat o cifras inventadas: decláralo.

## Tools

| Tool | Comando | Efecto |
| --- | --- | --- |
| `tools` | `mova tools --json` | read |
| `status` | `mova status --json` | read |
| `safety` | `mova safety` | read |
| `doctor` | `mova doctor --json --no-network` | read |
| `cockpit` | `mova cockpit --json` | read |
| `triage` | `mova triage --incident-id ID --json` | read |
| `data.status` | `mova data status` | read |
| `collect` | `mova collect fpl --force --actor A --reason R --idempotency-key K` | write-memory |
| `private_state.capture` | `mova private-state capture --force --actor A --reason R --idempotency-key K` | write-memory |
| `incidents.close_obsolete` | `mova incidents close-obsolete --actor A --reason R --idempotency-key K` | write-memory |
| `analytics.status` | `mova analytics status` | read |
| `analytics.reconcile` | `mova analytics reconcile` | write-memory |
| `model.status` | `mova model status` | read |
| `week.brief` | `mova week brief --gw N --json [--no-network] [--no-acta] [--chips]` | read |
| `acta.dry_run` | `mova week acta --gw N --horizon 3 [--chips] --json` | read |
| `acta.commit` | `python -m mova_fpl.cli.live --season S --gw N --horizon 3 --top-k 0 --team-id 3609854` | write-memory |
| `strategy.status` | `mova strategy status` | read |
| `research.due` | `mova strategy research due` | read |
| `research.enqueue` | `mova strategy research enqueue --force --actor A --reason R --idempotency-key K` | write-memory |
| `deliberate.status` | `mova strategy deliberate status` | read |
| `deliberate.enqueue` | `mova strategy deliberate enqueue` | write-memory |
| `memory.read` | `mova memory read --gw N --json` | read |
| `memory.note.add` | `mova memory note add --gw N --kind K --text T --source S --actor A --reason R --idempotency-key K --json` | write-memory |
| `memory.note.list` | `mova memory note list --gw N --json` | read |
| `execute.status` | `mova execute status` | read |
| `execute.manual_package` | `mova execute manual-package --gw N --approved-by julian --approved-at TS --operations OPS --pre-state DIR --post-state DIR --evidence FILE --rationale R` | read |
| `execute.record_manual` | `mova execute record-manual --package FILE --actor A --reason R --idempotency-key K` | write-memory |
| `review.status` | `mova review status --gw N` | read |
| `review.settle_auto` | `mova review settle-auto --gw N --actor A --reason R --idempotency-key K` | write-memory |
| `review.gw` | `mova review gw --package FILE --actor A --reason R --idempotency-key K` | write-memory |
| `improve.status` | `mova improve status --gw N` | read |
| `alerts.status` | `mova alerts status` | read |
| `fpl-web-ops` | skill `.claude/skills/fpl-web-ops` | write-fpl |

`read` no muta el ledger (brief y acta solo dejan artefactos efímeros bajo
`artifact_root/copilot/` o `tmp`; `manual-package` solo escribe el paquete). `write-memory`
escribe en `ops.db`/`trace.db` con actor, razón e idempotency key. `write-fpl` lo tiene
**solo** `fpl-web-ops`, y solo con OK de Julián.

## Ciclo semanal

1. **Brief.** `mova week brief --gw N --json`. Lee primero `open_decisions` y
   `missing_on_vps`. Si `squad` no viene de `private_team_state` fresco, FT/banco/chips están
   sin confirmar: pide a Julián re-login FPL en el browser del VPS antes de cerrar
   transferencias o chips.
2. **Acta y contexto (a demanda).** `mova week acta --gw N --json` para candidatos MILP,
   violaciones y `acta_path`. Si hace falta: `strategy status`, `research due|enqueue`,
   `deliberate status|enqueue`, `memory read`. Research y deliberación ya no corren por
   timer: encolarlos es una decisión explícita (consume cuota).
3. **Proponer.** Con `fpl-expert`: XI, banca en orden, C/VC, transferencias (y hits) y chip,
   cada uno con su razón (xP, minutos, flags, fixtures, memoria), más alternativas y riesgos.
   Mientras la GW actual no esté `finished + data_checked` la propuesta es preliminar: no
   promover chips ni transferencias.
4. **Validar con Julián.** Presenta el plan concreto y espera un OK explícito en el chat
   sobre ese plan exacto (GW, 15, XI, banca, C/VC, transfers, chip). Un "ok" genérico, el
   silencio o un OK de otra GW no autorizan nada. Si algo cambia, vuelve a presentarlo.
5. **Aplicar (solo tras el OK).** Julián lo hace a mano o pide `fpl-web-ops`, que devuelve
   evidencia pre/post.
6. **Memoria (siempre).** `mova memory note add --gw N --kind decision --source owner
   --players-json @plan.json ...` con lo aprobado. Preferencias y restricciones de Julián van
   como `owner_preference`/`constraint`; tus razones, como `reason`/`hypothesis`.
7. **Registro manual (si hay estado privado y evidencia).** Snapshots pre/post bajo
   `MOVA_ARTIFACT_ROOT/team_state/`, luego `mova execute manual-package ...` y
   `mova execute record-manual --package ...`. Sin sesión FPL válida no es posible: dilo y
   deja solo la nota `decision`.
8. **Después de `data_checked`.** `mova analytics reconcile`,
   `mova review settle-auto --gw N ...` (o `review gw --package ...`) y
   `mova memory note add --kind post_mortem` con qué funcionó y qué no.

## Prohibiciones

- No lanzar la cadena de delivery legacy (`execute dispatch|prepare|claim|ui-plan|begin|finalize|fail`,
  `rehearsal*`, `delivery-cycle.sh`, drivers R2/R3): no está en el catálogo y falla cerrado
  con `copilot_mode`.
- No editar controles (`mova control`), envs, SQLite ni artefactos sin OK explícito de Julián;
  toda mutación lleva `--actor`, `--reason` e `--idempotency-key`.
- No re-armar timers de delivery o research ni activar `MOVA_ENABLE_SCHEDULED_DELIVERY`.
- No forzar plantilla, XI ni capitán dentro del motor: solo `Intervention` acotadas vía
  `fpl-expert`; `decide()` es el único punto de decisión.
- No pedir, escribir ni copiar contraseña, OTP, cookies, perfil del browser ni auth de agentes.
- Supabase es solo PM: nunca runtime ni memoria del agente.

## Salud y diagnóstico

- `mova cockpit --json` es el snapshot común; con P0/P1 o `verdict=critical`, corre
  `mova triage --incident-id ... --json`. Guía: [cockpit.md](../../../docs/operations/cockpit.md).
- `mova safety` resume: `unsafe` exige atención, `attention_required` exige leer `reasons`.
  Nunca eleva permisos.
- `mova doctor --json [--no-network]`: un `FAIL` requerido devuelve 1 y bloquea decisiones
  dependientes; un `WARN` se declara y nunca se presenta como `PASS`.
- Contrato completo: [operator.md](../../../docs/operations/operator.md).

| Síntoma | Acción |
| --- | --- |
| `private_team_state` WARN / `FPL_AUTH_REQUIRED` | Squad viejo: correr `mova private-state capture --force`; si falla la sesión, Julián re-loguea por noVNC ([vps.md](../../../docs/operations/vps.md)); no inventar estado ni tocar el perfil. |
| `autonomous_data_service` FAIL/WARN | `mova data status`; aislar la fuente ([data-service.md](../../../docs/operations/data-service.md)). |
| `canonical_database`, `trace_database`, `model_artifacts` FAIL | No proponer con el acta hasta restaurar y verificar. |
| `analytics` sin scorecard | `mova analytics status`; si la GW no está `data_checked`, esperar ([analytics-service.md](../../../docs/operations/analytics-service.md)). |
| `deployment_revision` WARN | Comparar checkout, imagen y SHA antes de atribuir capacidades. |
| Watchdog failed por disco | Reportar; podar backups/imports solo con OK y según [vps.md](../../../docs/operations/vps.md). |
| API FPL FAIL | Conservar la última evidencia y declarar la pérdida de frescura. |

`mova collect <fuente> --force` es una mutación del ledger (exit 2 = degradado, 75 = lock o
cadencia). El collector solo lee fuentes externas; no concede autoridad sobre FPL.

## Qué queda en el VPS

Colector público, timer de analytics/ML (inferencia), PostgreSQL/API, `ops.db`/`trace.db`
y backup diario con poda (ADR-022). Tick, watchdog, DR, postgres-sync y captura privada por
timer están retirados; delivery y research no tienen timer. Estado privado a demanda:
`mova private-state capture --force` (o `week brief --capture-private-state`) antes de armar
la GW, y de nuevo tras el Apply si se registra el manual. Salud mínima: `mova data status` y
`mova doctor --no-network`. Rollout (requiere OK de Julián):
[vps.md](../../../docs/operations/vps.md#rollout-adr-022-harness-mínimo).

## Fuentes de verdad

- Git: código, contratos, skills y runbooks.
- VPS: estado operativo, bases, artefactos, backups, logs y browser persistente.
- `ops.db`: ledger y memoria (`copilot_strategy_notes`, lecciones, ejecuciones manuales).
- Chat: conversación con Julián; lo que deba recordarse se guarda con `mova memory note add`.

Otras referencias, cargar solo si aplican:
[strategic-research.md](../../../docs/operations/strategic-research.md),
[continuous-improvement.md](../../../docs/operations/continuous-improvement.md),
[postgres-shadow.md](../../../docs/operations/postgres-shadow.md),
[execution-preflight.md](../../../docs/operations/execution-preflight.md) (preflight y legacy),
[host-recovery.md](../../../docs/operations/host-recovery.md).

Después de un cambio de código: prueba cercana, `pytest -q`, `docker compose config` y, en el
VPS tras un deploy aprobado, `mova doctor --json`. Para estrategia usa `fpl-expert`; para
aplicar en la web, `fpl-web-ops`.
