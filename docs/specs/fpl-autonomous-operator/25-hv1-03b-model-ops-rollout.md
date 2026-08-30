---
type: evidence
name: "HV1-03b — Model operations facade"
created: 2026-08-30
updated: 2026-08-30
tags: [mova, fpl, model, mlops, idempotency, observability]
status: implementation-verified
---

# Evidencia HV1-03b — Model operations facade

## Resultado

El harness expone `mova model status|train|predict|explain|evaluate` como contrato estable.
Las cuatro operaciones ya no dependen de conocer CLIs internos ni de interpretar artifacts a
mano. Predicción y evaluación conservan los jobs analíticos existentes; explicación devuelve
la proyección sellada con procedencia; entrenamiento produce un bundle candidato inmutable.

## Guardrails

- `train`, `predict` y `evaluate` exigen actor, razón y clave idempotente.
- La identidad de training incluye contrato, versión, holdout y hash de la base canónica.
- Reusar una clave con otra identidad falla; repetir la misma identidad retorna el job previo.
- Los artifacts de versión no se sobrescriben y usan temporales + rename atómico.
- Un fallo limpia artifacts candidatos parciales y persiste `error_code`/detalle en el job.
- El manifest de training declara `runtime_mutated=false` y el siguiente gate exacto.
- Sólo `mova improve release prepare/shadow/promote` puede activar un bundle.
- `explain` es read-only y sella su `content_sha256` sobre versiones, cutoff, artifact, sujeto,
  componentes y contexto.

## Verificación de implementación

```text
pytest -q tests/test_model_service.py tests/test_model_analytics.py tests/test_gameweek_review.py
24 passed

python -m compileall -q mova_fpl
PASS
```

Las pruebas cubren parser tipado, separación de jobs, procedencia de explicación, candidato sin
promoción, replay idempotente, rechazo de alias con input distinto, limpieza ante fallo y
protección contra overwrite. La suite completa, smoke del VPS y una corrida candidata real se
registran en la sección de rollout antes de cerrar el acta.

## Rollout VPS

Pendiente de completar en esta misma iteración. Hasta entonces la implementación está verificada
localmente, pero el task PM no debe considerarse desplegado.
