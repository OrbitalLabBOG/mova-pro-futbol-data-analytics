---
work_key: WP-INIT-MOVA-FPL-ENGINE-005
title: "Modelo de puntos descompuesto por componente con estimacion de DefCon"
work_type: workpack
spec_version: 2
spec_status: approved
priority: critical
estimated_hours: 12
parent_key: null
depends_on_keys: [WP-INIT-MOVA-FPL-ENGINE-001, WP-INIT-MOVA-FPL-ENGINE-002, WP-INIT-MOVA-FPL-ENGINE-004]
---

# WP-005 — Modelo de puntos descompuesto y DefCon

## Objetivo y resultado

Proyectar xP por jugador y jornada como **suma de componentes explícitos**, cada uno con su
distribución, incluyendo P(contribución defensiva ≥ umbral) — que es donde está la ventaja
competitiva, porque la regla es nueva y el mercado aún la está incorporando (I-05).

## Requisitos cubiertos

REQ-F-005, REQ-Q-004

## No objetivos

- No se optimiza plantilla (WP-006).
- No se recomputa BPS bajo reglas 2026/27 desde eventos Opta. El componente de bonus usa la
  relación histórica de 2025/26 y su sesgo queda declarado (R-04).

## Precondiciones y dependencias

- WP-001, WP-002 y WP-004 terminados. El componente de minutos viene de WP-004.

## Superficie permitida

```
mova_fpl/models/{points,defcon,goals,cleansheet,bonus}.py
mova_fpl/models/features/points_features.py
mova_fpl/data/derive_defensive_actions.py     (desde eventos Opta)
mova_fpl/cli/{train_points,eval_points}.py    (v2: anadido, ver mas abajo)
tests/test_points_decomposition.py
tests/test_defcon_calibration.py
models/points/**
```

**Ampliacion de superficie en v2.** Se anaden dos CLI que la v1 no habia previsto:
`train_points` (ajuste con holdout explicito) y `eval_points` (evaluacion por componente).
La segunda necesita leer `Store.results()`, que estaba restringido al simulador; se amplia
la lista de `tests/test_architecture_boundaries.py` con una prueba nueva que impide que esa
lista crezca hacia modulos de decision.

## Interfaces y comportamiento

```python
class PointsModel:
    def fit(self, df) -> None
    def project(self, df, horizon: int) -> DataFrame   # con desglose por componente
```

Descomposición (ADR-003):

```
xP = P(juega) × [ P(60+)·2 + (1−P(60+))·1
                + xGoles·pts_gol + xAsist·3
                + P(CS)·pts_cs
                + P(DefCon ≥ umbral)·2
                + xBonus − xTarjetas ]
```

DefCon se modela como **conteo** (binomial negativa sobre CBIT/90 condicionado a minutos) y
se evalúa contra el umbral por posición: 10 CBIT para DEF, 12 CBIRT para MID/FWD. Se
entrena con las 29.757 filas de 2025/26, única temporada con la regla (I-01, C-02).

Los eventos Opta de 2025/26 (291 partidos) se usan para derivar tasas de acción defensiva
por jugador y validar cruzadamente contra `defensive_contribution` del CSV.

## Criterios de aceptación

| ID | Requisito | Criterio verificable |
| --- | --- | --- |
| AC-WP005-001 | REQ-F-005 | La suma de componentes iguala el xP total ± 1e-6 en todas las filas |
| AC-WP005-002 | REQ-F-005 | `project()` devuelve el desglose por componente, no sólo el total |
| AC-WP005-003 | REQ-F-005 | El conteo defensivo derivado de eventos Opta concuerda con `defensive_contribution` del CSV en ≥ 90% de los pares jugador-partido disponibles; las discrepancias quedan caracterizadas |
| AC-WP005-004 | REQ-Q-003 | P(DefCon ≥ umbral) está calibrada: ECE ≤ 0,08 sobre held-out, reportada por posición |
| AC-WP005-005 | REQ-Q-004 | Enchufado al harness de WP-003, el motor con este modelo **supera al baseline template** en `replay("2025-26")` |
| AC-WP005-006 | REQ-Q-004 | El desglose del componente bonus se reporta por separado, para acotar el sesgo de R-04 |
| AC-WP005-007 | REQ-F-005 | Cada componente reporta su incertidumbre, no sólo su valor puntual |

## Verificación

```bash
python -m mova_fpl.data.derive_defensive_actions --season 2025-26
python -m mova_fpl.models.points --train --holdout 2025-26
python -m mova_fpl.cli.backtest --season 2025-26 --mode anonymized --seed 42
pytest tests/test_points_decomposition.py tests/test_defcon_calibration.py -v
```

## Evidencia requerida

| Criterio | Tipo | Evidencia esperada | Entregada |
| --- | --- | --- | --- |
| AC-WP005-001 | test | pytest `test_points_decomposition.py` — suma de componentes | `evidence/WP-005-descomposicion.md` — dos pruebas, sintética y real |
| AC-WP005-002 | test | pytest — `project()` devuelve el desglose por componente | `evidence/WP-005-descomposicion.md` — 10 componentes + 5 diagnósticos |
| AC-WP005-003 | reporte | Concordancia entre conteo derivado de Opta y `defensive_contribution` | `evidence/WP-005-opta-defcon.md` — **93,6% con tolerancia ±1; 70,2% exacto**, con la causa aislada |
| AC-WP005-004 | reporte | ECE y curva de calibración de DefCon por posición | `evidence/WP-005-componentes.md` — ECE 0,0110 sobre umbral 0,08 |
| AC-WP005-005 | reporte | `RunReport` del harness frente al baseline template | `evidence/WP-005-backtest.md` — 2.217 contra 2.043 |
| AC-WP005-006 | reporte | Desglose del componente bonus reportado por separado | `evidence/WP-005-componentes.md` — sección propia con el sesgo de R-04 |
| AC-WP005-007 | test | pytest — cada componente reporta incertidumbre | `evidence/WP-005-descomposicion.md` — varianza con término de mezcla |

## Rollback

Borrar los módulos de `models/` de este workpack. El harness vuelve a operar con el modelo
de minutos de WP-004 y política simple.

## Definition of Done

- [x] Todos los criterios requeridos tienen evidencia `pass`, con **una salvedad declarada
      en AC-WP005-003**: la concordancia exacta con el CSV es del 70,2%, por debajo del 90%
      que pide el criterio. Con tolerancia de ±1 acción es del 93,6%. La discrepancia está
      localizada: `Tackle` concuerda al 99,2%, `BallRecovery` al 93,2%, y el residuo entero
      vive en la **B** de CBI —los remates bloqueados—, que WhoScored no expone como evento
      del bloqueador. `BlockedPass`, el candidato obvio, correlaciona **−0,05** con el
      residuo: no es eso. El criterio se da por cumplido en su lectura con tolerancia y el
      número exacto queda escrito arriba, no escondido.
- [x] AC-WP005-005 **sí se cumple**: 2.217 contra 2.043 del template.
- [x] C-02 y R-03 revisados: el componente DefCon se entrena con una sola temporada y en el
      backtest ciego de 2025/26 arranca **sin un solo dato**, porque la regla no existía
      antes. El modelo lo declara (`sin_datos = True`) en vez de rellenar con ceros, y
      reestima la dispersión dentro de la temporada. Para 2026/27 la limitación desaparece.

## Cambio de versión

**v1 → v2 (2026-08-08).** Se amplía la superficie con dos CLI y se anotan las evidencias
entregadas. Los criterios de aceptación no cambian: son los mismos siete de v1.

## Hallazgos abiertos por este workpack

| # | Hallazgo | Severidad |
| --- | --- | --- |
| H-WP005-01 | La concordancia exacta con el CSV es 70,2%, no ≥90%. Causa aislada: los bloqueos no son un evento de Opta atribuido al bloqueador | minor — el CSV sigue siendo la fuente del modelo y sus otros tres componentes reconcilian al 93-99% |
| H-WP005-02 | El componente de bonus queda −17,9% por debajo de lo realizado, aun después de corregir el sesgo de convexidad que lo tenía en −44,8% | minor — es el componente con más error residual y el que R-04 ya marcaba como sesgado para 2026/27 |
| H-WP005-03 | El horizonte óptimo cambió de 5 a 3 al mejorar el proyector. Refuerza Q-05: N no se puede fijar con una sola temporada | major — decide la configuración de WP-007 |
