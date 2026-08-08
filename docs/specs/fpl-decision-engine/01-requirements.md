---
type: project
name: "Motor de decision FPL 2026/27 - modelos, reglas y harness de backtest blind — Requisitos"
created: 2026-08-07
updated: 2026-08-07
tags: [requirements, spec-driven, fpl-decision-engine, mova]
status: draft
---

# Motor de decisión FPL 2026/27 — Requisitos

## Convenciones

- `REQ-F-###`: requisito funcional.
- `REQ-Q-###`: atributo de calidad medible.
- `REQ-S-###`: seguridad o privacidad.
- Prioridad: `must`, `should` o `could`.

## Requisitos funcionales

### REQ-F-001 — Almacén canónico multi-temporada

- Prioridad: must
- Fuente: H-04, H-06, H-08 del brief
- Enunciado: El sistema debe consolidar las temporadas 2016-17 a 2025-26 en un esquema
  único player-gameweek, preservando `season` y `GW` como clave temporal, y normalizando
  las diferencias de columnas entre temporadas sin inventar valores.
- Escenario: Dado el conjunto de CSVs descargados, cuando se ejecute la ingesta, entonces
  la tabla canónica debe contener ≥ 250.000 filas, 10 temporadas distintas, y toda columna
  ausente en una temporada debe quedar `NULL` — nunca `0` — y quedar registrada en un
  reporte de cobertura por temporada.
- Estado: draft

### REQ-F-002 — Contrato de lectura temporal `as_of`

- Prioridad: must
- Fuente: H-11 (leakage del código legacy)
- Enunciado: Toda lectura de datos para entrenamiento, features o decisión debe pasar por
  una función `as_of(season, gw)` que devuelva exclusivamente observaciones con `GW < gw`
  de esa temporada. No debe existir ninguna otra vía pública de acceso al almacén.
- Escenario: Dado `as_of(season="2025-26", gw=17)`, cuando se inspeccione el resultado,
  entonces `max(GW)` debe ser 16 y el conjunto de columnas no debe incluir ningún agregado
  calculado sobre filas con `GW >= 17`.
- Estado: draft

### REQ-F-003 — Motor de reglas versionado por temporada

- Prioridad: must
- Fuente: H-03 (BPS cambió entre 2025/26 y 2026/27)
- Enunciado: Las reglas de puntuación y de plantilla deben implementarse como funciones
  puras, sin acceso a datos, seleccionables por temporada. Debe existir al menos
  `rules/2025_26.py` (para el backtest) y `rules/2026_27.py` (para producción).
- Escenario: Dado el diccionario de estadísticas crudas de una actuación real de 2025/26,
  cuando se invoque `rules_2025_26.score(stats)`, entonces el resultado debe igualar el
  `total_points` observado. Dado el mismo input bajo `rules_2026_27.score(stats)`, el
  resultado puede diferir y esa diferencia debe ser explicable por los cambios de BPS.
- Estado: draft

### REQ-F-004 — Modelo de minutos

- Prioridad: must
- Fuente: análisis de arquitectura — es el driver dominante del xP
- Enunciado: El sistema debe estimar, para cada jugador y gameweek, la distribución de
  probabilidad sobre las clases {0 minutos, 1–59, 60+}, usando exclusivamente información
  disponible vía `as_of`.
- Escenario: Dado un jugador y una gameweek objetivo, cuando se solicite la predicción,
  entonces debe devolver tres probabilidades que sumen 1.0 ± 1e-6, y el modelo debe estar
  entrenado sólo con filas anteriores a esa gameweek.
- Estado: draft

### REQ-F-005 — Modelo de puntos descompuesto con DefCon

- Prioridad: must
- Fuente: I-05, H-07
- Enunciado: El xP debe calcularse como suma de componentes explícitos (aparición, goles,
  asistencias, portería a cero, contribución defensiva, bonus, tarjetas), cada uno con su
  propia distribución, y no como una regresión única sobre `total_points`. El componente
  de contribución defensiva debe estimar P(CBIT ≥ 10) para DEF y P(CBIRT ≥ 12) para
  MID/FWD, condicionado a minutos.
- Escenario: Dado un jugador, cuando se solicite su proyección, entonces la respuesta debe
  incluir el desglose por componente y la suma de los componentes debe igualar el xP total
  ± 1e-6.
- Estado: draft

### REQ-F-006 — Optimizador con horizonte multi-gameweek

- Prioridad: must
- Fuente: estado del arte (arXiv 2505.02170) — el horizonte rodante es lo que separa a los
  solvers competentes
- Enunciado: El optimizador debe seleccionar plantilla de 15, XI, capitán y vicecapitán
  maximizando xP sobre un horizonte configurable de N gameweeks (N ≥ 3 por defecto),
  respetando presupuesto, banco, cuota de máximo 3 por club, formaciones válidas y el
  costo de las transferencias adicionales.
- Escenario: Dado un estado de plantilla y un horizonte de 3 jornadas, cuando se resuelva,
  entonces la solución no debe violar ninguna restricción de `rules.squad`, y su xP
  acumulado sobre el horizonte debe ser ≥ al de la solución con horizonte 1 evaluada sobre
  el mismo horizonte.
- Estado: draft

### REQ-F-007 — Función de decisión única

- Prioridad: must
- Fuente: H-12, H-13 — backtest y producción eran dos implementaciones distintas
- Enunciado: Debe existir exactamente una función `decide(gw, state, config) -> Decision`
  invocada tanto por el harness de backtest como por la ejecución en vivo. No debe existir
  lógica de decisión duplicada fuera de ella.
- Escenario: Dado un `state` sintético idéntico, cuando se invoque `decide()` desde el
  harness y desde el runner de producción, entonces ambas invocaciones deben producir un
  `Decision` byte-idéntico.
- Estado: draft

### REQ-F-008 — Harness de backtest walk-forward ciego

- Prioridad: must
- Fuente: objetivo 2 declarado por el sponsor
- Enunciado: El sistema debe reproducir la temporada 2025/26 completa jornada a jornada,
  arrancando sin modelo (cold start en GW1), reentrenando en cada jornada T únicamente con
  datos de 1..T-1, y acumulando los puntos reales obtenidos. Debe soportar modo
  `anonymized` (nombres de jugador y equipo sustituidos por identificadores estables) y
  modo `named`.
- Escenario: Dado `replay(season="2025-26", mode="anonymized")`, cuando termine la corrida,
  entonces debe reportar puntos totales por jornada, el detalle de decisiones, y ninguna
  invocación de entrenamiento debe haber recibido filas con `GW >= T`.
- Estado: draft

### REQ-F-009 — Baselines de comparación

- Prioridad: must
- Fuente: H-14 — los resultados previos no eran comparables contra nada
- Enunciado: El harness debe calcular, sobre la misma temporada y con las mismas reglas, al
  menos tres baselines: (a) plantilla template formada por los jugadores más seleccionados,
  (b) techo con información perfecta, (c) selección aleatoria válida.
- **Señal de cambio (2026-08-07).** El baseline (b) era originalmente "promedio real de la
  gameweek presente en los datos". Al implementarlo se verificó que `average_entry_score`
  **no existe** en el histórico de vaastav; sólo se expone en el bootstrap de la temporada
  en curso (H-24). Se sustituye por el **techo con información perfecta**, que además es
  más informativo: dice qué fracción de lo alcanzable se capturó, en vez de compararse
  contra una media que cualquier motor competente supera trivialmente.
- Escenario: Dado el resultado de un `replay()`, cuando se emita el reporte, entonces debe
  incluir los tres baselines junto al resultado del motor; un reporte sin baselines debe
  considerarse inválido.
- Estado: draft

### REQ-F-010 — Traza persistente de decisiones

- Prioridad: must
- Fuente: requerimiento explícito del sponsor
- Enunciado: Cada corrida y cada decisión por gameweek deben persistirse con: versión de
  modelo, git sha, semilla, configuración, insumos usados, decisión emitida, xP esperado y
  puntos reales cuando se conozcan.
- Escenario: Dada una corrida terminada, cuando se consulte la traza, entonces debe poderse
  responder "en qué jornadas la decisión del motor difirió del baseline template y cuál
  ganó" sin recomputar nada.
- Estado: draft

### REQ-F-011 — Acta de decisión para producción

- Prioridad: must
- Fuente: M-01
- Enunciado: Para una gameweek en vivo, el sistema debe emitir un documento legible con los
  15 jugadores, XI, banco ordenado, capitán, vicecapitán, costo total, banco de dinero
  restante y el desglose de xP por jugador.
- Escenario: Dado `decide()` para GW1 de 2026/27, cuando se genere el acta, entonces debe
  validar contra `rules_2026_27.squad` sin violaciones y registrar su propio timestamp de
  emisión.
- Estado: draft

## Atributos de calidad

### REQ-Q-001 — Ausencia de dependencia temporal futura

- Prioridad: must
- Fuente: H-11
- Estímulo y entorno: Un desarrollador o agente añade una feature nueva al pipeline.
- Respuesta: El sistema impide, por construcción y por test, que esa feature lea
  observaciones con `GW >= gw` objetivo.
- Medida: 0 violaciones. Test automatizado que instrumenta el almacén y falla si cualquier
  ruta de código accede a filas fuera de la ventana `as_of`. Se ejecuta en cada corrida del
  harness, no sólo en CI.

### REQ-Q-002 — Fidelidad del motor de reglas

- Prioridad: must
- Fuente: M-02
- Estímulo y entorno: Se recomputan los puntos de las 29.757 actuaciones de 2025/26 desde
  sus estadísticas crudas.
- Respuesta: El motor reproduce el `total_points` observado.
- Medida: ≥ 99% de coincidencia exacta. Las discrepancias deben quedar enumeradas y
  clasificadas por causa; una discrepancia sin explicación es un bloqueo.

### REQ-Q-003 — Calibración del modelo de minutos

- Prioridad: must
- Fuente: M-05
- Estímulo y entorno: Predicción de P(60+) sobre una temporada held-out no vista.
- Respuesta: Las probabilidades predichas corresponden a frecuencias observadas.
- Medida: Expected Calibration Error ≤ 0.05 en 10 bins, y Brier score reportado junto al de
  un baseline de frecuencia histórica del jugador. Accuracy no es medida aceptable.

### REQ-Q-004 — Desempeño verificable frente a baselines

- Prioridad: must
- Fuente: M-04
- Estímulo y entorno: `replay("2025-26")` completo.
- Respuesta: El motor supera al baseline template.
- Medida: Puntos totales del motor ≥ puntos del template sobre la misma temporada y reglas.
  Si no lo supera, el resultado se publica igual y se trata como hallazgo, no como falla a
  esconder.

### REQ-Q-005 — Reproducibilidad

- Prioridad: must
- Fuente: M-06
- Estímulo y entorno: Dos corridas del harness con la misma semilla, config y git sha.
- Respuesta: Resultados idénticos.
- Medida: Diff vacío entre los dos reportes de traza, excluyendo timestamps.

### REQ-Q-006 — Latencia del ciclo de decisión

- Prioridad: should
- Fuente: M-07 — condición para poder montar cron después
- Estímulo y entorno: `decide()` para una gameweek en vivo, en el portátil de trabajo.
- Respuesta: La decisión se produce dentro de una ventana operable.
- Medida: ≤ 10 minutos de extremo a extremo, incluyendo descarga de datos frescos,
  reentrenamiento y optimización.

### REQ-Q-007 — Modularidad verificable

- Prioridad: must
- Fuente: requerimiento explícito del sponsor ("no quiero otro Frankenstein")
- Estímulo y entorno: Inspección estática de importaciones entre subpaquetes.
- Respuesta: Las fronteras se respetan.
- Medida: Test de arquitectura que falla si `rules/` importa de `data/` o `models/`; si
  `models/` importa de `optimizer/`; o si cualquier módulo de `mova_fpl/` importa de
  `src/mova_data/` o `src/mova_model/`.

## Seguridad y privacidad

### REQ-S-001 — Sin secretos ni datos personales en el repositorio

- Prioridad: must
- Activo o dato protegido: Credenciales de API y datos de terceros.
- Enunciado: El paquete no debe contener claves, tokens ni datos personales. Los datos
  usados son estadísticas deportivas públicas.
- Escenario de abuso/fallo: Un `.env` o un token queda commiteado y se publica en GitHub.
- Control verificable: El paquete no lee variables de entorno secretas en v1 (todas las
  fuentes son públicas sin auth); test que falla si aparece un patrón de clave en los
  archivos del paquete.

### REQ-S-002 — v1 no escribe en sistemas externos

- Prioridad: must
- Activo o dato protegido: La cuenta FPL de Julián y su temporada.
- Enunciado: v1 debe ser estrictamente de sólo lectura frente a servicios externos. No debe
  existir ninguna llamada de escritura a la API de FPL.
- Escenario de abuso/fallo: Un bug en el optimizador ejecuta transferencias reales no
  deseadas y consume hits irreversibles.
- Control verificable: Test que falla si aparece cualquier verbo HTTP distinto de `GET`
  dirigido a `fantasy.premierleague.com`.

## Trazabilidad

| Requisito | Driver/componente | Workpack | Evidencia prevista |
| --- | --- | --- | --- |
| REQ-F-001 | `mova_fpl/data/store.py` | WP-001 | Reporte de cobertura por temporada |
| REQ-F-002 | `mova_fpl/data/store.py` | WP-001 | Test de contrato `as_of` |
| REQ-F-003 | `mova_fpl/rules/` | WP-002 | Golden test sobre 29.757 filas |
| REQ-F-004 | `mova_fpl/models/minutes.py` | WP-004 | Reporte de calibración |
| REQ-F-005 | `mova_fpl/models/points.py` | WP-005 | Desglose por componente + calibración |
| REQ-F-006 | `mova_fpl/optimizer/milp.py` | WP-006 | Test de restricciones + comparación de horizontes |
| REQ-F-007 | `mova_fpl/engine/runner.py` | WP-003 | Test de identidad harness/producción |
| REQ-F-008 | `mova_fpl/engine/simulator.py` | WP-003 | Reporte de `replay()` |
| REQ-F-009 | `mova_fpl/engine/baselines.py` | WP-003 | Tabla de baselines en el reporte |
| REQ-F-010 | `mova_fpl/trace/` | WP-003 | Consulta de traza resuelta |
| REQ-F-011 | `mova_fpl/cli/live.py` | WP-007 | Acta de GW1 validada |
| REQ-Q-001 | `mova_fpl/data/store.py` | WP-001 | Test de instrumentación |
| REQ-Q-002 | `mova_fpl/rules/` | WP-002 | % de coincidencia + tabla de discrepancias |
| REQ-Q-003 | `mova_fpl/models/minutes.py` | WP-004 | ECE y Brier |
| REQ-Q-004 | `mova_fpl/engine/` | WP-005 | Puntos motor vs baselines |
| REQ-Q-005 | `mova_fpl/trace/` | WP-003 | Diff de dos corridas |
| REQ-Q-006 | `mova_fpl/cli/live.py` | WP-007 | Medición de tiempo |
| REQ-Q-007 | estructura del paquete | WP-001 | Test de importaciones |
| REQ-S-001 | repo | WP-001 | Test de patrones de secreto |
| REQ-S-002 | `mova_fpl/data/sources/` | WP-001 | Test de verbos HTTP |

## Conflictos y preguntas

| # | Conflicto detectado | Resolución | Owner |
| --- | --- | --- | --- |
| C-01 | REQ-Q-002 exige recomputar puntos de 2025/26, pero producción usa reglas 2026/27, que no son validables contra ground truth porque la temporada no ha ocurrido | Se acepta: el golden test valida `rules_2025_26`; `rules_2026_27` se valida por revisión contra la fuente oficial y por diff explicado contra la versión anterior. Queda como riesgo declarado | Julián |
| C-02 | REQ-F-005 exige modelar DefCon, pero sólo 2025/26 tiene la regla (I-01): una sola temporada de entrenamiento para ese componente | Se acepta con 29.757 filas. Se reporta intervalo de confianza del componente por separado | Julián |
| C-03 | S-05 supone que 2025/26 es representativa, pero H-03 dice que BPS cambió | El backtest sobreestima el componente bonus. Se documenta como sesgo conocido y se reporta el desglose bonus por separado para acotarlo | Julián |
| C-04 | Q-02 sin respuesta cambia la función objetivo de REQ-F-006 (maximizar puntos vs rank ajustado por ownership) | **Bloqueo para WP-006.** Por defecto se asume maximizar puntos esperados | Julián |
