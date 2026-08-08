---
work_key: WP-INIT-MOVA-FPL-ENGINE-001
title: "Almacen canonico multi-temporada con contrato as_of y fronteras verificadas"
work_type: workpack
spec_version: 1
spec_status: approved
priority: critical
estimated_hours: 10
parent_key: null
depends_on_keys: []
---

# WP-001 — Almacén canónico y contrato `as_of`

## Objetivo y resultado

Dejar el paquete `mova_fpl/` creado con sus fronteras, y un almacén que consolide las 10
temporadas (2016-17 → 2025-26) accesible **exclusivamente** por `as_of(season, gw)`. Al
terminar, el leakage temporal deja de ser expresable en el código.

## Requisitos cubiertos

REQ-F-001, REQ-F-002, REQ-Q-001, REQ-Q-007, REQ-S-001, REQ-S-002

## No objetivos

- No se entrena ningún modelo.
- No se implementan reglas de puntuación.
- No se derivan acciones defensivas desde eventos Opta (eso es WP-005).

## Precondiciones y dependencias

- Rama `feat/fpl-agent-clean` creada. ✅ hecho el 2026-08-07
- Descarga de los 10 `merged_gw.csv` a `data/raw/fpl_seasons/`. En curso.

## Superficie permitida

```
mova_fpl/__init__.py
mova_fpl/data/{__init__,sources,store,ingest,coverage}.py
tests/test_store_as_of.py
tests/test_architecture_boundaries.py
tests/test_no_secrets.py
tests/test_readonly_http.py
data/raw/fpl_seasons/**          (sólo escritura de descargas)
data/processed/fpl_canonical.db  (nuevo)
```

No se toca: `src/`, `scripts/`, `data/mundial.db`, `data/betting.db`.

## Interfaces y comportamiento

```python
as_of(season: str, gw: int, columns=None) -> DataFrame   # sólo filas con GW < gw
coverage() -> DataFrame                                   # temporada × columna × no-nulos
fixtures(season: str, gw_from: int, gw_to: int) -> DataFrame
```

Columnas ausentes en una temporada quedan `NULL`, nunca `0`. La ingesta es idempotente por
`(season, gw, element, fixture)` y escribe de forma atómica.

> **Señal de cambio (2026-08-07, durante ejecución).** La clave declarada originalmente era
> `(season, gw, element)`. Al ingerir se comprobó que colapsaba las **dobles jornadas**
> —un jugador con dos partidos en la misma gameweek— perdiendo 9.114 observaciones reales
> (H-16). La clave incorpora `fixture`. Adicionalmente se retiró el tope de `gw <= 38`,
> que descartaba 6.004 filas legítimas de la temporada COVID 2019-20 (H-17).

## Criterios de aceptación

| ID | Requisito | Criterio verificable |
| --- | --- | --- |
| AC-WP001-001 | REQ-F-001 | La tabla canónica tiene ≥ 250.000 filas y exactamente 10 temporadas distintas |
| AC-WP001-002 | REQ-F-001 | `coverage()` reproduce el patrón conocido: defensivas presentes sólo en 2016-17..2018-19 y 2025-26; xG sólo desde 2022-23 |
| AC-WP001-003 | REQ-F-002 | `as_of("2025-26", 17)` devuelve `max(GW) == 16`; para cada `gw` en 1..38 se cumple `max(GW) == gw-1` o el resultado es vacío |
| AC-WP001-004 | REQ-Q-001 | La instrumentación falla la corrida cuando un acceso deliberado de prueba lee filas con `GW >= gw` |
| AC-WP001-005 | REQ-F-001 | Re-ejecutar la ingesta dos veces deja el mismo número de filas, y la clave `(season, gw, element, fixture)` es única — preservando las dobles jornadas |
| AC-WP001-006 | REQ-Q-007 | El test de fronteras falla si `rules/` importa de `data/`, o si cualquier módulo importa de `src/mova_*` |
| AC-WP001-007 | REQ-S-001 | El escaneo de patrones de secreto sobre `mova_fpl/` no encuentra coincidencias |
| AC-WP001-008 | REQ-S-002 | El test falla ante cualquier verbo HTTP distinto de `GET` hacia `fantasy.premierleague.com` |

## Verificación

```bash
python -m mova_fpl.data.ingest --all
python -m mova_fpl.data.coverage
pytest tests/test_store_as_of.py tests/test_architecture_boundaries.py \
       tests/test_no_secrets.py tests/test_readonly_http.py -v
```

## Evidencia requerida

| Criterio | Tipo | Evidencia esperada |
| --- | --- | --- |
| AC-WP001-001 | reporte | Salida de `coverage()`: conteo de filas y de temporadas distintas |
| AC-WP001-002 | reporte | Matriz de cobertura por temporada y columna, publicada en el paquete |
| AC-WP001-003 | test | pytest `test_store_as_of.py` — ventana temporal por cada gameweek |
| AC-WP001-004 | test | pytest — la corrida falla ante un acceso deliberado fuera de ventana |
| AC-WP001-005 | test | pytest — doble ingesta produce el mismo conteo de filas |
| AC-WP001-006 | test | pytest `test_architecture_boundaries.py` |
| AC-WP001-007 | test | pytest `test_no_secrets.py` |
| AC-WP001-008 | test | pytest `test_readonly_http.py` |

## Rollback

Borrar `mova_fpl/data/` y `data/processed/fpl_canonical.db`. Nada existente cambia.

## Resultado de ejecución — 2026-08-07

**8/8 criterios en `pass`.** 253.890 filas, 10 temporadas, 93 pruebas verdes.
Evidencia: [`evidence/WP-001-tests.md`](../evidence/WP-001-tests.md) ·
[`evidence/WP-001-coverage.md`](../evidence/WP-001-coverage.md)

Ejecutado bajo autorización de Julián (2026-08-07), aprobador único de la iniciativa.

## Definition of Done

- [ ] Todos los criterios requeridos tienen evidencia `pass`.
- [ ] No existe drift no documentado.
- [ ] La matriz de cobertura queda publicada en el paquete de spec.
