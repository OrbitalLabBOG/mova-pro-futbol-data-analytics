---
title: Benchmark interno MOVA — evidencia histórica
status: experimental
owner: MOVA Fantasy
---

# Progreso analítico registrado

Generado desde `registry.json` y evidencia local; no es una nueva corrida.

**No hay ranking global.** Cada bloque conserva su control y protocolo.

Catálogo: 23 directorios; grupos pareados: 11.

PVA-38 = puntos netos del candidato menos puntos netos de su control.
Los puestos son descriptivos: no prueban significancia ni autorizan promoción.

## exp003-development-v1

Estado season-only; políticas sin chips. Ablación de horizonte, calendario y proxies.

Fase: `development`. Temporadas: 2021-22, 2023-24, 2024-25.

| Variante | PVA-38 por temporada (orden anterior) | Media | Gana/pierde | IC95 registrado |
| --- | --- | ---: | --- | --- |
| season_fixture_h3 | +33 / +72 / -21 | +28.00 | 2/1 | [-95.0, +155.0] |
| season_fixture_h6_events_stable | +24 / +110 / -88 | +15.33 | 2/1 | [-144.0, +188.0] |
| season_fixture_h6_events | -47 / +132 / -42 | +14.33 | 1/2 | [-129.0, +167.0] |
| season_fixture_h6 | -36 / +34 / -177 | -59.67 | 1/2 | [-198.0, +85.0] |

Evidencia: `EXP-MOVA-2026-003/policy-selection.json`, `EXP-MOVA-2026-003/manifest.json`.

## exp003-historical_holdout-v1

Holdout registrado en su momento; hoy ya consultado. No reutilizar como holdout intacto.

Fase: `historical_holdout`. Temporadas: 2025-26.

| Variante | PVA-38 por temporada (orden anterior) | Media | Gana/pierde | IC95 registrado |
| --- | --- | ---: | --- | --- |
| season_fixture_h3 | +165 | +165.00 | 1/0 | no importado |

Evidencia: `EXP-MOVA-2026-003/holdout-result.json`, `EXP-MOVA-2026-003/manifest.json`.

## exp004-development-v1

Proxies de eventos aislados sobre h3. El control es fixture_h3, no control_h3.

Fase: `development`. Temporadas: 2021-22, 2023-24, 2024-25.

| Variante | PVA-38 por temporada (orden anterior) | Media | Gana/pierde | IC95 registrado |
| --- | --- | ---: | --- | --- |
| season_fixture_h3_events | +7 / +52 / -132 | -24.33 | 2/1 | [-154.0, +96.0] |
| control_h3 | -33 / -72 / +21 | -28.00 | 1/2 | no importado |

Evidencia: `EXP-MOVA-2026-004/policy-selection.json`, `EXP-MOVA-2026-004/manifest.json`.

## exp009-development-v1

Recourse estocástico: conservar el resultado nulo.

Fase: `development`. Temporadas: 2021-22, 2023-24, 2024-25.

| Variante | PVA-38 por temporada (orden anterior) | Media | Gana/pierde | IC95 registrado |
| --- | --- | ---: | --- | --- |
| stochastic-recourse-h3 | +0 / +0 / +0 | +0.00 | 0/0 | [+0.0, +0.0] |

Evidencia: `EXP-MOVA-2026-009/selection.json`, `EXP-MOVA-2026-009/manifest.json`.

## exp012-development-v1

Valor terminal de FT; cuatro temporadas, política sin chips.

Fase: `development`. Temporadas: 2020-21, 2021-22, 2023-24, 2024-25.

| Variante | PVA-38 por temporada (orden anterior) | Media | Gana/pierde | IC95 registrado |
| --- | --- | ---: | --- | --- |
| season_fixture_h3_terminal_ft_v1 | -144 / +3 / +4 / -129 | -66.50 | 2/2 | [-190.0, +44.0] |

Evidencia: `EXP-MOVA-2026-012/selection.json`, `EXP-MOVA-2026-012/manifest.json`.

## exp013-development-v1

Estado previo congelado frente a incorporación causal de historia actual.

Fase: `development`. Temporadas: 2021-22, 2023-24, 2024-25.

| Variante | PVA-38 por temporada (orden anterior) | Media | Gana/pierde | IC95 registrado |
| --- | --- | ---: | --- | --- |
| append_full | +406 / +553 / +166 | +375.00 | 3/0 | [+128.0, +613.0] |

Evidencia: `EXP-MOVA-2026-013/decision-development.json`, `EXP-MOVA-2026-013/manifest.json`.

## exp013-external_diagnostic-v1

Estado previo congelado frente a incorporación causal de historia actual. Temporada externa ya consultada.

Fase: `external_diagnostic`. Temporadas: 2025-26.

| Variante | PVA-38 por temporada (orden anterior) | Media | Gana/pierde | IC95 registrado |
| --- | --- | ---: | --- | --- |
| append_full | +694 | +694.00 | 1/0 | [+374.0, +1032.0] |

Evidencia: `EXP-MOVA-2026-013/external-evaluation.json`, `EXP-MOVA-2026-013/manifest.json`.

## exp017-development-v1

Ensemble continuidad/reinicio; distinto control al EXP003.

Fase: `development`. Temporadas: 2021-22, 2023-24, 2024-25.

| Variante | PVA-38 por temporada (orden anterior) | Media | Gana/pierde | IC95 registrado |
| --- | --- | ---: | --- | --- |
| blend_0.50 | +148 / -111 / +82 | +39.67 | 2/1 | [-138.0, +169.0] |

Evidencia: `EXP-MOVA-2026-017/decision-development.json`, `EXP-MOVA-2026-017/manifest.json`.

## exp017-external_diagnostic-v1

Ensemble continuidad/reinicio; distinto control al EXP003. Temporada externa ya consultada.

Fase: `external_diagnostic`. Temporadas: 2025-26.

| Variante | PVA-38 por temporada (orden anterior) | Media | Gana/pierde | IC95 registrado |
| --- | --- | ---: | --- | --- |
| blend_0.50 | +29 | +29.00 | 1/0 | [-133.0, +238.0] |

Evidencia: `EXP-MOVA-2026-017/external-evaluation.json`, `EXP-MOVA-2026-017/manifest.json`.

## exp021-development-v1

Participación reciente; estado append_full, h3, top20, CBC 3s, sin chips históricos.

Fase: `development`. Temporadas: 2021-22, 2023-24, 2024-25.

| Variante | PVA-38 por temporada (orden anterior) | Media | Gana/pierde | IC95 registrado |
| --- | --- | ---: | --- | --- |
| participation | -79 / -44 / -77 | -66.67 | 0/3 | [-220.0, +83.0] |

Evidencia: `EXP-MOVA-2026-021/2021-22-baseline-replay.json`, `EXP-MOVA-2026-021/2021-22-participation-replay.json`, `EXP-MOVA-2026-021/2023-24-baseline-replay.json`, `EXP-MOVA-2026-021/2023-24-participation-replay.json`, `EXP-MOVA-2026-021/2024-25-baseline-replay.json`, `EXP-MOVA-2026-021/2024-25-participation-replay.json`, `EXP-MOVA-2026-021/manifest.json`, `EXP-MOVA-2026-021/paired-evaluation.json`.

## exp021-external_diagnostic-v1

Valor conjunto de chips y participación; catálogo habilitado, h3, top20, CBC 3s. No comparable con EXP003.

Fase: `external_diagnostic`. Temporadas: 2025-26.

| Variante | PVA-38 por temporada (orden anterior) | Media | Gana/pierde | IC95 registrado |
| --- | --- | ---: | --- | --- |
| season_value | +156 | +156.00 | 1/0 | [+24.0, +263.0] |
| combined | +66 | +66.00 | 1/0 | [-139.0, +264.0] |
| runtime_matrix | +2 | +2.00 | 1/0 | no importado |

Evidencia: `EXP-MOVA-2026-021/2025-26-baseline-replay.json`, `EXP-MOVA-2026-021/2025-26-runtime_matrix-replay.json`, `EXP-MOVA-2026-021/2025-26-season_value-replay.json`, `EXP-MOVA-2026-021/2025-26-combined-replay.json`, `EXP-MOVA-2026-021/manifest.json`, `EXP-MOVA-2026-021/paired-evaluation.json`.

## Métricas predictivas (separadas de utilidad de política)

Cada panel conserva su población. No comparar niveles entre paneles ni inferir mejora de puntos.

### exp005-external

2025-26; misma población reportada de puntos jugador-GW. Menor CRPS/log-score/Brier es mejor; cobertura se compara con el nominal, no se maximiza.

| Variante | rows | crps_discrete | log_score | zero_brier | coverage_80 |
| --- | ---: | ---: | ---: | ---: | ---: |
| empirical_discrete | 29338 | 0.645038 | 1.08535 | 0.0950157 | 0.937658 |
| discretized_normal | 29338 | 0.711185 | 1.41107 | 0.155315 | 0.937317 |

Evidencia: `EXP-MOVA-2026-005/external-evaluation.json`.

### exp015-external

2025-26; participación al comienzo de temporada, población definida por el experimento. No equivale a toda la temporada de EXP021.

| Variante | n | log_loss_3c | brier_p60 | ece_p60 |
| --- | ---: | ---: | ---: | ---: |
| base | 4423 | 0.492202 | 0.083644 | 0.0170211 |
| prior_shift_0.5gw | 4423 | 0.491934 | 0.0836739 | 0.0167593 |

Evidencia: `EXP-MOVA-2026-015/external-evaluation.json`.

### exp017-external

2025-26; participación al comienzo de temporada, población definida por el experimento. No equivale a toda la temporada de EXP021.

| Variante | n | log_loss_3c | brier_p60 | ece_p60 |
| --- | ---: | ---: | ---: | ---: |
| blend_0.50 | 5128 | 0.493351 | 0.0825208 | 0.0154061 |
| control_full | 5128 | 0.496894 | 0.0830186 | 0.017503 |

Evidencia: `EXP-MOVA-2026-017/external-evaluation.json`.

### exp021-2021-22

2021-22; participación, excluye etiquetas DGW agregadas. Menor es mejor; métricas de calibración no sustituyen PVA.

| Variante | n | log_loss_3c | brier_p60 | ece_p60 |
| --- | ---: | ---: | ---: | ---: |
| baseline | 21013 | 0.540763 | 0.103463 | 0.00397608 |
| ensemble50 | 21013 | 0.537829 | 0.103087 | 0.00649413 |
| participation | 21013 | 0.543328 | 0.103277 | 0.00462882 |

Evidencia: `EXP-MOVA-2026-021/2021-22-predictive.json`.

### exp021-2023-24

2023-24; participación, excluye etiquetas DGW agregadas. Menor es mejor; métricas de calibración no sustituyen PVA.

| Variante | n | log_loss_3c | brier_p60 | ece_p60 |
| --- | ---: | ---: | ---: | ---: |
| baseline | 27759 | 0.481764 | 0.0818519 | 0.00842761 |
| ensemble50 | 27759 | 0.476676 | 0.0812359 | 0.00760892 |
| participation | 27759 | 0.478987 | 0.0816496 | 0.00743188 |

Evidencia: `EXP-MOVA-2026-021/2023-24-predictive.json`.

### exp021-2024-25

2024-25; participación, excluye etiquetas DGW agregadas. Menor es mejor; métricas de calibración no sustituyen PVA.

| Variante | n | log_loss_3c | brier_p60 | ece_p60 |
| --- | ---: | ---: | ---: | ---: |
| baseline | 26555 | 0.518454 | 0.09207 | 0.0102012 |
| ensemble50 | 26555 | 0.515622 | 0.0919455 | 0.0120212 |
| participation | 26555 | 0.514571 | 0.0916272 | 0.00935451 |

Evidencia: `EXP-MOVA-2026-021/2024-25-predictive.json`.

### exp021-2025-26

2025-26; participación, excluye etiquetas DGW agregadas. Menor es mejor; métricas de calibración no sustituyen PVA.

| Variante | n | log_loss_3c | brier_p60 | ece_p60 |
| --- | ---: | ---: | ---: | ---: |
| baseline | 28929 | 0.464066 | 0.0817584 | 0.0105772 |
| ensemble50 | 28929 | 0.460223 | 0.0813783 | 0.0106895 |
| participation | 28929 | 0.461269 | 0.0815509 | 0.0112376 |

Evidencia: `EXP-MOVA-2026-021/2025-26-predictive.json`.

## Límites

- Los grupos son comparaciones históricas separadas, no un ranking global ni una nueva evaluación científica.
- El catálogo inventaría metadata JSON de primer nivel; no certifica todos los binarios, predicciones ni trazas externos. Sus hashes declarados no equivalen a verificar sus bytes.
- Los resultados agregados anteriores se importan como evidencia reportada; sólo el adaptador replay comprueba GW1..38 y suma de puntos netos. No se reejecutaron temporadas en esta consolidación.
- Los IC95 se importan de bootstrap pareado sólo cuando las temporadas y deltas coinciden; no incorporan toda la selección de modelos ni convierten 2025-26 en holdout intacto.
- No se mezclan xP vivos con puntos realizados, ni métricas predictivas con PVA-38. Los experimentos predictivos/vivos siguen catalogados aunque no tengan fila de política.
- Los calendarios históricos conservan asignaciones finales de aplazamientos; los catálogos históricos de chips son incompletos. Falta comparabilidad multitemporada completa.
- Una reproducción o fallo tiene su propio directorio; nunca cuenta como temporada independiente. No se infiere éxito o promoción de la presencia de un archivo.
- El benchmark no cambia modelos activos ni autoridad del harness. MLflow no se incorpora en esta fase.

## Catálogo (sin inferir que una carpeta equivale a un experimento terminado)

| Directorio | JSON de primer nivel | Grupos pareados |
| --- | ---: | ---: |
| EXP-MOVA-2026-001 | 3 | 0 |
| EXP-MOVA-2026-002 | 2 | 0 |
| EXP-MOVA-2026-003 | 4 | 2 |
| EXP-MOVA-2026-003-repro | 1 | 0 |
| EXP-MOVA-2026-004 | 2 | 1 |
| EXP-MOVA-2026-005 | 3 | 0 |
| EXP-MOVA-2026-006 | 2 | 0 |
| EXP-MOVA-2026-007 | 3 | 0 |
| EXP-MOVA-2026-008 | 4 | 0 |
| EXP-MOVA-2026-009 | 2 | 1 |
| EXP-MOVA-2026-010 | 0 | 0 |
| EXP-MOVA-2026-011 | 1 | 0 |
| EXP-MOVA-2026-012 | 2 | 1 |
| EXP-MOVA-2026-013 | 4 | 2 |
| EXP-MOVA-2026-014 | 3 | 0 |
| EXP-MOVA-2026-015 | 3 | 0 |
| EXP-MOVA-2026-016 | 1 | 0 |
| EXP-MOVA-2026-017 | 4 | 2 |
| EXP-MOVA-2026-018 | 2 | 0 |
| EXP-MOVA-2026-019 | 1 | 0 |
| EXP-MOVA-2026-020 | 2 | 0 |
| EXP-MOVA-2026-021 | 18 | 2 |
| EXP-MOVA-2026-021-preflight-failed | 1 | 0 |
