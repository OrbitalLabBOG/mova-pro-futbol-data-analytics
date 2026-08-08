---
work_key: WP-INIT-MOVA-FPL-ENGINE-006
title: "Optimizador MILP con horizonte rodante multi-gameweek"
work_type: workpack
spec_version: 1
spec_status: approved
priority: high
estimated_hours: 12
parent_key: null
depends_on_keys: [WP-INIT-MOVA-FPL-ENGINE-002, WP-INIT-MOVA-FPL-ENGINE-005]
---

# WP-006 — Optimizador con horizonte multi-gameweek

## Objetivo y resultado

Seleccionar plantilla de 15, XI, capitán y vicecapitán maximizando xP sobre un horizonte de
N jornadas (N ≥ 3), respetando todas las restricciones del motor de reglas. Según el estado
del arte, el horizonte rodante —no el solver— es lo que separa a los optimizadores
competentes de los ingenuos.

## Requisitos cubiertos

REQ-F-006

## No objetivos

- No se optimiza la política de chips: v1 usa heurística simple (Q-04).
- No se modela el precio futuro de los jugadores ni la especulación de valor.

## Precondiciones y dependencias

- WP-002 (restricciones) y WP-005 (proyecciones) terminados.
- **BLOQUEO Q-02:** la función objetivo depende de si el objetivo es rank global o
  mini-liga. Por defecto se asume maximizar puntos esperados. Requiere decisión de Julián
  antes de cerrar este workpack.

## Superficie permitida

```
mova_fpl/optimizer/{__init__,milp,horizon,heuristics}.py
tests/test_optimizer_constraints.py
tests/test_optimizer_horizon.py
```

## Interfaces y comportamiento

```python
def solve(state: SquadState, projections: DataFrame,
          horizon: int, rules: RulesModule) -> Decision
```

Formulación como programa lineal entero mixto con PuLP: variables binarias de plantilla,
titularidad y capitanía; restricciones de presupuesto, composición 2/5/5/3, máximo 3 por
club, formación válida, y costo de transferencias por encima de las libres acumuladas.

**Importante:** el candidato no se pre-filtra por xP antes de resolver salvo que se
documente el criterio y su efecto. El legacy filtraba a top-20 por posición, lo que rompe
la garantía de optimalidad sin decirlo.

Si el problema resulta infactible, falla ruidosamente listando las restricciones violadas.
Nunca relaja una restricción en silencio.

## Criterios de aceptación

| ID | Requisito | Criterio verificable |
| --- | --- | --- |
| AC-WP006-001 | REQ-F-006 | La solución nunca viola `rules.validate_squad`, verificado sobre las 38 jornadas de un `replay()` completo |
| AC-WP006-002 | REQ-F-006 | Con horizonte 3, el xP acumulado sobre esas 3 jornadas es ≥ al de la solución con horizonte 1 evaluada sobre el mismo tramo |
| AC-WP006-003 | REQ-F-006 | El optimizador respeta el banco de dinero y el precio de venta, no un presupuesto fijo de £100M por jornada |
| AC-WP006-004 | REQ-F-006 | Las transferencias libres se acumulan hasta el máximo vigente y el costo de hits se descuenta correctamente |
| AC-WP006-005 | REQ-F-006 | Un problema infactible produce error explícito con la lista de restricciones violadas |
| AC-WP006-006 | REQ-F-006 | Si se usa pre-filtro de candidatos, su criterio y su efecto sobre la optimalidad están documentados y medidos |
| AC-WP006-007 | REQ-Q-004 | Enchufado al harness, mejora el resultado frente a WP-005 con horizonte 1 |

## Verificación

```bash
pytest tests/test_optimizer_constraints.py tests/test_optimizer_horizon.py -v
python -m mova_fpl.cli.backtest --season 2025-26 --horizon 1 --seed 42
python -m mova_fpl.cli.backtest --season 2025-26 --horizon 3 --seed 42
```

## Evidencia requerida

| Criterio | Tipo | Evidencia esperada |
| --- | --- | --- |
| AC-WP006-001 | test | pytest `test_optimizer_constraints.py` sobre 38 jornadas |
| AC-WP006-002 | reporte | Comparación de xP acumulado: horizonte 1 frente a horizonte 3 |
| AC-WP006-003 | test | pytest — banco de dinero y precio de venta respetados |
| AC-WP006-004 | test | pytest — acumulación de transferencias libres y costo de hits |
| AC-WP006-005 | test | pytest — error explícito con restricciones violadas |
| AC-WP006-006 | reporte | Documento del criterio de pre-filtro y su efecto medido |
| AC-WP006-007 | reporte | `RunReport` comparado contra el resultado de WP-005 |

## Rollback

Borrar `mova_fpl/optimizer/`. `decide()` cae a la heurística de WP-003, que ya está probada
y sirve para operar GW1 si hace falta (corte de R-01).

## Definition of Done

- [ ] Todos los criterios requeridos tienen evidencia `pass`.
- [ ] Q-02 respondida por Julián y la función objetivo documentada.
- [ ] La ganancia del horizonte multi-GW está medida, no supuesta.
