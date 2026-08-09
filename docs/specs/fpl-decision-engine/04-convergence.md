---
type: project
name: "Motor de decision FPL 2026/27 - modelos, reglas y harness de backtest blind — Convergencia"
created: 2026-08-07
updated: 2026-08-09
tags: [convergence, evidence, fpl-decision-engine]
status: draft
---

# Motor de decisión FPL 2026/27 — Convergencia

## Veredicto

**CONCERNS** — Los siete workpacks están cerrados y los veinte requisitos tienen evidencia.
El motor supera al baseline `template` por primera vez en la historia del proyecto y el
acta de la GW1 se emite contra datos reales de 2026/27 en 5,6 segundos.

Quedan **tres asuntos abiertos** que no impiden operar la GW1 pero sí condicionan lo que
viene: falta el `entry_id` (bloquea desde la GW2), el horizonte de producción no está
demostrado, y el sistema en vivo usa una señal que el backtest no tiene.

## Versión evaluada

| | |
|---|---|
| Paquete | versión 1, `approved` |
| Rama | `feat/fpl-agent-clean` |
| Commits | `87a29bc` (WP-001) · `a2ae39d` (WP-002/003) · `eea2e7c` (WP-004) · `8f67d99` (WP-006) · `a1bc287` (WP-005) · WP-007 en este commit |
| Suite | 524 pruebas verdes + 2 marcadas `slow` |
| Validador | `PASS` en modo `execute` |
| Entorno | Python 3.13.5 · pandas 2.3.3 · scikit-learn 1.7.2 · PuLP 3.3.2 · SciPy 1.16.3 |
| Datos | 253.890 filas, 10 temporadas (2016-17 … 2025-26) |

## Cobertura requisito → evidencia

| Requisito | Workpack | Criterio | Evidencia | Estado |
| --- | --- | --- | --- | --- |
| REQ-F-001 esquema con nulos honestos | WP-001 | AC-WP001-001..003 | `WP-001-coverage.md` | pass |
| REQ-F-002 contrato `as_of` | WP-001 | AC-WP001-004 | `WP-001-tests.md` · `test_store_as_of.py` | pass |
| REQ-F-003 motor de reglas fiel | WP-002 | AC-WP002-001 | `WP-002-golden.md` — 100% sobre 29.757 filas | pass |
| REQ-F-004 modelo de minutos | WP-004 | AC-WP004-001..004 | `WP-004-calibracion.md` — ECE 0,0106 | pass |
| REQ-F-005 xP descompuesto | WP-005 | AC-WP005-001..002, 007 | `WP-005-descomposicion.md` | pass |
| REQ-F-006 optimizador con horizonte | WP-006 | AC-WP006-001..006 | `WP-006-restricciones.md` · `WP-006-horizonte.md` | pass |
| REQ-F-007 una sola `decide()` | WP-003 | AC-WP003-001 | `test_engine_skeleton.py` — huellas idénticas | pass |
| REQ-F-008 backtest walk-forward | WP-003 | AC-WP003-002..004 | `WP-003-backtest-2025-26.md` | pass |
| REQ-F-009 baselines obligatorios | WP-003 | AC-WP003-005 | template 2.043 · random 533 · techo 5.871 | pass |
| REQ-F-010 traza persistente | WP-003 | AC-WP003-006 | traza `2026-27-live-milp-h3`, estado `committed` | pass |
| REQ-F-011 acta de GW1 | WP-007 | AC-WP007-001..003 | `WP-007-acta-gw01.md` | pass |
| REQ-Q-001 instrumentación de leakage | WP-001 | AC-WP001-005 | `assert_causal` activa siempre, no solo en tests | pass |
| REQ-Q-002 fidelidad de reglas | WP-002 | AC-WP002-002 | `WP-002-golden.md` — 100%, cero discrepancias | pass |
| REQ-Q-003 calibración | WP-004 · WP-005 | AC-WP004-002 · AC-WP005-004 | ECE minutos 0,0106 · ECE DefCon 0,0110 | pass |
| REQ-Q-004 superar baselines | WP-005 · WP-006 | AC-WP005-005 · AC-WP006-007 | **2.217 vs 2.043** del template | pass |
| REQ-Q-005 reproducibilidad | WP-003 | AC-WP003-007 | huella estable por decisión; misma semilla, mismo resultado | pass |
| REQ-Q-006 ciclo ≤ 10 min | WP-007 | AC-WP007-004 | **5,6 s** | pass |
| REQ-Q-007 fronteras de arquitectura | WP-001 | AC-WP001-006 | `test_architecture_boundaries.py` sobre 30 módulos | pass |
| REQ-S-001 sin secretos ni PII | WP-001 | AC-WP001-007 | `test_no_secrets.py` | pass |
| REQ-S-002 solo lectura externa | WP-001 · WP-007 | AC-WP001-008 · AC-WP007-005 | `test_readonly_http.py` — un solo `urlopen`, method GET | pass |

**20 de 20 requisitos con evidencia.** Uno con salvedad declarada: AC-WP005-003 (concordancia
con Opta) alcanza el 93,6% con tolerancia ±1 pero solo el 70,2% exacto, contra el ≥90% que
pedía el criterio. La causa está aislada y escrita.

## Resultado medido

| Configuración | 2025-26 | vs template |
|---|---:|---:|
| Punto de partida del proyecto (greedy + prior de precio) | 1.302 | −741 |
| WP-004 modelo de minutos | 1.298 | −745 |
| WP-006 optimizador MILP | 2.131 | +88 |
| **WP-005 modelo por componentes** | **2.217** | **+174** |
| Baseline `template` | 2.043 | — |
| Techo con información perfecta | 5.871 | — |

Captura del techo: **37,8%**.

## Drift detectado

Ninguno entre spec, código y comportamiento. Verificaciones corridas:

- Los siete hashes SHA-256 de los workpacks en Git coinciden con `tasks.spec_hash` en Supabase.
- El validador del paquete pasa en modo `execute`.
- Las fronteras del grafo de dependencias se verifican por test, no por convención.
- El backtest con semilla 42 es reproducible: mismas huellas de decisión.

Dos **desviaciones de superficie** declaradas en los workpacks, no silenciosas:

| Workpack | Previsto en v1 | Implementado | Por qué |
|---|---|---|---|
| WP-005 | sin CLI | `cli/train_points.py`, `cli/eval_points.py` | La evaluación por componente necesita el oráculo; se amplió la lista permitida y se añadió una prueba que impide que crezca hacia módulos de decisión |
| WP-007 | `data/sources/fpl_live.py` | `data/live.py` sin red | Habría dejado dos puntos de salida a internet y debilitado la garantía de REQ-S-002 |

## Decisiones emergentes y deuda

### ADR-007 — la función objetivo (emergente)

Q-02 bloqueaba WP-006. Se resolvió reformulándola: v1 maximiza puntos esperados y el caso
mini-liga es un término lineal (`risk_lambda`, declarado y en cero) sobre las mismas
variables. Dejó de ser una decisión de arquitectura para ser una de configuración.

### Lo que se aprendió y no estaba en el plan

**Modelo y política se multiplican, no se suman.** La misma mejora de proyección vale +35
puntos bajo la política voraz y +207 bajo el optimizador. Y al revés: en WP-004 un modelo
mejor no movió el resultado porque la política no actuaba sobre él. El plan trataba los
workpacks como sumandos independientes; no lo son. Esto justificó ejecutar WP-006 antes que
WP-005, contra el orden del plan.

**Descomponer sirve para encontrar errores, no solo para explicar.** Un total que cuadra
puede esconder dos componentes que se compensan. Medir uno por uno destapó un sesgo de
−44,8% en bonus y +43,5% en paradas que el agregado ocultaba.

**Las estimaciones estaban en la escala equivocada.** 80 horas planificadas, 4,5 reales. El
riesgo R-01 —cronograma— nunca fue el riesgo real.

### Deuda abierta

| # | Asunto | Severidad | Dueño |
|---|---|---|---|
| Q-01 | Falta el `entry_id` del equipo | **bloqueante desde GW2** | Julián |
| Q-05 | Horizonte de producción sin demostrar. Se opera con 3 por defecto razonado | major | evidencia / más temporadas |
| H-WP007-01 | La decisión en vivo usa el parte médico y el backtest no. El 2.217 no es exactamente el sistema que opera; el sesgo es favorable pero no está cuantificado | major | medición |
| H-WP005-01 | Concordancia exacta con Opta 70,2% frente al 90% pedido, con causa aislada en los remates bloqueados | minor | aceptado |
| H-WP005-02 | El componente de bonus sigue −17,9% por debajo | minor | WP futuro |
| L-01 | El calendario se lee de datos ya ingeridos, así que incorpora reprogramaciones que en su momento podían no estar anunciadas | minor | aceptado |
| R-04 | El componente bonus queda sobreestimado para defensas y porteros en 2026/27 por el cambio de BPS | minor | declarado, se reporta aparte |
| C-02 / R-03 | DefCon se entrena con una sola temporada. En 2026/27 la limitación desaparece | minor | resuelto por el tiempo |

## Lo que este paquete NO demuestra

- **Que el motor vaya a ganar la temporada 2026/27.** Demuestra que en 2025-26, con
  información estrictamente causal, habría sacado 2.217 puntos contra 2.043 de copiar a la
  multitud. Una temporada es una muestra de una.
- **Que h=3 sea el horizonte correcto.** El orden entre horizontes se invirtió al cambiar el
  proyector: está dentro del ruido.
- **Que el 37,8% de captura del techo sea un buen número.** No hay con qué compararlo: no
  existe un benchmark público de captura de techo en FPL. Sirve para medir progreso propio,
  no posición relativa.

## Siguiente iteración

Nada de esto está en el alcance de v1 y todo requiere una iniciativa nueva:

1. **Q-01 y operar desde la GW2** — leer estado real, arrastrar plantilla, transferencias.
2. **El agente LLM** que ADR-006 dejó fuera de v1: alineaciones probables, ruedas de prensa,
   foros. Es la información que hoy falta y que el almacén no puede dar.
3. **Política de chips**, hoy heurística nula (Q-04).
4. **Cron** — `decide()` no tiene estado global, así que montarlo es trabajo de infraestructura.
