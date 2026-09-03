---
title: Protocolo de experimentación y promoción del motor FPL
status: experimental
owner: MOVA Fantasy
updated: 2026-09-03
---

# Protocolo de experimentación del motor FPL

El registro de modelos existente sigue siendo la fuente de artefactos de
producción. No se añade MLflow remoto en esta etapa: el harness ya sella SHA de
Git, SHA del dataset, configuración, fold temporal, trazas y resultados. MLflow
local con SQLite solo se evaluará si el volumen de corridas vuelve insuficiente
la consulta de los JSON/CSV versionados.

## Unidad de evidencia

Una iteración válida tiene:

1. identificador inmutable;
2. una variable primaria frente al control;
3. dataset y código identificados por SHA-256/SHA;
4. temporadas de selección separadas del holdout;
5. métricas predictivas y métricas de política;
6. limitaciones y resultado `iterate`, `discard`, `hold` o `promote`;
7. autorización humana antes de mover cualquier artefacto activo.

## Gate de candidato

Un modelo no avanza por bajar MAE solamente. Debe mostrar simultáneamente:

- `PVA-38` positivo en promedio frente al control causal;
- mejora en más de una temporada de desarrollo;
- intervalo y downside del bootstrap reportados, aunque no sean concluyentes;
- CRPS y calibración sin degradación material;
- ausencia de fuga temporal y uso exclusivo de estado predeadline;
- replay completo con presupuesto, venta, transferencias, hits, banca y capitán;
- holdout abierto una sola vez después de congelar hiperparámetros.

Si el holdout falla, se inicia otro experimento con un nuevo identificador; no
se ajusta el mismo candidato mirando el resultado sellado.

## Promoción

`prepared` y `shadow` no cambian producción. La promoción necesita:

1. socialización de resultados con Julián;
2. aprobación explícita;
3. revisión técnica de Buitra si cambia arquitectura;
4. bundle y rollback verificables;
5. shadow en la jornada viva antes de tráfico operativo.

Hasta entonces el runtime sigue en lectura/sombra y la operación manual conserva
la última palabra.

## Sombra viva de `season_fixture_h3`

El candidato offline de `EXP-MOVA-2026-003` tiene un adaptador opt-in en el
runtime. `MOVA_ENABLE_LONG_HORIZON_SHADOW=1` añade al artefacto de candidatos un
par control/candidato con estas garantías:

- el `selected_candidate_key` continúa siendo `milp_baseline`;
- ambos brazos usan el mismo snapshot, bundle de modelos, plantilla, banco,
  transferencias libres y política sin chips;
- el control repite el xP del rival inmediato y el candidato proyecta rival y
  localía fixture-a-fixture durante tres GW;
- `selected_for_execution=false` queda sellado en el envelope;
- las matrices completas de xP y desviación estándar quedan en el JSON para su
  liquidación posterior.

El flag permanece en `0` por defecto y no es una promoción. Para superar el gate
se requieren tres deadlines consecutivos, revisión contra la decisión manual y
una nueva autorización explícita.
