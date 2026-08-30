# MOVA Fantasy Fútbol Data Analytics

Motor operativo y analítico para gestionar el equipo `losmillosFPL` durante la temporada
Fantasy Premier League 2026/27. El repositorio contiene únicamente el producto FPL vigente:
collector, almacén causal, modelos de minutos y puntos, optimizador MILP, control plane del
VPS y contratos de operación segura.

El stack autónomo está desplegado en modo `shadow / A0`: puede recolectar, modelar, decidir
y auditar, pero los cambios en la cuenta continúan bloqueados por controles explícitos.

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
mova status
mova doctor

# servicio autónomo: API FPL + odds + WhoScored
mova collect all
mova data status
mova strategy status
mova strategy research due
mova strategy deliberate status
mova improve status --season 2026-27

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
  únicamente capitanía R2; XI/banca, R3 y toda ejecución no ensayada fallan cerrados. Los controles
  efectivos siguen bloqueando escrituras.
- `mova improve` registra experimentos, evaluaciones, lecciones y uso/costo. Aceptar una lección
  no modifica el runtime; `mova improve release` es el único camino que puede activar un bundle
  `minutes+points`, después de hashes válidos, shadow multi-GW y gate determinista.
- `mova cost report` muestra consumo y reservas contra límites por job, GW y mes; research y
  deliberación reservan capacidad atómicamente antes de entrar a la cola.
- `mova review auto` atribuye causas después del scorecard final y exige recurrencia multi-GW
  antes de crear una propuesta experimental.
- El tick no interpreta Markdown: persiste un `DecisionEnvelope` JSON ligado al manifest real.
- Una propuesta sin GW previa asentada, proyección aprobada, team state fresco o ventana válida
  queda `blocked`; solo una que supera todos los hard gates queda `staged`.
- Strategist y Critic consumen el envelope sellado en un worker one-shot sin DB, browser ni
  secretos. Su `Intervention` es solo evidencia `shadow_only`; no modifica el envelope ni el MILP.
- `mova_fpl` solo hace HTTP `GET`; no escribe en FPL.
- El browser autenticado vive aislado y sus mutaciones están gobernadas por controles.
- Supabase no forma parte del runtime; se usa únicamente para seguimiento PM.

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
- [Servicio autónomo de datos](docs/operations/data-service.md)
- [Operar el VPS](docs/operations/vps.md)
- [PostgreSQL shadow](docs/operations/postgres-shadow.md)
- [Plan y research verificable](docs/operations/strategic-research.md)
- [Lifecycle de decisión](docs/operations/decision-lifecycle.md)
- [Arquitectura del motor](docs/architecture/decision-engine.md)
- [Autonomous Harness v1](docs/specs/fpl-autonomous-operator/10-autonomous-harness-v1.md)

El capítulo Mundial 2026, el motor FPL con leakage, visualizaciones y outputs históricos se
retiraron del árbol operativo. Permanecen recuperables en el tag
`archive/pre-harness-cleanup-2026-08-23`; ver [historia del repositorio](docs/history.md).
