---
type: agents
name: AGENTS.md — MOVA Fantasy Fútbol Data Analytics
updated: 2026-11-25
---

# AGENTS.md — MOVA Fantasy Fútbol Data Analytics

Este repositorio contiene el motor FPL vivo de MOVA. Codex debe tratar Git como
fuente canónica de código y documentación, PostgreSQL/SQLite del VPS como datos
operativos y Supabase únicamente como seguimiento PM.

Julián Zuluaga es el owner y decide la dirección de MOVA Fantasy.
No exigir aprobación de otro revisor como gate del proyecto. Las pruebas,
contratos, límites de operación y decisiones de cumplimiento se verifican por
su propia evidencia; no se sustituyen por un visto bueno personal. La única
excepción es la decisión semanal sobre la cuenta FPL: ahí el OK explícito de
Julián es el gate (ADR-021).

## Modelo operativo: copiloto (ADR-021, 25/11/2026)

Un asistente de IA (el Grok Bot de Julián, que orquesta Claude Code o Codex para
cambios de código) opera MOVA cada GW con el catálogo `mova tools --json` y la
memoria de `ops.db`. Propone XI, banca, C/VC, transferencias y chip con razones;
**nada se escribe en FPL sin el OK explícito de Julián** sobre ese plan concreto.
Ya no se busca un Save autónomo por jornada: `operating_model=copilot` es el
default y la cadena de delivery automática falla cerrado (`copilot_mode`).

Ciclo semanal (runbook: `docs/operations/gameweek.md`):

1. `mova week brief --gw N --json`
2. `mova week acta --gw N --json` (+ `strategy`, `research`, `deliberate` a demanda)
3. Proponer con razones y validar con Julián en el chat.
4. Aplicar con `fpl-web-ops` solo después de su OK explícito.
5. `mova memory note add --kind decision` (siempre) y, si hay estado privado y
   evidencia, `mova execute manual-package` + `mova execute record-manual`.
6. Tras `data_checked`: `mova analytics reconcile`, `mova review settle-auto|gw`
   y `mova memory note add --kind post_mortem`.

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
- El VPS conserva: API loopback de datos, collectors público y privado
  autenticado de solo lectura, timers de analytics/ML, tick (envelope y preflight
  como memoria), `ops.db`/`trace.db`/backups y watchdog (solo salud). Delivery y
  research ya no tienen timer; research y deliberación son on-demand.
- Browser separado con perfil persistente. En copiloto los controles quedan
  fail-closed (`browser_writes=false`, A0, sin `delivery_scope`); consultar
  `mova status --json` (`operating_model`) antes de afirmar el estado del VPS: el
  reset de controles de ADR-021 lo ejecuta Julián o se hace con su OK
  (`docs/operations/vps.md`). La sesión se conserva con Chromium activo y volumen
  protegido; contraseña/MFA requieren al humano.
- Equipo real: `losmillosFPL`, `team_id=3609854`.

La hoja de ruta migra gradualmente los datos analíticos y operativos a
PostgreSQL local al VPS. Consultar `docs/operations/postgres-shadow.md` antes de
operarlo. Supabase no es runtime ni almacén FPL.

## Interfaz operativa

En el VPS, usar el wrapper estable. La superficie de tools es `mova tools --json`
(`mova-tools-v1`: nombre, argv, side effect `read|write-memory|write-fpl`, contrato):

```bash
mova tools --json
mova status --json
mova week brief --gw N --json
mova week acta --gw N --json
mova memory read --gw N --json
mova doctor --json --no-network
mova data status
mova analytics status
```

Ningún comando del CLI es `write-fpl`; esa clase solo la tiene la skill
`fpl-web-ops`. Consultar primero la skill canónica
`.claude/skills/mova-fpl-operator/SKILL.md` (`.agents/skills/mova-fpl-operator/SKILL.md`
es su adaptador nativo) y `docs/operations/operator.md`. Los cortes antiguos del README son antecedentes fechados.
Para Docker Compose manual, cargar
`/etc/mova-fpl/deploy.env`; el runbook exacto está en
`docs/operations/vps.md`.

No editar envs, SQLite, artefactos ni controles para saltarse un check. Toda
mutación debe tener actor, razón e idempotency key. Cambiar controles en el VPS
(`mova control`), timers o envs requiere OK explícito de Julián. No usar la cadena
de delivery legacy (`execute dispatch|prepare|claim|ui-plan|begin|finalize|fail`).

## Flujo FPL

`Store.as_of` → minutos → puntos por componentes → matriz por horizonte →
MILP → `Decision` → acta y traza.

- Único punto de decisión: `mova_fpl/engine/runner.py::decide`.
- El planificador autoriza chips; el optimizador decide si los ejecuta.
- El agente solo modifica entradas acotadas mediante `Intervention`; nunca
  fuerza plantilla, once o capitán.
- La primitiva HTTP del motor solo realiza GET. Las escrituras FPL ocurren en el
  browser aislado mediante `fpl-web-ops`, a mano o asistidas, y solo con el OK
  explícito de Julián sobre un plan concreto. Salud, cobertura research, un acta
  nueva o una actualización documental nunca conceden autoridad.
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
- Spec vigente: modelo copiloto,
  `docs/specs/fpl-autonomous-operator/decisions/ADR-021-copilot-operating-model.md`.
- Spec autónoma (superseded, antecedente):
  `docs/specs/fpl-autonomous-operator/10-autonomous-harness-v1.md`.
- Plan de la migración: `docs/plans/operator-tools-refactor.md`.
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
