---
work_key: WP-INIT-MOVA-FPL-ENGINE-002
title: "Motor de reglas 2025/26 y 2026/27 validado contra 29.757 actuaciones reales"
work_type: workpack
spec_version: 1
spec_status: draft
priority: critical
estimated_hours: 12
parent_key: null
depends_on_keys: [WP-INIT-MOVA-FPL-ENGINE-001]
---

# WP-002 — Motor de reglas versionado por temporada

## Objetivo y resultado

Implementar las reglas de FPL como funciones puras versionadas por temporada, y demostrar
su fidelidad recomputando los puntos de las 29.757 actuaciones reales de 2025/26.

Este es el workpack que convierte "creemos que entendimos las reglas" en un hecho medido.

## Requisitos cubiertos

REQ-F-003, REQ-Q-002

## No objetivos

- No se decide cuándo usar chips (sólo se implementan sus efectos).
- No se recomputa BPS bajo reglas 2026/27 desde eventos Opta (stretch, ver R-02).
- No se accede a datos desde `rules/` — es puro por contrato.

## Precondiciones y dependencias

- WP-001 terminado (se necesita el almacén para el golden test).
- Reglas oficiales 2026/27 confirmadas (H-03).

## Superficie permitida

```
mova_fpl/rules/{__init__,base,season_2025_26,season_2026_27}.py
mova_fpl/rules/{scoring,squad,market,chips,autosubs}.py
tests/test_rules_golden_2025_26.py
tests/test_rules_squad_constraints.py
tests/test_rules_purity.py
```

## Interfaces y comportamiento

```python
score(stats: PlayerStats) -> PointsBreakdown       # desglosado, no sólo el total
validate_squad(squad: Squad) -> list[Violation]    # [] == válido
auto_subs(squad: Squad, minutes: dict) -> Squad
transfer_cost(n_transfers: int, free: int) -> int
```

Diferencias 2026/27 vs 2025/26 que deben quedar codificadas y comentadas con su fuente:
CBI pasa a 1 BPS por cada 3; se elimina "atajada fuera del área"; +1 BPS por atajar big
chance; penalti atajado baja de +8 a +7 BPS. DefCon sin cambios (10 CBIT DEF / 12 CBIRT
MID-FWD, tope +2).

## Criterios de aceptación

| ID | Requisito | Criterio verificable |
| --- | --- | --- |
| AC-WP002-001 | REQ-Q-002 | ≥ 99% de las 29.757 filas de 2025/26 recomputan `total_points` exacto |
| AC-WP002-002 | REQ-Q-002 | Las discrepancias restantes están enumeradas y clasificadas por causa; ninguna queda sin explicación |
| AC-WP002-003 | REQ-F-003 | `validate_squad` rechaza: >3 por club, presupuesto excedido, composición ≠ 2/5/5/3, y formaciones inválidas — un caso de test por regla |
| AC-WP002-004 | REQ-F-003 | `auto_subs` reproduce el orden de prioridad de banca y respeta formación válida en 5 escenarios construidos a mano |
| AC-WP002-005 | REQ-F-003 | `rules_2026_27` difiere de `rules_2025_26` exactamente en los cuatro cambios de BPS documentados; el diff se genera automáticamente |
| AC-WP002-006 | REQ-Q-007 | El test de pureza falla si algún módulo de `rules/` importa `pandas`, `sqlite3` o `mova_fpl.data` |

## Verificación

```bash
pytest tests/test_rules_golden_2025_26.py -v      # 29.757 casos
pytest tests/test_rules_squad_constraints.py tests/test_rules_purity.py -v
python -m mova_fpl.rules.diff --from 2025_26 --to 2026_27
```

## Evidencia requerida

| Criterio | Tipo | Evidencia esperada |
| --- | --- | --- |
| AC-WP002-001 | test | Porcentaje de coincidencia exacta sobre las 29.757 filas |
| AC-WP002-002 | reporte | Tabla de discrepancias clasificadas por causa |
| AC-WP002-003 | test | pytest `test_rules_squad_constraints.py` — un caso por regla |
| AC-WP002-004 | test | pytest — cinco escenarios de sustitución automática |
| AC-WP002-005 | reporte | Diff generado entre `rules_2025_26` y `rules_2026_27` |
| AC-WP002-006 | test | pytest `test_rules_purity.py` |

## Rollback

Borrar `mova_fpl/rules/`. Ningún otro componente depende de él todavía.

## Resultado de ejecución — 2026-08-07

**6/6 criterios en `pass`.** Fidelidad **100,000%**: las 29.747 actuaciones de 2025/26
recomputadas exactas, cero discrepancias (umbral exigido: 99%).

El diff entre versiones aísla exactamente los cuatro cambios oficiales de BPS; la matriz
de puntuación base, los umbrales de DefCon, la plantilla y los chips no cambian. Eso es
lo que hace revisable el riesgo R-02.

Evidencia: [`evidence/WP-002-golden.md`](../evidence/WP-002-golden.md) ·
[`evidence/WP-002-rules-diff.md`](../evidence/WP-002-rules-diff.md)

## Definition of Done

- [ ] Todos los criterios requeridos tienen evidencia `pass`.
- [ ] El % de fidelidad y la tabla de discrepancias están publicados.
- [ ] R-02 revisado por Nicolás: el diff 2025_26 → 2026_27 fue verificado contra la fuente oficial.
