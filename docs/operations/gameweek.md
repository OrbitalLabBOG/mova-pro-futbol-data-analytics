---
type: runbook
name: MOVA FPL — operar y cerrar una jornada (modelo copiloto)
updated: 2026-11-25
status: active
supersedes_section: "Ruta operativa vigente (lineup-v1 autónomo, 21/10/2026)"
---

# Runbook — operar una jornada de FPL

Para el asistente que opera MOVA cada GW (el Grok Bot de Julián, que orquesta Claude Code
para cambios de código) y para Julián. Modelo vigente:
[ADR-021](../specs/fpl-autonomous-operator/decisions/ADR-021-copilot-operating-model.md).

**Regla única: nada se escribe en FPL sin el OK explícito de Julián** sobre un plan
concreto (GW, 15, XI, banca en orden, C/VC, transferencias, hits, chip). El motor propone;
el asistente explica; Julián decide.

---

## Ciclo semanal del copiloto

| Paso | Qué | Comando / tool | Efecto |
| --- | --- | --- | --- |
| 1 | Brief de la GW | `mova week brief --gw N --json` | read |
| 2 | Acta MILP (dry-run) | `mova week acta --gw N --json [--chips]` | read |
| 2b | Contexto a demanda | `mova strategy status`, `strategy research due\|enqueue`, `strategy deliberate status\|enqueue`, `mova memory read --gw N --json` | read / write-memory |
| 3 | Propuesta con razones | skill `fpl-expert` | — |
| 4 | Validación | chat con Julián: OK explícito sobre el plan exacto | — |
| 5 | Aplicar en FPL | skill `fpl-web-ops` (solo tras el OK) | write-fpl |
| 6 | Memoria de la decisión (siempre) | `mova memory note add --kind decision` | write-memory |
| 7 | Registro manual (si hay estado privado y evidencia) | `mova execute manual-package` → `mova execute record-manual` | write-memory |
| 8 | Tras `data_checked` | `mova analytics reconcile`, `mova review settle-auto\|gw`, `mova memory note add --kind post_mortem` | write-memory |

### Equipo real, research y cierre (iter. 1)

1. **Importar el equipo** leído del browser logueado: `mova private-state import --file
   snap.json --actor A --reason R --idempotency-key K` (my-team crudo o snapshot simplificado:
   `picks[{element, position 1..15, selling_price, purchase_price, element_type|pos}]`, `bank` y
   precios en **décimas**, `free_transfers`, `chips` disponibles, `gw`). Se sella como
   `operator_import`; `transfers.limit: null` (chip activo / sin tope) no falla y los FT pasan a
   ser un supuesto declarado (`free_transfers_assumed`). Devuelve `artifact_path`.
2. **Acta con ese estado e intervenciones**: `mova week acta --gw N --private-state-path
   <artifact_path> --interventions research.json [--intervention-from-notes]
   [--require-private-state] [--timeout 600]`. La ruta explícita no pasa por la cadencia del
   deadline. Acta y brief reportan `state_source` (`import|capture|public_reconstruction`) y
   `state_age_h`. El research (`mova-research-adjustments-v1`: `source`, `rationale`,
   `adjustments[{element, p_play|xp_multiplier, confidence}]`, `lock_out`, `block_chips`; máx. 8
   jugadores) ajusta p_play/xP **antes de proyectar** (p=0 vetea; subir sobre el modelo exige
   `confidence: "high"`) sin solves MILP extra; el reporte `interventions.adjustments` da el
   cambio de xP proyectado por jugador, no una ganancia de decisión.
3. **Cerrar la GW** (sin `settle-auto` ni ejecución verificada): tras `finished + data_checked`,
   `mova gw close --gw N --actor A --reason R --idempotency-key K` puntúa los picks públicos y la
   nota `decision` y escribe el `post_mortem`; sale con código 2 si la GW no se puede cerrar.

La superficie completa y sus side effects están en `mova tools --json`. En el VPS anteponer
`sudo /usr/local/bin/` al wrapper.

### 0. Antes de empezar

```bash
mova status --json      # operating_model debe ser "copilot"
mova tools --json       # catálogo mova-tools-v1
```

Si `operating_model` no es `copilot`, detenerse y avisar a Julián: el opt-in legacy
`MOVA_ENABLE_SCHEDULED_DELIVERY` está activo y la cadena automática puede competir con la
operación manual.

### 1. Brief

```bash
mova week brief --gw 12 --json
```

Nunca falla por datos faltantes: cada sección trae `status`
(`ok|missing|degraded|error|skipped`), `source` y `needs_vps`; `overall` es
`ready|partial|empty` y `missing_on_vps` lista lo que solo existe en el VPS. Leer primero
`open_decisions`:

- `private_state_missing` / `squad.source != private_team_state`: FT, banco y chips sin
  confirmar. No hay timer de captura (ADR-022): correr en el host
  `mova private-state capture --force --actor A --reason R --idempotency-key K` (o
  `mova week brief --gw N --capture-private-state`). Si la sesión FPL venció, Julián debe
  re-loguearla en el browser del VPS ([vps.md](vps.md)). Repetir la captura justo antes del
  acta si faltan < 3 h al deadline, y de nuevo tras el Apply si se registrará el manual. El
  brief/acta degradan sin estado fresco; nunca esperan al browser.
- GW actual sin `data_checked`: la propuesta es **preliminar**; no promover chips ni
  transferencias.
- Titular con flag, margen C vs VC < 0.5 xP, transferencia/hit o chip propuesto,
  conflictos de research: puntos a discutir con Julián.

Un `missing` no se rellena con memoria de chat ni cifras inventadas: se declara.
`--no-network` omite los GET públicos; `--no-acta` evita correr el MILP.

### 2. Acta y contexto a demanda

```bash
mova week acta --gw 12 --horizon 3 --json          # --chips para evaluar chips
```

Devuelve `mova-acta-dry-run-v1` con `acta_path`, `candidates`, `violations` y
`elapsed_s`; no escribe traza. Si faltan `fpl_canonical.db` o los `.joblib` del bundle
activo responde `missing` con las rutas (exit 2): el acta corre en el VPS.

Research y deliberación ya no tienen timer. Encolarlas es una decisión explícita porque
consume cuota ([strategic-research.md](strategic-research.md)):

```bash
mova strategy research due
mova strategy research enqueue --force --actor julian --reason "noticias GW12" \
  --idempotency-key research:2026-27-gw12:1
mova strategy deliberate status
mova memory read --gw 12 --json
```

### 3. Proponer

Con `fpl-expert`, una propuesta por GW con:

- XI y formación, banca en orden (GK, 1, 2, 3);
- capitán y vice;
- transferencias (FT disponibles, hits) o "rollear FT";
- chip o ninguno;
- para cada punto, la razón (xP por horizonte, minutos, flags, fixtures, precio, memoria)
  y la alternativa más cercana.

La propuesta sale de `decide()` vía el acta. Si Julián quiere desviarse, se explica el costo
en xP y se registra su razón; no se fuerza la salida del motor.

### 4. Validar con Julián

Presentar el plan concreto y esperar un **OK explícito** sobre ese plan exacto, para esa GW
y antes del deadline. Un "ok" genérico, el silencio, un OK de otra GW, salud verde o un acta
nueva no autorizan nada. Si el plan cambia, se vuelve a presentar. Anotar la hora del OK
(`--approved-at`).

### 5. Aplicar (solo tras el OK)

Julián lo aplica a mano en la web o pide `fpl-web-ops`, que opera el browser aislado del
VPS, captura pre/post-state privados y deja evidencia (captura + SHA-256) bajo
`MOVA_ARTIFACT_ROOT/manual/`. Ningún comando `mova` escribe en FPL. No cambiar
`browser_writes`, `action_level` ni `delivery_scope` para esto: gobiernan el driver
automático legacy y quedan fail-closed.

### 6. Memoria de la decisión (siempre)

```bash
mova memory note add --gw 12 --kind decision --source owner \
  --text "XI aprobado por Julián: ..." --players-json @/tmp/gw12-plan.json \
  --actor julian --reason "OK en chat" --idempotency-key note:2026-27-gw12:decision:1 --json
```

`players_json` de una nota `decision` se valida: `xi` 11, `bench` 4, C≠VC y titulares,
transferencias balanceadas, hits múltiplo de 4, chip conocido. La tabla es append-only; para
corregir se añade otra nota con `--supersedes <note_id>`. Las preferencias o restricciones de
Julián se guardan como `owner_preference`/`constraint`. El texto se sanea (sin emails,
tokens ni query strings).

### 7. Registro manual (si hay estado privado y evidencia)

Requiere snapshots privados pre y post (`MOVA_ARTIFACT_ROOT/team_state/...`, ver
`/api/v1/team-state`) y el JSON de evidencia:

```bash
mova execute manual-package --gw 12 --approved-by julian \
  --approved-at 2026-11-26T20:00:00Z --operations lineup,captaincy \
  --pre-state <dir-pre> --post-state <dir-post> \
  --evidence /var/lib/mova-fpl/artifacts/manual/gw12-evidence.json \
  --rationale "OK de Julián en chat"
mova execute record-manual --package <paquete> --actor julian --reason "GW12 aplicada" \
  --idempotency-key manual-verified:2026-27-gw12:1
```

`manual-package` deriva jugadores, C/VC, transferencias, hits y chip de pre/post, valida con
el mismo código que `record-manual` y solo escribe archivos (R2/A2 sin diff, R3/A3 con diff).
Misma entrada, mismos bytes; contenido distinto exige `--overwrite`. Sin sesión FPL válida
(`FPL_AUTH_REQUIRED`) no hay pre/post: declararlo y dejar solo la nota `decision`.

### 8. Después de `data_checked`

```bash
mova analytics reconcile
mova review settle-auto --gw 12 --actor julian --reason "cierre GW12" \
  --idempotency-key settle:2026-27-gw12
mova review status --gw 12
mova memory note add --gw 12 --kind post_mortem --source assistant \
  --text "Qué funcionó y qué no ..." --actor assistant --reason "cierre GW12" \
  --idempotency-key note:2026-27-gw12:post_mortem:1 --json
```

`settle-auto` cierra con el recibo manual v2 si existe. Sin recibo, usar `mova review gw
--package ...` (§8 del anexo). El post-mortem alimenta `lessons` del brief de la GW siguiente.

### Qué no hacer

- No usar la cadena de delivery legacy (`execute dispatch|prepare|claim|ui-plan|begin|finalize|fail`,
  `rehearsal*`, `delivery-cycle.sh`): falla cerrado con `copilot_mode` y no está en el catálogo.
- No re-armar timers de delivery, research, tick, watchdog ni private-state (ADR-022).
- No editar controles, envs, SQLite ni artefactos sin OK explícito de Julián.
- No pedir ni escribir contraseña/MFA: el re-login lo hace Julián por noVNC.

---

# Anexo — referencia del motor y del cierre

Los comandos directos del motor que siguen son utilidades manuales y de investigación; el
acta del copiloto los envuelve (`mova week acta`). Sus deadlines, cifras y estados fechados
son antecedentes. Una rutina de operación no reentrena producción: para candidatos usar
[mova model](analytics-service.md) y el release gate.

## 0. Lo que hay que saber antes de tocar nada

- **El motor de decisión no escribe en FPL.** Su única primitiva de red es un `GET`
  (`data/sources.py`), verificado por `tests/test_readonly_http.py`. El browser del stack VPS
  es otro runtime con autoridad y scope auditados; ver [VPS](vps.md).
- **La única acta que cuenta es la última.** Los precios se mueven a diario y el parte
  médico cambia hasta minutos antes del cierre. Un acta emitida con más de dos días de
  antelación se marca sola como borrador.
- **El deadline se consulta en el ciclo y la API oficial.** Antecedente GW1 de 2026/27: `2026-08-21T17:30:00Z` = 12:30 en Bogotá.

## 1. Correr una jornada

```bash
cd "/home/julianzu/code/orbital lab/mova-pro-futbol-data-analytics"

# ensayo: escribe el acta pero no toca la traza
python -m mova_fpl.cli.live --season 2026-27 --gw 1 --horizon 3 --top-k 0 --dry-run

# de verdad: persiste la decisión en la traza como `committed`
python -m mova_fpl.cli.live --season 2026-27 --gw 1 --horizon 3 --top-k 0
```

El acta queda en `outputs/fpl/2026-27/gwNN_decision.md`. Tarda unos **5 segundos**.

| Opción | Para qué | Recomendado |
|---|---|---|
| `--horizon N` | Jornadas que mira hacia adelante | **3** (ver §5) |
| `--top-k 0` | Sin recorte de mercado: optimalidad garantizada | **0** en vivo |
| `--policy` | `milp` u `greedy-stub` | `milp`; la voraz es el plan B |
| `--dry-run` | No escribe en la traza | Para ensayar |
| `--json-out PATH` | Emite candidatos tipados para el harness | Uso a demanda (el tick está retirado) |
| `--as-of RFC3339` | Fija el reloj lógico para replay | Uso a demanda (el tick está retirado) |

### Con el equipo real (desde la GW2)

```bash
export FPL_TEAM_ID=3609854     # losmillosFPL — el número de la URL /entry/<ID>/ en la web de FPL
python -m mova_fpl.cli.live --season 2026-27 --gw 2 --horizon 3 --top-k 0 --chips
```

Con `--team-id` (o `FPL_TEAM_ID`) el motor lee de la API **pública** tu plantilla vigente,
el banco, las transferencias libres acumuladas y **los chips que ya gastaste**. Tres GET
más; la garantía de solo lectura no se toca.

| Opción | Para qué |
|---|---|
| `--team-id N` | Decidir sobre tu equipo real en vez de desde cero |
| `--chips` | Deja que el planificador proponga chips |
| `--lookahead N` | Jornadas de calendario que considera anunciadas (6) |

Sin `--team-id`, el motor arma desde cero y **avisa** de que no sabe qué chips te quedan.
En GW1 puede evaluar Bench Boost y Triple Captain; Free Hit está legalmente bloqueado.

## 2. Cuándo correrla

| Momento | Qué hacer |
|---|---|
| Al abrir la temporada | Una corrida para ver por dónde va el equipo. Es un borrador. |
| 48 h antes del cierre | Otra corrida. Empiezan a salir las ruedas de prensa. |
| **Dentro de las 24 h previas** | **La corrida que vale.** Esta es la que se introduce. |
| Después del cierre | Nada. El acta ya no sirve; la siguiente jornada es otra corrida. |

## 3. Reentrenar los modelos

Los artefactos `.joblib` no están en Git (son regenerables y pesan). Después de clonar, o
cuando entren datos nuevos:

```bash
python -m mova_fpl.data.ingest --all          # almacén canónico, idempotente
python -m mova_fpl.cli.train_minutes --production --version 1.1.0
python -m mova_fpl.cli.train_points  --production --version 1.1.0
```

En producción entran las diez temporadas cerradas hasta 2025-26. El modelo de minutos usa
2025-26 para calibración temporal y el de puntos ajusta todos sus componentes con el histórico
completo. Para evaluación y backtest se conserva `--holdout`; no confundir ese modo con el
artefacto que decide 2026/27.

Antes de emitir el acta final, sellar la API oficial para que datos, decisión y hashes sean
reproducibles:

```bash
python -m mova_fpl.cli.collect_live --season 2026-27 --gw 1
python -m mova_fpl.cli.live --season 2026-27 --gw 1 --snapshot-dir data/raw/fpl_live/2026-27/gw01/<captura> --dry-run
```

## 4. Si algo falla antes del deadline

### La API de FPL no responde

`data/sources.py` reintenta cinco veces con espera creciente. Si aun así falla:

1. **Comprobar que es la fuente y no la red:**
   `curl -s -o /dev/null -w "%{http_code}\n" https://fantasy.premierleague.com/api/bootstrap-static/`
2. **Si la API está caída**, no hay estado público que leer y el motor no puede decidir con
   datos frescos. El plan B es manual: abrir la web de FPL, que suele seguir en pie aunque la
   API pública falle, y armar el equipo con el acta más reciente como guía. Está para eso.
3. **Nunca inventar datos** para que el pipeline corra. Un acta con precios de hace una
   semana es peor que ninguna, porque parece fresca.

### El optimizador dice `Infeasible`

Trae la lista de motivos. Los tres reales:

| Motivo | Qué significa | Salida |
|---|---|---|
| `solo N GKP en el mercado` | El catálogo llegó incompleto | Reintentar; si persiste, es la fuente |
| `la plantilla más barata cuesta X` | El presupuesto no alcanza | Solo puede pasar con estado corrupto |
| `con máximo 3 por club...` | Muy pocos clubes juegan | Jornada con muchos blancos: bajar `--horizon` |

### El acta sale marcada como INVÁLIDA

`validate_squad` encontró una violación. **No introducir ese equipo.** El acta lista los
códigos exactos. Correr con `--policy greedy-stub`, que es la heurística probada de WP-003, y
comparar. Si las dos fallan, es un problema de datos, no de política.

### Falta el `.joblib` de un modelo

```
FileNotFoundError: models/points/points-1.0.0.joblib
```

Reentrenar (§3). Toma menos de dos minutos.

## 5. Qué horizonte usar

**Por defecto 3.** No porque esté demostrado que es el mejor, sino porque:

| Horizonte | 2025-26 con `minutes` | 2025-26 con `points` |
|---:|---:|---:|
| 1 | 2.014 | 2.178 |
| **3** | 2.010 | **2.217** |
| 5 | **2.131** | 2.207 |
| 8 | 2.080 | — |

> Cifras medidas antes de ADR-008; con la corrección de las transferencias libres, h=3
> pasa de 2.217 a 2.220. El **orden** entre horizontes no se volvió a medir.

El orden **se invirtió** al mejorar el proyector: con un modelo, ganaba 5 y perdía 3; con el
otro, al revés. Diferencias que cambian de orden al tocar otra pieza del sistema están dentro
del ruido de una sola temporada. Es la pregunta abierta **Q-05**.

Mientras no se resuelva con más temporadas, se usa **3**: es el mejor con el modelo vigente
y está en el medio del rango, que es donde conviene estar cuando no se sabe.

## 6. Verificar que todo sigue en pie

```bash
pytest -q                                     # gate hermético, sin datos externos
pytest -m integration_data -q                 # dataset y modelos locales
pytest -m slow -q                             # temporada completa, ~3 min
pytest tests/test_readonly_http.py -v         # solo GET contra FPL
python -m mova_fpl.cli.backtest --season 2025-26 --policy milp --projector points --horizon 3
```

El backtest completo tarda unos dos minutos. Las huellas históricas con semilla 42 fueron
**2.220** puntos sin chips y **2.303** con chips. Se conservan como regresión de
comportamiento, no como una estimación estable de calidad; si cambian, hay que atribuir la
causa antes de operar.

> La cifra de referencia fue 2.217 hasta agosto de 2026. Subió a 2.220 al cerrarse un fallo
> en la linealización de las transferencias libres, verificado por A/B sobre la temporada
> completa (ADR-008).

## 6.b Los chips

Ocho por temporada: dos juegos completos —wildcard, free hit, bench boost, triple captain—
y el primero **caduca en el deadline de la GW19**. No se arrastra. Un chip sin usar al
cerrar su ventana es valor quemado.

```bash
# backtest con el planificador de chips activo
python -m mova_fpl.cli.backtest --season 2025-26 --policy milp --projector points \
    --horizon 3 --chips --lookahead 6
```

El reporte trae la atribución **medida** de cada chip: para cada uno que se jugó, se puntúa
también la decisión que se habría tomado sin él, contra los mismos resultados. La resta es
su valor real, no una estimación.

| Mando | Qué hace |
|---|---|
| `--chips` | Activa el planificador. Sin él, ningún chip se juega |
| `--lookahead N` | Jornadas de calendario que el planificador considera **anunciadas** |

`--lookahead` es una decisión de honestidad, no de rendimiento: mirar la temporada entera
le daría al motor información que un manager no tenía cuando decidió. Por defecto 6.

## 7. Consultar lo ya decidido

```python
from mova_fpl.trace.query import runs, decisions
runs()                                        # todas las corridas
decisions("2026-27-live-milp-h3")             # decisiones de la corrida en vivo
```

## 8. Cerrar una jornada asentada

El settlement solo corre cuando la API oficial marca la jornada `finished + data_checked`. El
package manual versionado contiene la decisión, el comparador y la evidencia predeadline; los
puntos, minutos, picks y rank se vuelven a leer de PostgreSQL. Una jornada sin batch predeadline
produce un review `retrospective`, nunca un scorecard causal fabricado.

```bash
mova review gw \
  --package /app/decisions/fpl/2026-27/gw01_closeout.json \
  --actor julian \
  --reason "cerrar GW1 antes de decidir GW2" \
  --idempotency-key "2026-27:gw01:manual-closeout:v1"
```

El job valida los 15 picks, recalcula autosubs/capitán con las reglas de la temporada, compara el
resultado oficial con el engine, publica un artifact inmutable, exporta la atribución a `trace.db`
y persiste settlement, review, jugadores y propuestas en `ops.db`. Después de backup y con la GW
cerrada se puede ejecutar un nuevo `mova postgres import` para reflejar la fotografía completa en
el store shadow; nunca hacer ese import durante el deadline.

Verificación mínima:

```bash
mova status --json
mova doctor --json --no-network
mova review status --gw 1
```

El último comando expone settlement, métricas, outcomes por jugador y propuestas desde el
SQLite soportado dentro del contenedor. No abrir `ops.db` con el `sqlite3` del host.

La traza vive en `data/processed/trace.db`. Cada decisión guarda su huella
(`fingerprint`), que permite comprobar si dos corridas decidieron lo mismo.

### Cierre automático de una intervención manual verificada

Es la ruta normal del copiloto tras `execute record-manual`. El cierre autónomo (analytics) procesa recibos
manuales v2 íntegros. El paquete resultante usa
`mova-fpl-manual-closeout-v2`, `verified_execution_source=manual_verified` y
`scheduler_save=false`: automatizar el cierre no convierte el montaje en autónomo.
El seleccionado proviene de las quince posiciones y audit sellados; el comparador
es el estado privado anterior identificado por el fingerprint auditado. No exige ni
fabrica un candidato MILP coincidente. Conserva financiación, hashes y conciliación
con picks/puntos oficiales. Las expectativas se atribuyen retrospectivamente desde
un batch aprobado generado antes del deadline. No se registra un scorecard causal
nuevo ni se incrementa `observed_closeouts` del contrato autónomo.

### Financiación y atribución del cierre autónomo v2 (legacy)

Aplica solo a ciclos de la etapa autónoma o al opt-in legacy; en copiloto el cierre
usa el contrato manual v2 de arriba.

Una entrega regular sin cambios puede cerrar desde un recibo
`mova-unchanged-delivery-v1`: captura privada exacta <=300 s, plan/candidato ligados,
hashes verificados y preflight completo en la ventana regular. El cierre etiqueta
`verified_execution_source=unchanged_delivery`, conserva financiación y comparador
y nunca acredita un Save físico. No sirven jobs legacy sin este recibo ni pruebas
`delivery_proof`. Si falta evidencia histórica, no se fabrica una ejecución.


`mova-fpl-autonomous-closeout-v2` requiere `mova-closeout-financing-v1` en ambos
escenarios. El estado inicial proviene del team-state vinculado al manifest del envelope;
el seleccionado también exige el estado posterior durable de la ejecución. Se verifican
hashes físicos, fingerprints, pertenencia al ledger y precios del batch approved predeadline.
Importes en décimas: banco posterior = banco inicial + ventas a selling_price − compras.
Los jugadores retenidos conservan purchase_price. Valor de mercado no equivale a coste de
compra ni a efectivo disponible. Un roster valorizado puede ser legal sin volver a aplicar
el presupuesto de compra inicial; esta excepción sólo procede tras validar financiación.
El validador general del motor conserva su presupuesto.

Wildcard y Free Hit eximen hits, sin eximir financiación. Free Hit deja reversión
`pending_next_gameweek` con hash del estado previo; el cierre de la jornada del chip
no acredita que la reversión futura haya ocurrido. Si falta evidencia o los precios del
batch no reproducen las compras observadas, el cierre falla y requiere evidencia compatible.
No aproximar la financiación con precios posteriores.

Los paquetes v1 siguen siendo legibles y conservan `legacy_initial_budget`; un cierre v1
no cuenta como evidencia del contrato autónomo v2. Los contadores sólo incluyen jobs
completos etiquetados v2. Las contribuciones por jugador usan los multiplicadores del
motor, incluyendo BB, TC, vice y autosubs: suma de filas = bruto; neto = bruto − hits.
La expectativa declara el chip y los oracles mantienen chip/hits del escenario. La
comparación expone `same_chip`, sin atribuir automáticamente diferencias de chip al modelo.
`p60_brier_15=null`, contador cero y `probabilities_missing` indican ausencia de datos,
sin impedir el settlement ni fabricar calibración.

## 8. La bitácora de intervenciones

Cada vez que alguien mueve una entrada del sistema —el planificador de chips, un agente,
Julián a mano— queda registrado en `trace.interventions` con su motivo, lo que prometía y
lo que acabó entregando.

```python
import sqlite3, pandas as pd
con = sqlite3.connect("data/processed/trace.db")
pd.read_sql_query("SELECT gw, author, rationale, expected_delta, realized_delta "
                  "FROM interventions WHERE run_id=? ORDER BY gw", con, params=(run_id,))
```

Los dos números no son lo mismo y no hay que confundirlos: `expected_delta` es lo que el
modelo **creía**, `realized_delta` lo que **pasó**. La brecha media entre ambos es la
calibración de quien interviene, y es la cifra que de verdad lo retrata.

## 9. Desde la GW2

Hace falta el **id del equipo** para leer el estado real. Se obtiene entrando a la web de
FPL con la cuenta: el número aparece en la URL `/entry/<ID>/event/<GW>/`.

**Ya resuelto:** el equipo real es `losmillosFPL`, creado por browser automation el
2026-08-09 (ver `.claude/skills/fpl-web-ops/SKILL.md`).

```bash
export FPL_TEAM_ID=3609854
```

Lo que el motor deriva de ahí, todo con GET públicos:

| Dato | De dónde |
|---|---|
| Plantilla vigente | `picks` de la última jornada jugada |
| Banco | `entry_history.bank` |
| Chips gastados | `history.chips` |
| Transferencias libres | **Derivadas**: la API pública no las expone, se replica la regla desde la GW1 |

**Limitación declarada (H-LIVE-01):** el precio de *compra* solo lo da el endpoint
autenticado, que no tocamos. Se asume el precio corriente, así que el presupuesto de venta
queda algo sobreestimado para jugadores que subieron de precio.

### Recuperación del export y reintentos de cierre (28/10/2026)

El exportador de trace consume el mismo contrato validado que el cálculo:
manual/autonomous v1 y v2. Conserva el origen manual y `scheduler_save=false`;
liquidar automáticamente una ejecución manual no acredita un Save autónomo.
El scheduler usa la revisión de cierre `v2`, conservando los jobs fallidos `v1`.
Una corrida fallida puede recuperarse en hasta tres jobs independientes, con cinco
minutos de espera entre intentos. No borra errores ni reinicia contadores. Un replay
fallido, en ejecución o sin settlement durable no resuelve incidentes. Agotar los
intentos exige diagnóstico y una corrección verificada.


## Salud mínima antes de la GW (ADR-022)

No hay watchdog. Al preparar la GW: `mova data status` y `mova doctor --no-network`. Los
requeridos son colector `fpl_official` sano, Postgres y API arriba, `ops.db`, joblibs,
disco ≥ 20 GiB y backup < 36 h. Una alerta única (`mova alerts health`, tras cada
`collect all`) avisa si `fpl_official` lleva > 6 h mal o el disco baja de 20 GiB. Incidentes
viejos del harness: `mova incidents close-obsolete --actor A --reason R --idempotency-key K`.
