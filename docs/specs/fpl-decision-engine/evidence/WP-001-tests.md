# WP-001 — Evidencia de ejecución

Fecha: 2026-08-07 · Rama: feat/fpl-agent-clean

## Suite de pruebas

```
tests/test_store_as_of.py::test_multi_season_respeta_ventana
  /home/jzuluaga/code/orbital-lab/mova-pro-futbol-data-analytics/mova_fpl/data/store.py:117: FutureWarning: The behavior of DataFrame concatenation with empty or all-NA entries is deprecated. In a future version, this will no longer exclude empty or all-NA columns when determining the result dtypes. To retain the old behavior, exclude the relevant entries before the concat operation.
    out = frames[0] if len(frames) == 1 else pd.concat(frames, ignore_index=True)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
93 passed, 1 skipped, 1 warning in 12.71s
```

## Ingesta

```
Ingesta de 10 temporadas -> /home/jzuluaga/code/orbital-lab/mova-pro-futbol-data-analytics/data/processed/fpl_canonical.db
  2016-17: 23,679 filas
  2017-18: 22,467 filas
  2018-19: 21,790 filas
  2019-20: 22,560 filas
  2020-21: 24,365 filas
  2021-22: 25,447 filas
  2022-23: 26,505 filas
  2023-24: 29,725 filas
  2024-25: 27,605 filas
      (2025-26: 10 filas duplicadas exactas descartadas)
  2025-26: 29,747 filas

Total: 253,890 filas en 10 temporadas
```

## Criterios

| Criterio | Resultado | Evidencia |
|---|---|---|
| AC-WP001-001 | **pass** | 253.890 filas, 10 temporadas |
| AC-WP001-002 | **pass** | `WP-001-coverage.md` + `test_cobertura_reproduce_patron_conocido` |
| AC-WP001-003 | **pass** | 38 casos parametrizados, uno por gameweek |
| AC-WP001-004 | **pass** | `test_instrumentacion_*` + `test_sql_y_verificacion_son_independientes` |
| AC-WP001-005 | **pass** | `test_ingesta_es_idempotente`, `test_clave_primaria_unica` |
| AC-WP001-006 | **pass** | `test_architecture_boundaries.py` |
| AC-WP001-007 | **pass** | `test_no_secrets.py` |
| AC-WP001-008 | **pass** | `test_readonly_http.py` |
