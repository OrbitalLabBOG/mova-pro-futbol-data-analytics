---
type: plan
name: MOVA FPL — refactor a modo copiloto y superficie de tools de operador
updated: 2026-11-25
status: draft
branch: refactor/operator-tools
base: c4824a8
---

# Plan — modo copiloto + tools de operador

Dirección del owner (Julián): el VPS garantiza collector (público + privado), modelos
ML/analytics, memoria operativa (ops.db/trace.db/backups) y API de datos. La decisión
semanal la arma un asistente con Julián usando tools; **nada se escribe en FPL sin su
validación explícita**. Flujo: `brief → proponer → validar con Julián → aplicar (fpl-web-ops)
→ record-manual → review`.

Hallazgo clave: no existe auto-promoción R2/R3 en código (`readiness.py` publica
`promotion_is_automatic: False`). La autonomía vive en **controles de ops.db en el VPS**
(`mode=autonomous`, `action_level=A2`, `browser_writes=true`, `delivery_scope=lineup-v1`,
`delivery_policy=progressive-lineup-v1`, `delivery_proof`) + **timers** (`delivery` 5 min,
`research` 15 min). Retirarla = guard en código (fail-closed por defecto) + unidades
versionadas + reset de controles ejecutado por el owner.

## (a) Ítem 1 — copiloto por defecto y retiro de autonomía

### Código

| Archivo / símbolo | Cambio |
| --- | --- |
| `mova_fpl/ops/config.py::RuntimeConfig` | Nuevo campo `enable_scheduled_delivery: bool = False` (env `MOVA_ENABLE_SCHEDULED_DELIVERY`). Propiedad `operating_model` → `"copilot"` salvo opt-in. `validate()`: el opt-in exige además `enable_browser_writes`. No se añade un `mode` nuevo (evita tocar 12 literales de modo). |
| `mova_fpl/ops/delivery.py::DeliveryService.dispatch` | Primer gate: si `not config.enable_scheduled_delivery` → `{'status':'blocked','reason':'copilot_mode'}`. El resto del código queda como ruta opt-in (no se borra). |
| `mova_fpl/ops/watchdog.py::assess_workflow_deadline` | `delivery_required = scope=='lineup-v1' and config.enable_scheduled_delivery`. El watchdog queda solo de salud; el recibo manual (`manual_delivery.receipt`) sigue contando como completado. |
| `mova_fpl/ops/operator.py` (~l.811, `expected_units`) | Quitar `mova-fpl-research.timer` de los requeridos; `mova-fpl-delivery.timer` solo si `enable_scheduled_delivery`. `mova-fpl-backup-retention.timer` pasa a requerido siempre (hoy solo con lineup-v1). Añadir `operating_model` al payload de `build_status`/`build_safety`. |
| `mova_fpl/ops/cockpit.py` (~l.183-205) | Ítems `research`/`strategist`: `mode: "on_demand"`, `enabled` = la tool está disponible (no el timer). Ítem `browser_writes`: `mode: "owner_validated_manual"` en copiloto. Exponer `operating_model`. |
| `docs/contracts/operator-status-v1.schema.json` | Campo opcional `operating_model` (aditivo; no rompe v1). |
| `mova_fpl/ops/tick.py` | Sin cambio: envelope + preflight automático son solo memoria (`execution_plans`), útiles al brief. Documentarlo. |

Se conserva invocable: `execute status|preflight|record-manual|reconcile-unchanged`,
`strategy research|deliberate|attempts`, `review *`. Pasan a "legacy opt-in" (documentado,
sin borrar, siguen fallando cerrado): `execute dispatch|prepare|claim|ui-plan|begin|finalize|fail`,
`rehearsal*`, `deploy/bin/delivery-cycle.sh`, `execute-r2-browser.sh`, `browser-r2/r3-driver.py`.
Nada claramente muerto se identificó con seguridad; no se borra código de dominio en esta fase.

### systemd / deploy (versionado)

| Archivo | Cambio |
| --- | --- |
| `deploy/systemd/mova-fpl-delivery.timer` | **Eliminar**. `mova-fpl-delivery.service` se conserva sin `[Install]` (arranque manual explícito, que de todos modos fallará con `copilot_mode`). |
| `deploy/systemd/mova-fpl-research.timer` | **Eliminar**. `mova-fpl-research.service` queda oneshot on-demand (`systemctl start`) o `deploy/bin/research-cycle.sh` manual. |
| `deploy/bin/install-systemd.sh` | Quitar `enable --now` de delivery/research; añadir bloque idempotente `RETIRED_UNITS=(mova-fpl-delivery.timer mova-fpl-research.timer)` → `systemctl disable --now` + `rm -f /etc/systemd/system/<unit>` + `daemon-reload` + `reset-failed 'mova-fpl-delivery-proof-*'`. |
| `deploy/bin/reboot-recovery-prepare.sh` (l.82), `reboot-recovery-verify.sh` (l.65) | Quitar `mova-fpl-research.timer` de la lista de timers verificados. |
| `deploy/bin/host-probe.py` (l.22-37) | Mantener las unidades en la sonda (observación: confirmar que quedaron inactivas). |
| `deploy/bin/delivery-cycle.sh` | Sin cambio funcional; comentario "legacy opt-in". |

### Rollout VPS (lo ejecuta Julián o con su OK explícito; documentado en el runbook)

`git pull` + `install-systemd.sh`, luego controles con actor/razón:
`mova control delivery_scope null`, `delivery_policy null`, `browser_writes false`,
`action_level '"A0"'`, `mode '"supervised"'` (`--actor julian --reason "ADR-021 copiloto"`),
y verificar `mova status --json` → `operating_model=copilot`, `mova doctor`, `systemctl list-timers 'mova-fpl-*'`.

### Tests afectados (Fase A)

- `tests/test_research_worker_contract.py::test_timer_no_es_un_agente_residente` → reescribir: timer ausente, servicio oneshot sin `[Install]` de timer; `test_timer_no_levanta_codex_sin_request_pendiente` sigue válido (script on-demand).
- `tests/test_delivery.py`: `seed()` debe construir config con `enable_scheduled_delivery=True`; nuevo `test_dispatch_blocked_in_copilot_by_default`; `test_host_cycle_returns_before_browser_when_scope_disabled` intacto; `test_scoped_delivery_alerts_even_when_policy_skips_execution` usa `evaluate_workflow_deadline` directo (intacto) + nuevo test de `assess_workflow_deadline` sin delivery requerido en copiloto.
- `tests/test_operator_contract.py` (fixture l.85-110): sigue pasando; añadir test "lineup-v1 sin opt-in no exige delivery/research timers" y `operating_model` presente.
- `tests/test_cockpit.py` (fixture l.29): ajustar expectativas de `research.mode`.
- `tests/test_host_probe.py`: nuevo assert de que `install-systemd.sh` no habilita delivery/research y los deshabilita.
- `tests/test_host_drill.py` (~l.380-400): revisar asserts sobre listas de timers de reboot-recovery.
- Grep de seguridad antes de cerrar: `rg -n 'delivery.timer|research.timer|enable_scheduled_delivery' tests mova_fpl deploy`.

## (b) Catálogo de tools (`mova tools [--json]`)

Nuevo `mova_fpl/ops/tools.py`: registro estático `TOOLS: tuple[Tool,...]` con
`name, argv, summary, inputs, side_effect ∈ {read, write-memory, write-fpl}, needs_vps_data, output_schema`.
`mova tools --json` → `{"schema":"mova-tools-v1","operating_model":..,"tools":[...]}`. Ningún
comando del CLI es `write-fpl`; esa clase solo la tiene la skill externa `fpl-web-ops`
(listada como `external`). Test anti-drift: cada `argv` del registro parsea con `cli.parser()`.

| Tool | Envuelve (existente) | Contrato JSON | Efecto |
| --- | --- | --- | --- |
| `status` | `mova status --json` | `mova-fpl-operator-v1` | read |
| `safety` / `doctor` / `cockpit` / `triage` | `mova safety`, `doctor --json [--no-network]`, `cockpit --json`, `triage` | `operator-doctor-v1`, `mova-cockpit-v1` | read |
| `data.status` / `data.coverage` | `mova data status|coverage` | payload actual | read |
| `collect` | `mova collect <src> --actor --reason --idempotency-key` | job result | write-memory |
| `analytics.status` / `.project` / `.reconcile` | `mova analytics status|project|reconcile` | payload actual | read / write-memory |
| `model.status` / `.explain` / `.predict` | `mova model status|explain|predict` | payload actual | read |
| `week.brief` | **nuevo** `mova week brief --gw N` | `mova-week-brief-v1` (§c) | read (+ artefactos efímeros del acta) |
| `acta.dry_run` | **nuevo** `mova week acta --gw N [--chips] [--horizon 3]` → `python -m mova_fpl.cli.live ... --dry-run --json-out` | `mova-live-decision-candidates-v1` envuelto en `{schema:"mova-acta-dry-run-v1", acta_path, candidates, violations, elapsed_s}` | read (no traza) |
| `acta.commit` | `python -m mova_fpl.cli.live ...` sin `--dry-run` | ídem + `trace_run_id` | write-memory (trace.db) |
| `strategy.status` / `.prepare` | `mova strategy status|prepare` | payload actual (`memory_summary`) | read / write-memory |
| `research.due` / `.coverage` / `.enqueue` / `.import` | `mova strategy research ...` (+ `research-cycle.sh` en host) | payload actual | read / write-memory |
| `deliberate.status` / `.enqueue` / `.import` | `mova strategy deliberate ...` | payload actual | read / write-memory |
| `execute.status` / `.preflight` | `mova execute status|preflight --actor --reason --idempotency-key` | plan + checks | read / write-memory |
| `execute.manual_package` | **nuevo** `mova execute manual-package --gw N --approved-by --operations ... --pre-state --post-state --evidence` → ensambla el paquete `mova-fpl-manual-verified-execution-v2` | paquete + sha | read (escribe solo archivo) |
| `execute.record_manual` | `mova execute record-manual --package ...` (`supervised.record`) | recibo | write-memory |
| `review.status` / `.gw` / `.settle_auto` / `.auto` | `mova review ...` | payload actual | read / write-memory |
| `improve.status` | `mova improve status` | lecciones/propuestas | read |
| `memory.read` | **nuevo** `mova memory read --gw N` | `mova-memory-v1`: notas + lecciones + deliberación + intervenciones + ejecuciones manuales | read |
| `memory.note` | **nuevo** `mova memory note add|list` | `mova-strategy-note-v1` | write-memory |
| `alerts.status` / `.acknowledge` | `mova alerts ...` | sanitizado | read / write-memory |
| `fpl-web-ops` (externa) | skill `.claude/skills/fpl-web-ops` | evidencia pre/post | **write-fpl** (solo con OK de Julián) |

`memory note`: nueva tabla append-only `strategy_notes(note_id, cycle_id, season, gw, kind ∈
{reason, owner_preference, hypothesis, constraint, post_mortem}, text≤2000, players_json,
source ∈ {owner, assistant}, actor, reason, idempotency_key UNIQUE, created_at, supersedes_note_id)`
+ audit event. SQLite migración 25 en `ops/schema.py::MIGRATIONS`, espejo Postgres
`mova_fpl/postgres/migrations/028_strategy_notes.sql` y alta en `postgres/importer.py::TABLES`.
`test_no_secrets.py` aplica: el texto se sanea (sin URLs con tokens, sin email).

## (c) Diseño de `mova week brief --gw N [--json] [--no-network] [--no-acta] [--chips]`

Módulo `mova_fpl/ops/week_brief.py::build_week_brief(config, db|None, *, gw, now, network, run_acta, chips) -> dict`.
Nunca lanza por datos faltantes: cada sección es `{status: ok|missing|degraded|error, source,
needs_vps: bool, detail?, data}`; `overall: ready|partial|empty` y `missing_on_vps: [...]`.
Exit 0 salvo error de argumentos. Sin `ops.db` (path inexistente) → no migra ni crea: todas
las secciones de memoria `missing, needs_vps=true`. Markdown por defecto, `--json` para el agente.

| Sección | Fuente (reusa) | Si falta |
| --- | --- | --- |
| `cycle` (deadline, fase, preliminar) | `db.status()['cycle']`; fallback `data/sources.fetch_bootstrap` (GET) `events` | sin red y sin db → `missing` |
| `authority` | `build_safety` (read-only) + `operating_model` | `missing` |
| `squad` (15, XI, C/VC, FT, banco, chips) | `db.latest_team_state(cycle_id)` (privado) | fallback picks públicos GW-1 (`source=public_reconstruction`, FT/chips `unknown`), `needs_vps=true` |
| `flags` (lesión/duda/sanción) | `bootstrap.elements` status/`chance_of_playing_next_round`/news para los 15 + candidatos del acta | `missing` sin red |
| `projections` | último `projection_runs` vía `AnalyticsStore.status`/`read_status`; fallback xP del bundle del acta | `missing, needs_vps` |
| `acta` (MILP dry-run + alternativas) | subprocess `python -m mova_fpl.cli.live --season --gw --horizon 3 --top-k 0 --team-id --dry-run --out <tmp>/acta.md --json-out <tmp>/candidates.json [--private-team-state <dir>] [--chips]`, timeout 180 s; tmp bajo `artifact_root/copilot/gwNN/` si es escribible, si no `tempfile` | `error` con stderr recortado; `--no-acta` → `skipped` |
| `strategy_reasons` | `db.strategic_status()` (manifest + `memory_summary`), `db.latest_decision_envelope`, `db.decision_deliberation_for_envelope` | `missing` |
| `research_signals` | `research_signals` vigentes del ciclo (validados, no expirados) + conflictos `unresolved` (método nuevo de solo lectura en `OpsDB`) | `missing` |
| `lessons` | `ImprovementService.status(gw=N-1)` lecciones validadas + `strategy_notes` del ciclo y previas activas | `missing` |
| `execution` | `ExecutionService.status(limit=5)` + `manual_delivery.receipt` | `missing` |
| `open_decisions` (derivada) | reglas puras: GW actual no `data_checked` ⇒ preliminar (no chips/transfers); titular con flag; margen C vs VC < 0.5 xP; FT disponibles y acta propone transfer/hit; chip propuesto; conflictos de research; sin estado privado ⇒ "re-login FPL" | siempre presente |

Tests (`tests/test_week_brief.py`): db vacía en `tmp_path` + `--no-network --no-acta` ⇒ `overall=empty`, todas las secciones con `needs_vps`; db sembrada con fixtures existentes (helpers de `test_operator_contract`/`test_delivery`) ⇒ `squad.ok`; acta con runner inyectado (fake subprocess) ⇒ candidatos parseados; error del acta no rompe el brief; `open_decisions` determinista. Contrato `docs/contracts/week-brief-v1.schema.json` validado en test.

## (d) Docs y skills a reescribir

- `AGENTS.md`: secciones *Runtime vigente*, *Interfaz operativa*, *Flujo FPL* y *Documentación* al modelo copiloto; autoridad = validación de Julián; spec vigente → ADR-021.
- `CLAUDE.md`: se mantiene como puente; solo una línea "modelo copiloto, ver AGENTS.md".
- `README.md`: nuevo corte fechado arriba (copiloto); los cortes autónomos quedan como antecedentes.
- `.claude/skills/mova-fpl-operator/SKILL.md` (369 l.): reescritura → "operar MOVA en copiloto": primera lectura `mova tools`/`week brief`, ciclo semanal, qué es write-memory vs write-fpl, prohibiciones (no dispatch/begin, no editar controles sin OK). `.agents/skills/mova-fpl-operator/SKILL.md`: actualizar `description`.
- `.claude/skills/fpl-expert/SKILL.md`: leer brief/acta, explicar candidatos, formular `Intervention` y alternativas, chips como propuesta.
- `.claude/skills/fpl-web-ops/SKILL.md` (+ `references/`): gate = OK explícito de Julián en chat sobre un plan concreto; produce pre/post state + evidencia para `execute manual-package`. Adaptadores `.agents/skills/*`: descripciones.
- `docs/operations/gameweek.md` (path requerido por `test_repository_hygiene.py`): runbook nuevo brief → propuesta → validación → aplicar → record-manual → review (post `data_checked`: `analytics reconcile`, `review settle-auto|gw`, `memory note`).
- `docs/operations/operator.md`, `cockpit.md` (§ operar desde este chat), `execution-preflight.md` (cadena delivery = legacy opt-in), `strategic-research.md` (on-demand), `vps.md` (lista de timers + rollout), `decision-lifecycle.md`.
- Nuevo `docs/specs/fpl-autonomous-operator/decisions/ADR-021-copilot-operating-model.md`; banner "superseded por ADR-021" en `10-autonomous-harness-v1.md`.

## (e) Fases

### Fase A — copiloto por defecto + retiro de autonomía
Cambios de §(a). Criterio: `DeliveryService.dispatch` bloquea con `copilot_mode` sin opt-in;
no hay timers delivery/research versionados; `status`/`cockpit` reportan `operating_model`.
```bash
. .venv/bin/activate
pytest -q tests/test_delivery.py tests/test_operator_contract.py tests/test_cockpit.py \
  tests/test_research_worker_contract.py tests/test_research_entrypoint.py \
  tests/test_host_probe.py tests/test_host_drill.py
python -m compileall -q mova_fpl && bash -n deploy/bin/install-systemd.sh
pytest -q   # baseline: solo las 2 fallas preexistentes
```

### Fase B — superficie de tools + week brief + memoria
`ops/tools.py` + `mova tools`; `ops/week_brief.py` + `mova week brief|acta`; migración
`strategy_notes` (SQLite 25 + Postgres 028 + importer); `mova memory read|note`;
`mova execute manual-package`. Sin tocar `decide()` ni la primitiva HTTP (solo GET vía `data/sources`).
```bash
pytest -q tests/test_tools_catalog.py tests/test_week_brief.py tests/test_strategy_notes.py \
  tests/test_manual_package.py tests/test_readonly_http.py tests/test_architecture_boundaries.py \
  tests/test_no_secrets.py tests/test_agent_contract.py tests/test_postgres*.py
mova tools --json | python -m json.tool >/dev/null
MOVA_OPS_DB=/tmp/empty/ops.db mova week brief --gw 12 --json --no-network --no-acta
pytest -q
```

### Fase C — docs, skills y runbook
Reescrituras de §(d) con frontmatter YAML (`updated:` fecha real). Test nuevo
`tests/test_operator_docs.py`: skills/runbook mencionan `week brief`, `record-manual` y no
recomiendan `execute dispatch`/`begin` ni timers retirados; adaptadores apuntan a la canónica.
```bash
pytest -q tests/test_repository_hygiene.py tests/test_operator_docs.py tests/test_no_secrets.py
rg -n 'delivery.timer|research.timer|execute dispatch' AGENTS.md README.md docs/operations .claude .agents
pytest -q && docker compose config >/dev/null
```

## Riesgos / decisiones abiertas

- `record-manual` v2 exige pre/post team state y evidencia: depende de que el collector privado vuelva (sesión FPL vencida, `FPL_AUTH_REQUIRED`). Sin eso, el registro manual de GW12 no es posible; el brief lo marca.
- El reset de controles en el VPS es un cambio de autoridad: solo con OK explícito de Julián.
- Paridad Postgres de la tabla nueva: verificar que `postgres verify` no falle por tabla no importada.
- `cli.live` imprime progreso a stdout: el wrapper parsea solo `--json-out`, nunca stdout.
