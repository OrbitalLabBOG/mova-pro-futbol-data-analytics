# AGENTS.md — MOVA Fantasy Fútbol Data Analytics

Este repositorio contiene el motor FPL vivo de MOVA. Codex debe tratar Git como
fuente canónica de código y documentación, PostgreSQL/SQLite del VPS como datos
operativos y Supabase únicamente como seguimiento PM.

## Qué está vivo

- Código activo: `mova_fpl/`, `deploy/`, `tests/` y `docs/operations/`.
- Código congelado: `src/mova_data/`, `src/mova_model/` y `scripts/` heredados.
- No importar, extender ni citar resultados del FPL legacy: contiene leakage y
  resultados no reproducibles. Las pruebas de arquitectura hacen cumplir esta
  frontera.
- Rama productiva: `main`.

## Runtime vigente

- Python 3.13.5, pandas, NumPy, SciPy, scikit-learn, PuLP/CBC y joblib.
- Imagen Docker reproducible en el VPS.
- Writer oficial: SQLite `ops.db`; almacenes analíticos actuales:
  `fpl_canonical.db` y `trace.db`.
- PostgreSQL 17 corre privado. Sigue en shadow para el path de decisión, pero es
  writer autorizado del data service FPL/odds/WhoScored. No hacer cutover del
  resto del harness sin los gates de HV1-02.
- API loopback, timers systemd, backups, collector público y collector privado
  autenticado de solo lectura.
- Browser separado con perfil persistente. Por defecto está detenido y sin
  escrituras: `shadow`, `A0`, `kill_switch=true`, `browser_writes=false`.
- Equipo real: `losmillosFPL`, `team_id=3609854`.

La hoja de ruta migra gradualmente los datos analíticos y operativos a
PostgreSQL local al VPS. Consultar `docs/operations/postgres-shadow.md` antes de
operarlo. Supabase no es runtime ni almacén FPL.

## Interfaz operativa

En el VPS, usar el wrapper estable:

```bash
mova status
mova status --json
mova doctor
mova doctor --json --no-network
mova postgres status
mova postgres verify
mova data status
mova collect all
mova analytics status
mova analytics run
```

Consultar primero `docs/operations/operator.md` y la skill
`.agents/skills/mova-fpl-operator/SKILL.md`. Para Docker Compose manual, cargar
`/etc/mova-fpl/deploy.env`; el runbook exacto está en
`docs/operations/vps.md`.

No editar envs, SQLite, artefactos ni controles para saltarse un check. Toda
mutación debe tener actor, razón e idempotency key. Las decisiones y corridas de
research son observación mientras los controles sigan en A0/shadow.

## Flujo FPL

`Store.as_of` → minutos → puntos por componentes → matriz por horizonte →
MILP → `Decision` → acta y traza.

- Único punto de decisión: `mova_fpl/engine/runner.py::decide`.
- El planificador autoriza chips; el optimizador decide si los ejecuta.
- El agente solo modifica entradas acotadas mediante `Intervention`; nunca
  fuerza plantilla, once o capitán.
- La salida automática hacia FPL permanece prohibida hasta superar los gates de
  cumplimiento y autonomía. El paquete solo realiza GET.
- Una propuesta para la GW siguiente es preliminar mientras la GW actual no
  esté `finished` y `data_checked`. No promover chips ni transferencias en ese
  estado.

## Datos y modelos

- Histórico canónico: 253.890 filas, temporadas 2016-17…2025-26.
- Artefactos productivos: familias `minutes` y `points`, versiones 1.0.0/1.1.0.
- El estado vivo usa API pública oficial y snapshot privado sanitizado.
- Para operar 2026-27, el modelo se ajusta con temporadas cerradas y reserva
  2025-26 según el comando de entrenamiento vigente.
- No tratar una sola aparición de GW1 como reentrenamiento. Las señales de
  minutos actuales deben entrar como research/intervención auditable hasta que
  HV1-03 defina su incorporación causal.

## Verificación obligatoria

Antes de terminar cambios:

```bash
pytest -q
```

Además, según el cambio:

```bash
docker compose config
python -m compileall -q mova_fpl
```

Pruebas estructurales no negociables:

- `test_readonly_http.py`: una sola primitiva HTTP y solo GET.
- `test_architecture_boundaries.py`: capas y legacy separados.
- `test_store_as_of.py`: causalidad sin filas futuras.
- `test_no_secrets.py`: sin secretos ni PII.
- `test_agent_contract.py`: el agente no controla la salida.

No declarar listo un cambio del VPS sin verificar revisión de checkout/imagen,
`mova doctor` y rollback disponible.

## Documentación y desarrollo

- Operación: `docs/operations/`.
- Spec autónoma vigente:
  `docs/specs/fpl-autonomous-operator/10-autonomous-harness-v1.md`.
- Spec histórica del motor:
  `docs/specs/fpl-decision-engine/`.
- Markdown permanente lleva frontmatter YAML y debe actualizar una fuente
  existente antes de duplicarla.
- No activar `orbital-large-development` salvo petición explícita de Julián.

## Navegación del código

El repo incluye CodeGraph en `.codegraph/`:

```bash
codegraph explore "pregunta"
codegraph callers <símbolo>
codegraph callees <símbolo>
codegraph impact <símbolo>
git diff --name-only | codegraph affected --stdin
```

Verificar con `rg` los nombres genéricos y registros dinámicos como
`POLICIES[...]` y `models/registry.py`.

## Seguridad del worktree

Puede haber experimentos locales. Revisar `git status` antes de editar, preservar
cambios ajenos y usar un clone/worktree limpio si se solapan. No hacer reset,
checkout destructivo ni reformateo masivo.
