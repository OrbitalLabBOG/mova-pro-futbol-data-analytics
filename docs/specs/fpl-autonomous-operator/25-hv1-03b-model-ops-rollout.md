---
type: evidence
name: "HV1-03b — Model operations facade"
created: 2026-08-30
updated: 2026-08-30
tags: [mova, fpl, model, mlops, idempotency, observability]
status: deployed-shadow
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
protección contra overwrite. La suite completa también pasó:
`986 passed, 1 skipped, 79 deselected`.

## Rollout VPS

Desplegado en `main` como `d5dc90b3`; checkout, etiqueta de imagen y API quedaron en la misma
revisión. La corrida real produjo:

| Evidencia | Resultado |
| --- | --- |
| Dataset | `dataset_43e053f68d069d76f94bf14b`, 253.890 filas, cutoff 2025/26 GW<39 |
| Candidate | `minutes=1.2.0`, `points=1.2.0` |
| Training job | `job_503283893b9d449dace33fb796508ca6` |
| Training manifest | SHA-256 `0a8c96811eb339049ffbad55071d2442a9dd5c05bbea8f269f4d6523f427a3cf` |
| Candidate manifest | SHA-256 `057bc352346ed45ce9654218cb27eeaac0a8ba5d939f6afccef6ef75416dd34a` |
| Replay | misma clave → `reused`, mismo job |
| Bundle verify | hashes de ambos artifacts y sidecars verificados por el release sealer |
| Runtime activo | permaneció `minutes=1.1.0`, `points=1.1.0`, source `runtime_config` |

`model predict` creó un batch baseline causal de 623 jugadores para GW3
(`projection_c020f971ad894b0e8c181383daf7c55e`) y su variante odds shadow, usando todavía el
bundle activo 1.1.0. El replay devolvió el mismo job
`job_47cd1214932f4d47bcb7fb7371a882c1`.

`model explain` reconstruyó para el elemento 1 versiones, cutoff, artifact, contexto y diez
componentes, sellados con
`content_sha256=b6334f3216fca6b21629ae10b598c07f0bf4b65a0bb39e4523892f44d170ad38`.

`model evaluate` terminó correctamente con cuatro batches en `waiting_for_data_checked` y cero
evaluaciones: GW2/GW3 aún no tenían settlement oficial final. Repetir la clave reutilizó
`job_a84a5b5f144f4bed9af315127aab2ee2`. Este resultado es el guardrail esperado, no un fallo ni
permiso para fabricar scorecards.

El smoke posterior obtuvo 21 checks `PASS`, cero `FAIL` y un único `WARN` deliberado porque se
ejecutó `doctor --no-network`. Ningún control de autonomía, browser ni cuenta FPL cambió.
