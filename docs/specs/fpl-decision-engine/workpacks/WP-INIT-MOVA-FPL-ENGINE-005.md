---
work_key: WP-INIT-MOVA-FPL-ENGINE-005
title: "Modelo de puntos descompuesto por componente con estimacion de DefCon"
work_type: workpack
spec_version: 1
spec_status: draft
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
tests/test_points_decomposition.py
tests/test_defcon_calibration.py
models/points/**
```

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

| Criterio | Tipo | Evidencia esperada |
| --- | --- | --- |
| AC-WP005-001 | test | pytest `test_points_decomposition.py` — suma de componentes |
| AC-WP005-002 | test | pytest — `project()` devuelve el desglose por componente |
| AC-WP005-003 | reporte | Concordancia entre conteo derivado de Opta y `defensive_contribution` |
| AC-WP005-004 | reporte | ECE y curva de calibración de DefCon por posición |
| AC-WP005-005 | reporte | `RunReport` del harness frente al baseline template |
| AC-WP005-006 | reporte | Desglose del componente bonus reportado por separado |
| AC-WP005-007 | test | pytest — cada componente reporta incertidumbre |

## Rollback

Borrar los módulos de `models/` de este workpack. El harness vuelve a operar con el modelo
de minutos de WP-004 y política simple.

## Definition of Done

- [ ] Todos los criterios requeridos tienen evidencia `pass`.
- [ ] Si AC-WP005-005 no se cumple, el resultado se publica igual y se abre hallazgo — no se maquilla.
- [ ] C-02 y R-03 revisados: la incertidumbre del componente DefCon está declarada.
