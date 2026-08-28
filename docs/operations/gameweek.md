# Runbook — operar una jornada de FPL

Para la persona que tiene que emitir el acta antes del cierre, incluso si algo se rompió.

---

## 0. Lo que hay que saber antes de tocar nada

- **El motor de decisión no escribe en FPL.** Su única primitiva de red es un `GET`
  (`data/sources.py`), verificado por `tests/test_readonly_http.py`. El browser del stack VPS
  es otro runtime y permanece cerrado en `shadow/A0`; ver `runbook-fpl-vps.md`.
- **La única acta que cuenta es la última.** Los precios se mueven a diario y el parte
  médico cambia hasta minutos antes del cierre. Un acta emitida con más de dos días de
  antelación se marca sola como borrador.
- **El deadline no se mueve.** GW1 de 2026/27: `2026-08-21T17:30:00Z` = 12:30 en Bogotá.

## 1. Correr una jornada

```bash
cd ~/code/orbital-lab/mova-pro-futbol-data-analytics

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
