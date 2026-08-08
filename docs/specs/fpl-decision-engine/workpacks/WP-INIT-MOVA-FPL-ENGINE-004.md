---
work_key: WP-INIT-MOVA-FPL-ENGINE-004
title: "Modelo de minutos calibrado - clasificador {0, 1-59, 60+}"
work_type: workpack
spec_version: 1
spec_status: draft
priority: critical
estimated_hours: 12
parent_key: null
depends_on_keys: [WP-INIT-MOVA-FPL-ENGINE-001, WP-INIT-MOVA-FPL-ENGINE-003]
---

# WP-004 — Modelo de minutos

## Objetivo y resultado

Estimar P(0 min), P(1–59) y P(60+) por jugador y jornada. Es el driver dominante del xP:
un jugador que no juega vale cero sin importar lo bueno que sea, y es donde más se
equivocan los modelos ingenuos.

## Requisitos cubiertos

REQ-F-004, REQ-Q-003

## No objetivos

- No se predicen goles, asistencias ni bonus (WP-005).
- No se usa información de lesiones ni ruedas de prensa: eso requiere búsqueda web, que
  está fuera del alcance de v1 (ADR-006).

## Precondiciones y dependencias

- WP-001 (`as_of`) y WP-003 (harness donde medirse) terminados.

## Superficie permitida

```
mova_fpl/models/{__init__,minutes,registry}.py
mova_fpl/models/features/minutes_features.py
tests/test_minutes_calibration.py
tests/test_minutes_causality.py
models/minutes/**    (artefactos versionados)
```

## Interfaces y comportamiento

```python
class MinutesModel:
    def fit(self, df: DataFrame) -> None
    def predict_proba(self, df: DataFrame) -> ndarray   # (n, 3), filas suman 1
```

Features candidatas, todas causales vía `as_of`: minutos recientes con decaimiento,
volatilidad de minutos, titularidades (`starts`), racha de suplencias, precio como proxy
de estatus, y días de descanso desde el partido anterior.

Entrenamiento con las 10 temporadas del almacén; evaluación held-out por temporada
completa, nunca por muestreo aleatorio de filas.

## Criterios de aceptación

| ID | Requisito | Criterio verificable |
| --- | --- | --- |
| AC-WP004-001 | REQ-F-004 | `predict_proba` devuelve 3 columnas que suman 1.0 ± 1e-6 en todas las filas |
| AC-WP004-002 | REQ-Q-003 | ECE de P(60+) ≤ 0,05 en 10 bins sobre temporada held-out |
| AC-WP004-003 | REQ-Q-003 | Brier de P(60+) reportado junto al de un baseline de frecuencia histórica del jugador, y **mejor** que él |
| AC-WP004-004 | REQ-F-004 | El test de causalidad confirma que el entrenamiento para la jornada T sólo vio filas con `GW < T` |
| AC-WP004-005 | REQ-Q-003 | La curva de calibración queda publicada como evidencia gráfica o tabular |
| AC-WP004-006 | REQ-F-004 | El modelo queda registrado en `model_versions` con git sha y métricas |

## Verificación

```bash
python -m mova_fpl.models.minutes --train --holdout 2024-25
pytest tests/test_minutes_calibration.py tests/test_minutes_causality.py -v
```

## Evidencia requerida

| Criterio | Tipo | Evidencia esperada |
| --- | --- | --- |
| AC-WP004-001 | test | pytest — las tres probabilidades suman 1.0 en cada fila |
| AC-WP004-002 | reporte | ECE de P(60+) en 10 bins sobre temporada held-out |
| AC-WP004-003 | reporte | Brier del modelo frente al baseline de frecuencia histórica |
| AC-WP004-004 | test | pytest `test_minutes_causality.py` |
| AC-WP004-005 | reporte | Curva de calibración en formato gráfico o tabular |
| AC-WP004-006 | consulta | Fila de `model_versions` con git sha y métricas |

## Rollback

Borrar `mova_fpl/models/minutes.py` y sus artefactos. El harness vuelve a la política stub.

## Definition of Done

- [ ] Todos los criterios requeridos tienen evidencia `pass`.
- [ ] La calibración está reportada, no sólo la precisión.
- [ ] El efecto sobre el resultado del harness quedó medido contra el stub de WP-003.
