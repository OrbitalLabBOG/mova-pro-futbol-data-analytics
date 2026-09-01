# MOVA Fantasy Fútbol Data Analytics

Motor operativo y analítico para gestionar el equipo `losmillosFPL` durante la temporada
Fantasy Premier League 2026/27. El repositorio contiene únicamente el producto FPL vigente:
collector, almacén causal, modelos de minutos y puntos, optimizador MILP, control plane del
VPS y contratos de operación segura.

El stack autónomo está desplegado en modo `shadow / A0`: puede recolectar, modelar, decidir
y auditar, pero los cambios en la cuenta continúan bloqueados por controles explícitos.
El cockpit read-only comparte un único contrato entre CLI, API y dashboard web autenticado;
Supabase sólo refleja seguimiento PM y nunca recibe estado operativo.

## Empezar

Requiere Python 3.13.

```bash
python -m pip install -e '.[test]'
pytest -q
```

La suite por defecto es hermética y no necesita bases ni modelos externos. Las pruebas que
validan el dataset canónico y artefactos productivos se ejecutan después de generarlos:

```bash
python -m mova_fpl.data.ingest --all
python -m mova_fpl.cli.train_minutes --holdout 2025-26
python -m mova_fpl.cli.train_points --holdout 2025-26
pytest -m integration_data -q
pytest -m slow -q
```

## Operación

```bash
# estado consolidado y diagnóstico del control plane local/VPS
mova cockpit
mova cockpit --json
mova cockpit --watch 30
mova triage --incident-id incident_... --json
mova status
mova doctor

# servicio autónomo: API FPL + odds + WhoScored
mova collect all
mova data status
mova model status
mova model predict --actor codex --reason predeadline --idempotency-key gw03-v1
mova model explain --batch-id projection_ID --element 123
mova model evaluate --actor codex --reason settlement --idempotency-key gw02-v1
mova strategy status
mova strategy research due
mova strategy deliberate status
mova strategy attempts status
mova watchdog
mova improve status --season 2026-27
mova harness scorecard
mova harness workflow
mova postgres status
mova postgres verify
mova postgres drill --actor codex --reason read-cutover --idempotency-key gw03-v1
mova postgres roles --actor codex --reason least-privilege --idempotency-key gw03-roles-v1
mova status --json                 # host.offsite_backup nunca expone URL/password
mova drill host-status --scenario offsite_restore --actor codex \
  --reason restore-evidence --idempotency-key offsite-restore-v1
mova drill snapshot --actor codex --reason snapshot-boundary --idempotency-key snapshot-v1
mova drill browser-failure --actor codex --reason dom-save-boundary \
  --idempotency-key browser-failure-v1
mova drill orchestration --actor codex --reason agent-graph \
  --idempotency-key orchestration-v1
mova alerts channel
mova alerts test --actor codex --reason live-delivery \
  --idempotency-key alert-live-v1
mova drill alert-channel --actor codex --reason alert-contract \
  --idempotency-key alert-channel-v1

# chaos host-only, manual y reversible (no se agenda)
sudo deploy/bin/api-recovery-drill.sh codex "api recovery" hv1-api-v1
sudo deploy/bin/postgres-recovery-drill.sh codex "postgres recovery" hv1-postgres-v1
sudo deploy/bin/browser-recovery-drill.sh codex "browser recovery read-only" hv1-browser-v1
sudo deploy/bin/combined-recovery-drill.sh codex "combined recovery" hv1-combined-v1
# Fase 1 solamente: prepara backup/estado sellado; NO reinicia el VPS.
sudo deploy/bin/reboot-recovery-prepare.sh codex "real reboot recovery" hv1-reboot-v1
# Tras autorización separada, el operador reinicia el host; systemd verifica/importa al volver.

# collector público sellado
python -m mova_fpl.cli.collect_live --season 2026-27 --gw 2

# decisión con estado real del equipo
FPL_TEAM_ID=3609854 python -m mova_fpl.cli.live \
  --season 2026-27 --gw 2 --horizon 3 --top-k 0 --chips
```

El flujo de decisión conserva una sola autoridad y añade un lifecycle máquina:

```text
CycleManifest + memoria estratégica durable → modelos causales → matriz xP → MILP
  → do_nothing + baseline + alternativa
  → Validator determinista → DecisionEnvelope → acta + auditoría
  → Strategist + Critic acotados → Intervention shadow no aplicada
  → ExecutionPlan → apply-once ledger + driver R2 acotado + verifier
  → settlement → review → proposal → test gate → lección validada
  → model bundle sellado → shadow pareado → promote/rollback
```

- `mova_fpl.engine.runner.decide()` es la única autoridad de decisión.
- `mova strategy prepare` reconstruye una memoria estratégica sellada desde planes, decisiones y
  reviews de GWs anteriores y lecciones validadas. No usa historial conversacional ni incorpora
  decisiones de la GW en curso.
- `mova execute` sella riesgo, diff, lease apply-once y verificación. `execute ui-plan` cruza
  pre-state, slots DOM y controles semánticos C/VC después del claim. El wrapper host materializa
  capitanía R2. El instruction stream de XI/banca está implementado y es verificable en modo de
  contrato, pero su entrypoint productivo permanece cerrado hasta los rehearsals; R3 también
  falla cerrado. Los controles efectivos siguen bloqueando escrituras.
- `mova execute rehearsal` importa evidencia browser read-only sellada. Readiness cuenta una sola
  prueba aprobada por GW/capacidad/versión y rechaza fuentes alteradas o intentos de escritura.
- `mova execute rehearsal-capability-probe` deriva evidencia de lineup/R3 exclusivamente desde
  probes DOM allowlisted y conciliados; observar controles nunca habilita entrypoints ni commits.
- `mova postgres drill` ensaya el read-path PostgreSQL y su rollback a SQLite con hashes, artifact,
  idempotencia y métricas, sin cambiar el writer productivo.
- `mova postgres roles` rota y prueba identidades separadas para aplicación y sólo lectura;
  owner queda reservado a migraciones/imports y ningún secreto entra a logs o artifacts.
- Los scripts host de recuperación API/PostgreSQL toman locks, instalan traps, importan evidencia
  allowlisted y son idempotentes; nunca se ejecutan mediante timer ni amplían autoridad FPL.
- `mova improve` registra experimentos, evaluaciones, lecciones y uso/costo. Aceptar una lección
  no modifica el runtime; `mova improve release` es el único camino que puede activar un bundle
  `minutes+points`, después de hashes válidos, shadow multi-GW y gate determinista.
- `mova model` separa `train`, `predict`, `explain` y `evaluate`. El entrenamiento sólo publica
  un bundle candidato inmutable; no cambia el bundle activo y debe atravesar el release gate.
- `mova cost report` muestra consumo y reservas contra límites por job, GW y mes; research y
  deliberación reservan capacidad atómicamente antes de entrar a la cola.
- `mova review auto` atribuye causas después del scorecard final y exige recurrencia multi-GW
  antes de crear una propuesta experimental.
- `mova harness workflow` reconstruye el grafo vigente desde el ledger y separa una terminación
  segura por policy de una falla real de dependencias. El drill hermético comprueba orden,
  fail-closed, deadline e idempotencia sin llamar agentes ni tocar FPL.
- `mova watchdog` inspecciona el heartbeat y, de forma independiente al importador, la cola
  aislada de agentes. Requests huérfanos, terminales, inválidos, demasiado viejos o ligados a un
  tombstone abren un P1 deduplicado; la API `/api/v1/agent-queue`, `doctor` y las métricas
  `mova_agent_queue_*` exponen el estado sin publicar prompts. También expira permisos no usados
  de forma idempotente y detecta permisos ausentes/alterados/huérfanos o starts sin cierre.
- `mova cockpit` compone funciones, autoridad, workflow, costos, readiness y alertas para humanos
  y agentes. `mova triage` enlaza incidentes con jobs/correlations sin ejecutar reparaciones. El
  dashboard autenticado usa ese mismo contrato; no tiene endpoints mutables.
- El sentinel deadline-aware sólo abre incidentes cuando faltan hitos dentro de T−6h/T−3h o una
  ejecución entra en estado terminal inseguro; las esperas normales siguen observables sin ruido.
- `HOST_RECOVERY_DRILLS_PROVEN` exige cinco escenarios: API, PostgreSQL, browser, outage
  combinado y reboot real. El wrapper de preparación sella backups, boot ID, revisión, tick,
  controles y team state, pero nunca ejecuta el reboot; un servicio systemd valida la recuperación
  en el boot siguiente y deja el gate pendiente si no existe evidencia importada.
- `mova alerts channel` expone sólo estado, owner y fingerprint del destino. El webhook externo
  permanece opt-in mediante un secreto Docker; sin configuración, journald sigue funcionando y
  readiness declara pendiente el canal externo. El drill prueba payload mínimo, redacción y
  propagación de fallos sin DNS ni llamadas externas.
- `mova alerts test` crea un P3 de prueba en el outbox, reclama exclusivamente ese evento y
  persiste una entrega 2xx ligada al fingerprint vigente. Replay exacto no repite la llamada;
  cambiar identidad con la misma clave falla por conflicto. Configurar el secreto no basta para
  A1: readiness exige también este live-ping.
- El tick no interpreta Markdown: persiste un `DecisionEnvelope` JSON ligado al manifest real.
- Una propuesta sin GW previa asentada, proyección aprobada, team state fresco o ventana válida
  queda `blocked`; solo una que supera todos los hard gates queda `staged`.
- Strategist y Critic consumen el envelope sellado en un worker one-shot sin DB, browser ni
  secretos. Su `Intervention` es solo evidencia `shadow_only`; no modifica el envelope ni el MILP.
- `mova_fpl` solo hace HTTP `GET`; no escribe en FPL.
- El browser autenticado vive aislado y sus mutaciones están gobernadas por controles.
- Supabase no forma parte del runtime; se usa únicamente para seguimiento PM.
- SQLite sigue siendo el writer operativo. PostgreSQL shadow se sincroniza de forma idempotente
  por ciclo/semana y su paridad/frescura son visibles sin entregar secretos a la API.

## Repositorio

```text
mova_fpl/       dominio, datos, modelos, optimizador, engine y control plane
tests/          contratos herméticos e integración explícita con datos
deploy/         imágenes, scripts operativos y unidades systemd
docs/           arquitectura, runbooks, decisiones y specs
decisions/      decisiones de jornada y evidencia textual versionada
models/         manifests ligeros; los joblib viven fuera de Git
.agents/        skills nativas para operar el proyecto
```

Documentos principales:

- [Índice técnico](docs/README.md)
- [Operar una jornada](docs/operations/gameweek.md)
- [Contrato `mova` y diagnóstico](docs/operations/operator.md)
- [Cockpit, triage y dashboard autenticado](docs/operations/cockpit.md)
- [Servicio autónomo de datos](docs/operations/data-service.md)
- [Servicio analítico y operaciones del modelo](docs/operations/analytics-service.md)
- [Operar el VPS](docs/operations/vps.md)
- [PostgreSQL shadow](docs/operations/postgres-shadow.md)
- [Plan y research verificable](docs/operations/strategic-research.md)
- [Lifecycle de decisión](docs/operations/decision-lifecycle.md)
- [Arquitectura del motor](docs/architecture/decision-engine.md)
- [Autonomous Harness v1](docs/specs/fpl-autonomous-operator/10-autonomous-harness-v1.md)

El capítulo Mundial 2026, el motor FPL con leakage, visualizaciones y outputs históricos se
retiraron del árbol operativo. Permanecen recuperables en el tag
`archive/pre-harness-cleanup-2026-08-23`; ver [historia del repositorio](docs/history.md).
