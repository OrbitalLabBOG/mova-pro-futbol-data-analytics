# WP-002 — Golden test de reglas 2025/26

Fecha: 2026-08-07 · Fuente: `merged_gw_2025-26.csv`

| Métrica | Valor |
|---|---|
| Actuaciones evaluadas | 29,747 |
| Coincidencia exacta | **29,747** |
| Discrepancias | **0** |
| Fidelidad | **100.000%** (umbral AC-WP002-001: 99%) |

Cero discrepancias: no hay tabla de causas que documentar (AC-WP002-002).

El motor reproduce `total_points` desde estadísticas crudas en las 29,747 filas.

## Criterios

| Criterio | Resultado | Evidencia |
|---|---|---|
| AC-WP002-001 | **pass** | 100.000% de 29.747 filas |
| AC-WP002-002 | **pass** | Cero discrepancias que clasificar |
| AC-WP002-003 | **pass** | `test_rules_squad_constraints.py` — un caso por regla |
| AC-WP002-004 | **pass** | 6 escenarios de sustitución automática |
| AC-WP002-005 | **pass** | `WP-002-rules-diff.md`: sólo los 4 cambios de BPS |
| AC-WP002-006 | **pass** | `test_rules_purity.py` |
