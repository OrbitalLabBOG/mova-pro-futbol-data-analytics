---
name: fpl-expert
description: Analizar o modificar reglas, modelos de puntos esperados, optimización MILP, chips y decisiones deportivas del motor MOVA FPL. No usar para ejecutar clicks en la cuenta web.
metadata:
  vertical: mova
  type: skill
  repo: mova-pro-futbol-data-analytics
  updated: 2026-08-23
---

# FPL Expert

Trabaja sobre el motor causal bajo `mova_fpl/`. El código y las reglas versionadas son la
fuente de verdad; no copies cifras de backtests o supuestos de temporadas anteriores.

## Ruta por tipo de cambio

- Reglas y scoring: `mova_fpl/rules/` y sus golden tests.
- Datos y causalidad: `mova_fpl/data/`, especialmente `Store.as_of`.
- Minutos y xP: `mova_fpl/models/` y `mova_fpl/engine/projection.py`.
- Plantilla, transferencias y horizonte: `mova_fpl/optimizer/`.
- Autorización de chips: `mova_fpl/engine/planner.py`.
- Decisión común de vivo/backtest: `mova_fpl/engine/runner.py`.
- Diseño completo: `docs/architecture/decision-engine.md`.

Lee la referencia concreta antes de cambiar comportamiento; no cargues todas por defecto.

## Invariantes deportivos y estadísticos

1. Todo estado histórico entra por `Store.as_of(season, gw)` y conserva el cutoff.
2. Los puntos se calculan condicionados a ramas de minutos; no proyectes reglas no lineales
   sobre minutos esperados.
3. `E[floor(X/n)]` se calcula desde la distribución, no dividiendo la media.
4. El dinero usa precios de venta y conservación de banco en décimas enteras.
5. El planificador autoriza un chip; el optimizador calcula la mejor ejecución legal.
6. El MILP produce plantilla, XI, banca y C/V. Un agente puede ajustar inputs tipados, pero
   no forzar salidas.
7. Una comparación de totales secuenciales no atribuye causalidad. Evalúa intervenciones de
   agente con contrafactual pareado en sombra.

La existencia de una política o modelo no demuestra que su umbral sea óptimo. Distingue
implementación, calibración y evidencia antes de recomendar una acción.

## Verificación

Ejecuta primero la prueba cercana. Para cambios de arquitectura, además:

```bash
pytest -q
pytest tests/test_architecture_boundaries.py tests/test_store_as_of.py \
  tests/test_agent_contract.py tests/test_optimizer_constraints.py -q
```

Las pruebas marcadas `integration_data` requieren el almacén y modelos locales. Nunca
degrades un test causal para hacerlo pasar sin esos artefactos.

Esta skill analiza y construye decisiones. Para aplicar una decisión aprobada en la cuenta,
usa `fpl-web-ops`, que verifica gates, persistencia y evidencia post-reload.
