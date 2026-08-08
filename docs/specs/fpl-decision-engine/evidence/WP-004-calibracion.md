# Modelo de minutos v1.0.0 — calibracion

Entrenado con 2016-17, 2017-18, 2018-19, 2019-20, 2020-21, 2021-22, 2022-23, 2023-24, 2024-25 · calibrado en 2024-25 · evaluado a ciegas en 2025-26

| Metrica | Modelo | Baseline (frecuencia del jugador) |
|---|---:|---:|
| ECE de P(60+) | **0.0106** | 0.0416 |
| Brier de P(60+) | **0.0820** | 0.1087 |
| Log-loss 3 clases | 0.4641 | — |

Filas evaluadas: 29,747 · artefacto `models/minutes/minutes-1.0.0.joblib` · git `eada2ce`

## Curva de calibracion — P(60+)

| Bin | n | Predicho | Observado |
|---|---:|---:|---:|
| 0.0-0.1 | 16,491 | 0.013 | 0.017 |
| 0.1-0.2 | 1,718 | 0.151 | 0.132 |
| 0.2-0.3 | 1,313 | 0.244 | 0.192 |
| 0.3-0.4 | 1,061 | 0.352 | 0.351 |
| 0.4-0.5 | 1,149 | 0.448 | 0.426 |
| 0.5-0.6 | 1,057 | 0.549 | 0.521 |
| 0.6-0.7 | 1,265 | 0.651 | 0.641 |
| 0.7-0.8 | 1,761 | 0.754 | 0.773 |
| 0.8-0.9 | 2,861 | 0.850 | 0.865 |
| 0.9-1.0 | 1,071 | 0.941 | 0.935 |

## Efecto en el harness — y el diagnóstico que produjo

El DoD exige medir el efecto contra el stub de WP-003. Medido:

| Régimen | Proyector naive | Proyector minutes | Δ |
|---|---:|---:|---:|
| **Rearmando el equipo libremente cada jornada** *(aísla la proyección)* | 1.907 | **1.935** | **+28** |
| **Política real** (1 transferencia por jornada, horizonte 1) | 1.302 | 1.298 | **−4** |

> El primer régimen **no es una política legal de FPL** — ignora el límite de
> transferencias. Es un diagnóstico: separa la calidad de la proyección de la
> capacidad de la política para explotarla.

**Lectura honesta.** El modelo de minutos es mejor y está bien calibrado (ECE 0,0106
frente a 0,0416 del baseline; Brier 0,0820 frente a 0,1087), pero **el resultado de la
temporada no se mueve**. La razón queda cuantificada:

| Brecha | Puntos | Responsable |
|---|---:|---|
| Política: de 1.935 a 1.302 | **−633** | El greedy de una transferencia por jornada y horizonte 1 → **WP-006** |
| Proyección: 1.935 contra 2.043 del template | **−108** | El xp todavía pierde contra la propiedad de la multitud → **WP-005** |

La brecha de política es **seis veces** la de proyección. Coincide con lo que dice el
estado del arte (arXiv 2505.02170): lo que separa a los optimizadores competentes es el
horizonte rodante, no el solver.

**Consecuencia para la hoja de ruta.** WP-006 deja de ser el workpack de menor prioridad
y pasa a ser el de mayor retorno esperado. Sigue bloqueado por Q-02.

## Criterios

| Criterio | Resultado | Evidencia |
|---|---|---|
| AC-WP004-001 | **pass** | `test_tres_probabilidades_que_suman_uno` |
| AC-WP004-002 | **pass** | ECE 0,0106 ≤ 0,05 |
| AC-WP004-003 | **pass** | Brier 0,0820 < 0,1087 del baseline |
| AC-WP004-004 | **pass** | `test_minutes_causality.py` — 6 pruebas |
| AC-WP004-005 | **pass** | Curva de calibración arriba |
| AC-WP004-006 | **pass** | `model_versions`: minutes 1.0.0, git sha, 196.538 filas |
