# Motor de decisión FPL — arquitectura

> Referencia técnica del paquete `mova_fpl/`. Cómo funciona por dentro y por qué está hecho
> así. Para **operar** una jornada → [runbook-fpl.md](runbook-fpl.md). Para el registro de
> diseño con las alternativas que se descartaron → [specs/fpl-decision-engine/](specs/fpl-decision-engine/).
>
> Última actualización: 2026-08-09 · rama `feat/fpl-agent-clean` · v1 cerrada

---

## 1. Qué problema resuelve

Cada jornada de la Premier League hay que elegir once jugadores de quince, un capitán, y
decidir si gastar transferencias. Los quince salen de un mercado de ~570 jugadores con un
presupuesto de £100M, máximo tres por club y cuotas por posición. Las transferencias por
encima de las libres cuestan −4 puntos, y las libres se acumulan hasta cinco. Las decisiones
de hoy condicionan las de dentro de cinco jornadas.

Es un problema de optimización bajo incertidumbre con dos mitades bien distintas:

1. **Predecir** cuántos puntos hará cada jugador — un problema estadístico.
2. **Decidir** qué hacer con esas predicciones — un problema combinatorio.

El proyecto trató durante meses la segunda mitad como si fuera trivial. No lo es: el
optimizador solo, sin tocar el modelo, valió **+833 puntos**. Y la relación entre las dos
mitades no es aditiva sino multiplicativa: la misma mejora de proyección vale +35 puntos bajo
una política voraz y **+207** bajo el optimizador. Un modelo mejor no sirve de nada si la
política no actúa sobre él.

## 2. El flujo, de punta a punta

```
                    ┌──────────────────────────────────────────────┐
   fpl_canonical.db │  Store.as_of(temporada, jornada)             │  ← ÚNICA lectura
   254K filas       │  verifica el resultado contra el futuro      │
   10 temporadas    └──────────────────┬───────────────────────────┘
                                       │ history + roster
                    ┌──────────────────▼───────────────────────────┐
                    │  MinutesModel → P(0) · P(1-59) · P(60+)      │  ECE 0,0106
                    └──────────────────┬───────────────────────────┘
                                       │
                    ┌──────────────────▼───────────────────────────┐
                    │  PointsModel.project → xP por COMPONENTE     │
                    │  condicionado a cada rama de minutos         │
                    └──────────────────┬───────────────────────────┘
                                       │ xP, varianza, desglose
                    ┌──────────────────▼───────────────────────────┐
                    │  build_xp_matrix → xP[jugador][jornada]      │  descuento 0,84^t
                    │  dobles ×2 · blancos 0                       │
                    └──────────────────┬───────────────────────────┘
                                       │
                    ┌──────────────────▼───────────────────────────┐
                    │  shortlist (opcional) → recorte de mercado   │
                    └──────────────────┬───────────────────────────┘
                                       │
                    ┌──────────────────▼───────────────────────────┐
                    │  solve() MILP · PuLP/CBC                     │
                    │  plantilla · once · capitán · compras/ventas │
                    └──────────────────┬───────────────────────────┘
                                       │ Decision
                    ┌──────────────────▼───────────────────────────┐
                    │  validate_squad → report.render → acta .md   │
                    │  trace.writer → trace.db                     │
                    └──────────────────────────────────────────────┘
```

Dos consumidores distintos alimentan el mismo flujo:

| Consumidor | De dónde saca el estado | Para qué |
|---|---|---|
| `cli/live.py` | API de FPL, solo `GET`, sin persistir | Emitir el acta de la jornada |
| `engine/simulator.py` | `Store.as_of`, con nombres anonimizados | Backtest ciego de una temporada |

Ambos construyen un `State` y llaman a la **misma** `decide()`. Es lo que impide que el
backtest deje de decir algo sobre producción.

## 3. Los módulos

| Módulo | Líneas | Qué hace | Qué NO hace |
|---|---:|---|---|
| `data/` | 1.009 | Ingesta idempotente, identidad estable de jugador, `Store` | No decide, no proyecta |
| `rules/` | 615 | Reglas FPL puras versionadas por temporada | **No lee datos.** Ni un import de `data/` |
| `models/` | 1.262 | Minutos, puntos por componente, DefCon, bonus, goles, portería a cero | No ve resultados futuros |
| `optimizer/` | 497 | MILP, horizonte rodante, prefiltro | No sabe qué es un jugador; opera sobre números |
| `engine/` | 1.208 | `decide()`, proyección, políticas, simulador, acta | — |
| `trace/` | 220 | Persistencia de corridas y decisiones | — |
| `cli/` | 505 | Siete comandos | **Ninguna lógica propia.** Solo cablean |

Las fronteras no son un acuerdo: `tests/test_architecture_boundaries.py` recorre el grafo de
importaciones de los 30 módulos y falla si alguna se cruza.

### 3.1 `data/` — el contrato causal

Todo dato entra por un único método:

```python
Store.as_of(season, gw)          # historia estrictamente anterior a (season, gw)
Store.roster(season, gw)         # quién existe y a qué precio, sin resultados
Store.team_schedule(season, a, b)  # cuántos partidos juega cada club por jornada
Store.results(season, gw)        # ⚠️ el ORÁCULO. Solo el simulador y el evaluador
```

`as_of` verifica **después** de consultar, no antes: `assert_causal(df, season, gw)` revisa
el DataFrame devuelto y lanza `LeakageError` si trae una fila del futuro. Está activa
siempre, también en producción. La diferencia importa: una comprobación previa valida la
intención; una posterior valida el hecho.

`results()` es el oráculo y solo dos módulos pueden llamarlo. Hay una prueba que verifica la
lista permitida y otra que verifica que **ningún módulo de decisión** esté en ella, para que
no crezca por conveniencia.

### 3.2 `rules/` — funciones puras, versionadas

Las reglas de 2026/27 no son las de 2025-26: cambió el reparto de BPS y entró la contribución
defensiva. Por eso son datos versionados por temporada, no constantes:

```python
defcon_points=2
defcon_thresholds={DEF: 10, MID: 12, FWD: 12}   # DEF cuenta CBIT; MID/FWD, CBIRT
```

Se validaron reproduciendo el `total_points` real de **29.757 actuaciones** de 2025-26 a
partir de sus componentes crudos: **100% exacto, cero discrepancias**. `rules/diff.py`
compara dos temporadas y produce el listado de cambios.

Ningún módulo de `rules/` importa nada de `data/`. Una regla es una función de sus argumentos.

### 3.3 `models/` — por qué descompuesto

Un modelo monolítico predice `total_points` de una vez. Este predice cada componente por
separado y los suma:

```
pts_aparicion · pts_goles · pts_asistencias · pts_cs · pts_encajados
pts_defcon · pts_bonus · pts_tarjetas · pts_paradas · pts_otros
```

Tres razones, en orden de importancia:

1. **Las reglas de FPL no son lineales en los minutos.** La portería a cero solo paga a
   partir del minuto 60; la aparición paga 1 punto antes y 2 después. Proyectar sobre los
   minutos esperados da una respuesta distinta —y peor— que proyectar en cada rama y mezclar.
   Por eso `_rama()` calcula todo condicionado a "juega parcial" y a "juega completo", y
   después mezcla con las probabilidades del modelo de minutos.
2. **Cada componente tiene su distribución natural.** Poisson para goles, asistencias y goles
   encajados; binomial negativa para el conteo de acciones defensivas (sobredispersa);
   Bernoulli para la portería a cero. Un `E[floor(X/n)]` —paradas, goles encajados— se calcula
   sumando la pmf, no dividiendo la media: la diferencia era un sesgo del +43,5%.
3. **Descomponer encuentra errores que el agregado esconde.** Dos componentes con sesgos de
   signo opuesto dan un total que cuadra. Medir uno por uno destapó −44,8% en bonus y +43,5%
   en paradas, que se compensaban.

La varianza se propaga con el término de mezcla, no sumando varianzas:
`Var = Σ_rama P(rama)·(Var_rama + μ_rama²) − xP²`.

**Encogimiento hacia el prior.** Las tasas por 90 minutos de un jugador con pocos partidos no
son informativas. `shrink(observado, n, prior, k)` las mezcla con la mediana de su posición
—mediana, no media: la media la arrastran los cuatro delanteros de élite—. La fuerza del club
se estima solo con la **última temporada**: promediar diez le daba a un recién ascendido el
rendimiento de la última vez que estuvo en Primera.

### 3.4 `optimizer/` — el MILP

Variables binarias por jugador y jornada: en plantilla, en el once, capitán, comprado,
vendido. Objetivo:

```
max  Σ_t 0,84^t · [ Σ_i xp[i,t]·once[i,t] + xp[cap,t] + 0,12·Σ_i xp[i,t]·banco[i,t] ]
     − 4 · Σ_t golpes[t]
     − risk_lambda · (término de riesgo)
```

Restricciones que importan:

- **Dinero como conservación, no como tope.** `bank[t] = bank[t-1] + ventas − compras`, todo
  en décimas enteras (`rules/money.py`) para que no haya errores de coma flotante. Las ventas
  usan el `selling_price`, que no es el precio de mercado.
- **Transferencias libres, linealizadas.** La recursión "acumulas una por jornada hasta cinco"
  no es lineal. Se relaja a `ft[t+1] ≤ libres − usadas + golpes[t] + 1`, que es exacta en el
  óptimo porque el modelo nunca prefiere tirar una transferencia libre.
- **Arranque en frío.** Construir los quince desde cero son quince transferencias; con la
  recursión normal, `5 − 15 + 1 = −9` y el problema sale infactible. La primera jornada de una
  temporada fija `ft = 1` explícitamente.

`Infeasible` no es una excepción muda: trae la lista de motivos concretos (*"solo N porteros
en el mercado"*, *"la plantilla más barata cuesta X"*).

**El prefiltro** (`heuristics.shortlist`) recorta el mercado a los `top_k` por posición más
los `cheapest` más baratos, y **siempre** conserva a los jugadores que ya están en la
plantilla. Cuesta **0,000%** de optimalidad hasta horizonte 5. A horizonte 8 es al revés: sin
recortar, el solver choca contra el límite de tiempo y devuelve algo peor. En vivo se usa
`--top-k 0` —sin recorte— porque con 570 jugadores y horizonte 3 sobra tiempo.

### 3.5 `engine/` — una sola decisión

```python
decide(gw, state, config) -> Decision
```

Sin estado global. El estado entra como parámetro y sale como valor, que es lo que hará
trivial montarlo como cron más adelante. `config.policy` selecciona la política (`milp` o
`greedy-stub`, el plan B); `config.projector` selecciona el proyector (`points`, `minutes` o
`naive`).

El **simulador** anonimiza jugadores y clubes con alias estables por temporada antes de pasar
el estado a `decide()`. No es cosmético: sin eso el modelo podría reconocer la temporada por
los nombres. Hay una prueba que verifica que el alias es el mismo a lo largo de las 38
jornadas —si cambiara, el motor perdería el rastro de su propia plantilla—.

El **acta** (`report.render`) se marca sola como **borrador** si se emite a más de dos días
del cierre. A esa distancia los precios y el parte médico todavía se mueven.

## 4. Resultados medidos

Backtest ciego de 2025-26, 38 jornadas, semilla 42, nombres anonimizados:

| Configuración | Puntos | Δ |
|---|---:|---:|
| Voraz + prior de precio (punto de partida) | 1.302 | — |
| Voraz + modelo de minutos | 1.298 | −4 |
| MILP h=5 + modelo de minutos | 2.131 | +833 |
| **MILP h=3 + modelo por componentes** | **2.217** | **+86** |
| Baseline `template` | 2.043 | |
| Baseline aleatorio | 533 | |
| Techo con información perfecta | 5.871 | |

Calibración: ECE del modelo de minutos **0,0106** (baseline 0,0416), Brier 0,0820. ECE de
DefCon **0,0110**.

Ciclo en vivo completo: **5,6 s** contra un techo de diez minutos.

## 5. Los mandos

| Mando | Defecto | Qué cambia |
|---|---|---|
| `--horizon N` | 3 | Jornadas que mira hacia adelante. Ver Q-05 |
| `--top-k K` | 30 (0 en vivo) | Recorte de mercado por posición |
| `decay` | 0,84 | Cuánto vale una jornada futura frente a la de hoy |
| `bench_weight` | 0,12 | Valor del banquillo en el objetivo |
| `max_hits` | 2 | Tope de transferencias pagadas por jornada |
| `risk_lambda` | **0,0** | Aversión al riesgo. En cero, maximiza puntos esperados |

`risk_lambda` merece una nota. La pregunta "¿optimizar para el rank global o para ganar una
mini-liga?" bloqueó el diseño del optimizador. Se resolvió **no respondiéndola**: el caso
mini-liga es un término lineal sobre las mismas variables, declarado y en cero. Dejó de ser
una decisión de arquitectura para ser una de configuración (ADR-007).

## 6. Lo que el sistema no sabe

- **Alineaciones probables y ruedas de prensa.** Es la información que más pesa y que ningún
  almacén histórico puede dar. Requiere un agente de lenguaje, explícitamente fuera de v1.
- **La plantilla real de Julián.** Falta el `entry_id`. Desde la GW2 el motor solo puede
  proponer un equipo desde cero, que no es la decisión que toca (Q-01).
- **Cuál es el horizonte correcto.** El orden entre horizontes se invirtió al mejorar el
  proyector, así que está dentro del ruido de una sola temporada (Q-05).
- **Cuánto vale el parte médico.** La decisión en vivo lo usa; el backtest no lo tiene. El
  2.217 no es exactamente el sistema que opera. El sesgo va a favor, pero no está medido
  (H-WP007-01).

## 7. Deuda declarada

| # | Asunto | Severidad |
|---|---|---|
| H-WP005-01 | Concordancia exacta con las acciones defensivas de Opta: 70,2% frente al 90% pedido. Causa aislada en los remates bloqueados | minor, aceptada |
| H-WP005-02 | El componente de bonus sigue ~18% por debajo | minor |
| R-04 | El bonus queda sobreestimado para defensas y porteros en 2026/27 por el cambio de BPS | minor, se reporta aparte |
| L-01 | El calendario se lee de datos ya ingeridos, así que incorpora reprogramaciones que en su momento podían no estar anunciadas | minor, aceptada |

## 8. Dónde está cada cosa

| Quiero… | Ir a |
|---|---|
| Operar una jornada | [runbook-fpl.md](runbook-fpl.md) |
| Saber qué quedó demostrado y qué no | [specs/…/04-convergence.md](specs/fpl-decision-engine/04-convergence.md) |
| Entender por qué se eligió X y no Y | [specs/…/02-architecture.md](specs/fpl-decision-engine/02-architecture.md) y los 7 ADRs |
| Ver la evidencia de un criterio | [specs/…/evidence/](specs/fpl-decision-engine/evidence/) |
| Trabajar en el código | [../CLAUDE.md](../CLAUDE.md) |
