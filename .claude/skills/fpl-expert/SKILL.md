---
name: fpl-expert
description: Analizar el brief y el acta de MOVA FPL para proponer XI, C/VC, transferencias y chips con razones, formular Intervention acotadas y alternativas; o modificar reglas, xP, MILP y planificador de chips del motor. No usar para ejecutar clicks en la cuenta web.
metadata:
  vertical: mova
  type: skill
  repo: mova-pro-futbol-data-analytics
  updated: 2026-11-25
---

# FPL Expert

Trabaja sobre el motor causal bajo `mova_fpl/`. El código y las reglas versionadas son la
fuente de verdad; no copies cifras de backtests o supuestos de temporadas anteriores.

Desde ADR-021 el uso principal es **construir la propuesta semanal** que el operador
(`mova-fpl-operator`) presenta a Julián. La propuesta no es una decisión: nada se aplica en
FPL sin su OK explícito.

## Construir la propuesta de la GW

1. Lee `mova week brief --gw N --json`: `squad` (15, FT, banco, chips; fíjate en `source` y
   `fresh`), `flags`, `projections`, `acta`, `strategy_reasons`, `research_signals`,
   `lessons` y `open_decisions`. Una sección `missing` no se rellena con intuición.
2. Si el acta del brief falta o es vieja: `mova week acta --gw N --json` (`--chips` para que
   el planificador evalúe chips). Lee `candidates`, `violations` y el Markdown de
   `acta_path`. El acta es dry-run: no escribe traza.
3. Contrasta con memoria: `mova memory read --gw N --json` (notas `owner_preference`,
   `constraint`, `post_mortem` previas, lecciones validadas, deliberación).
4. Propón, cada punto con razón cuantificada (xP por horizonte, minutos esperados, flags,
   fixtures, precio/banco):
   - XI y formación; banca en orden (GK, 1, 2, 3).
   - Capitán y vice; si el margen C vs VC es < 0.5 xP, dilo y ofrece la alternativa.
   - Transferencias con FT disponibles y hits (múltiplos de 4) solo si el acta los justifica
     en el horizonte; alternativa "rollear FT".
   - Chip: solo como propuesta con su costo de oportunidad; Julián decide si lo usa.
5. Mientras la GW actual no esté `finished + data_checked`, la propuesta es **preliminar**:
   no promuevas chips ni transferencias.
6. Si Julián pide desviarse del acta, explica el costo en xP y registra el porqué como nota
   (`owner_preference` o `decision`); no alteres el motor para que "coincida".

### Intervenciones

El agente solo ajusta entradas tipadas mediante `Intervention` (p. ej. minutos de un jugador
con noticia verificada); nunca fuerza plantilla, XI o capitán. Toda intervención declara
fuente, as-of y caducidad, y se evalúa después con contrafactual pareado.

## Ruta por tipo de cambio de código

- Reglas y scoring: `mova_fpl/rules/` y sus golden tests.
- Datos y causalidad: `mova_fpl/data/`, especialmente `Store.as_of`.
- Minutos y xP: `mova_fpl/models/` y `mova_fpl/engine/projection.py`.
- Scorecards y drift por GW: `mova_fpl/analytics/` y
  `docs/operations/analytics-service.md`.
- Plantilla, transferencias y horizonte: `mova_fpl/optimizer/`.
- Autorización de chips: `mova_fpl/engine/planner.py`.
- Decisión común de vivo/backtest: `mova_fpl/engine/runner.py`.
- Brief y acta del copiloto: `mova_fpl/ops/week_brief.py` (no cambia `decide()`).
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

Esta skill analiza y construye propuestas. Para aplicar en la cuenta una decisión que Julián
aprobó explícitamente, usa `fpl-web-ops`.
