---
title: "EXP-MOVA-2026-022 — estados de oportunidad y promoción del planner"
status: experimental
updated: 2026-09-05
owner: MOVA Fantasy
---

# Hipótesis y métrica a vencer

Objetivo: maximizar puntos netos esperados de GW actual a GW38. El objetivo de
probabilidad de ganar una liga exige un modelo de rivales y una función de utilidad
separados; no se intercambia silenciosamente con puntos esperados.

El control estratégico es `season_value` 1.0.0 con predictores congelados del fold,
`append_full`, fixture h3, decay 0,84, top20, CBC 3 s y seed 42. Su resultado registrado
en EXP021 es 2.212 puntos en 2025/26; EXP022 vuelve a ejecutar ese control. La cifra
2.212 no es un umbral universal: la métrica es **PVA-38 = netos candidato − netos
control del mismo protocolo**. Si el control reproducido cambia, se declara ese drift.

EXP022 prueba si las oportunidades conjuntas normalizadas de BB/FH/TC/WC tienen
persistencia temporal explotable. Estima tres regímenes con KMeans (seed 42,
n_init 10), escala aprendida sólo con datos anteriores y cinco pseudotransiciones
por fila hacia la distribución marginal. Conserva vectores conjuntos de los cuatro
poderes. Bellman añade el régimen al tiempo e inventario; no conoce resultados futuros.
Los hiperparámetros se congelan antes de abrir la evaluación, sin búsqueda posterior.

## Datos, entrenamiento y prueba del mecanismo

Hay 74 observaciones de oportunidades: 37 en 2023/24 y 37 en 2024/25. Son deltas
contrafactuales del objetivo del solver antes del deadline sobre dos trayectorias
del control, con inventario hipotético. No son ganancias realizadas de poderes.

El mecanismo se ajusta con 2023/24 y evalúa 36 transiciones consecutivas en 2024/25.
No se crean transiciones entre temporadas ni a través de GWs ausentes. Se comparan
energy score multivariado y error cuadrático de la media, escalados exclusivamente
con desviaciones de entrenamiento (piso 1). Menor es mejor. Deben mejorar ambos
antes de gastar el presupuesto de replay. El evaluador conserva todos los scores,
rechaza duplicados y datos futuros y verifica hashes de fuente y entradas.

Resultado: energy score estacionario 1,061726 vs Markov 1,024411; MSE estandarizado
0,689251 vs 0,643928. La prueba exploratoria del mecanismo pasa. No es evidencia
estadística multitemporada ni utilidad FPL; 2024/25 ya había sido consultada antes.

Para el replay 2025/26 se ajustan transiciones con ambas temporadas anteriores.
Se comparan control y candidato desde GW1, mismos predictores y misma maquinaria
`replay → decide → MILP → score_decision`. Cada brazo arrastra su plantilla,
banco, transferencias y poderes. Se conserva la liquidación oficial, hits y
reversión de Free Hit. El estado de continuación es una aproximación de oportunidades,
no una simulación completa de los jugadores ni del efecto causal de Wildcard.

## Contrato de entradas y salidas

| Capa vigente | Entrada | Salida / límite |
| --- | --- | --- |
| Predictor de minutos | Historia causal y roster | Probabilidades de 0 / 1–59 / 60+; no es una alineación cierta |
| Predictor de puntos | Ramas de minutos, tasas y reglas | xP, dispersión y diez componentes; fixture projection produce matriz por GW |
| Planner | State, matriz, inventario y reglas | ChipVerdict: autorización de un chip, valor inmediato, umbral y evidencia |
| MILP y decide | Estado y autorización | Decision: plantilla, XI, banca, C/VC, transfers, hits, banco, xP y fingerprint |
| Harness | Manifest, Decision y evidencias | Envelope validado, autoridad, ejecución/verificación, settlement y review |

EXP022 conserva `ChipVerdict`; añade q_values por acción, valor de esperar, régimen,
dimensiones observadas y cantidad de estados Bellman en su evidencia. No registra
una política productiva, cambia el puntero de modelos ni habilita browser.
Si un chip gastado carece de valor actual, se estima el régimen con las dimensiones
observadas; no se interpreta la ausencia como una oportunidad nula.

## Diseño del sistema siguiente

La arquitectura objetivo es un control predictivo estocástico con estado de creencias:

1. Estado observado: plantilla, precios de compra/venta, banco, FT, poderes/ventanas,
   calendario conocido y datos sellados. La transición de dinero y reglas es exacta.
2. Estado incierto: participación, rol, forma y calendario aún no confirmado. Sus
   distribuciones se actualizan sólo con información publicada y resultados cerrados.
3. Escenarios conjuntos: dependencia por jugador, equipo, partido y descanso. No
   tratar las dos apariciones de una DGW ni compañeros de club como independientes.
4. Decisión: optimización rodante con acciones comunes entre futuros que aún no
   pueden distinguirse; valor de continuación hasta GW38 condicionado al estado.
   Wildcard cambia plantilla futura; Free Hit restaura el estado previo; BB valora
   banca y TC el capitán. Cada interacción requiere atribución y ablación propia.
5. Aprendizaje: revisión causal → hipótesis registrada → challenger → benchmark →
   shadow prospectivo → gate → versión/rollback. Una derrota no modifica parámetros
   hasta dar por cerrado su experimento y reservar otro protocolo.

EXP022 implementa sólo el primer ensayo de persistencia de oportunidades. Sus
transiciones son independientes de la acción y estimadas bajo una política fija;
no identifica qué ocurre a la siguiente plantilla al usar Wildcard. Ese límite
impide venderlo como un world model completo o como solución óptima global.

## Gate propuesto para una futura promoción estratégica

| Etapa | Evidencia mínima propuesta |
| --- | --- |
| Contrato | Versiones/hashes de predictores, planner, datos, reglas y solver; trazas reproducibles; acciones legales |
| Desarrollo | Al menos tres temporadas con reglas/chips representados fielmente; PVA medio positivo y victorias en ≥2/3; sin seleccionar sobre el test |
| Robustez | IC pareado, influencia de cada temporada/GW, escenarios de calendario y presupuesto, sin ocultar variantes fallidas |
| Prospectiva | Al menos tres GWs finales pareadas con manifests sellados antes del deadline; continuar si incertidumbre impide conclusión |
| Utilidad | PVA frente al control y calidad de distribuciones; no sustituir puntos por MAE/Brier ni extrapolar tres GWs a temporada |
| Operación | Latencia acotada, fallback legal, rollback, hashes y único decide; controles de autonomía independientes |

Esto es una propuesta experimental, no una modificación del gate activo. El gate
actual `improve release` admite sólo `minutes+points` y compara MAE/ECE en ≥3 GWs;
no debe reutilizarse para promover un planner por una métrica que no mide. Hace
falta un contrato de bundle estratégico con versiones del planner y proyector,
protocolo de utilidad, evidencia prospectiva y rollback propio. MLflow archiva
el experimento; no concede autoridad.

Faltan calendarios históricos con fecha de publicación y soporte completo de chips
para varias temporadas. Los históricos cerrados sí sirven para diagnóstico; las
simulaciones con reglas homogéneas deben llevar etiqueta contrafactual separada.
No se completan estos requisitos replicando una temporada con muchas semillas.

## Reproducir

El directorio externo `../mova-fpl-experiments/EXP-MOVA-2026-022` conserva manifest,
protocolo previo al replay, scores, trazas y resultados. Los originales de EXP021
se leen sin modificarlos. Ejecutar con Python 3.13 del proyecto:

```bash
python -m experiments.season_value.transition_run \
  --parent ../mova-fpl-experiments/EXP-MOVA-2026-021 \
  --output ../mova-fpl-experiments/EXP-MOVA-2026-022
python -m experiments.season_value.transition_replay \
  --parent ../mova-fpl-experiments/EXP-MOVA-2026-021 \
  --output ../mova-fpl-experiments/EXP-MOVA-2026-022 \
  --fpl-db ../mova-pro-futbol-data-analytics/data/processed/fpl_canonical.db
```

Una traza parcial se conserva y bloquea sobreescritura. Un resultado existente
se reutiliza sólo bajo el mismo protocolo. El manifest congelado debe estar
presente; los hashes no se reconstruyen para hacer pasar una fuente alterada.
Para una reproducción desde cero, crear un directorio externo nuevo, copiar
[el manifest del mecanismo](protocols/exp022-mechanism.json) a `manifest.json`
y usar ese directorio en ambos comandos. El
[protocolo aislado](protocols/exp022-policy-isolated.json) conserva los hashes del
runner, planner, bundle y datos usados. Una reproducción no es otra temporada.


## Auditoría de aislamiento de brazos

La primera pareja de replays reutilizó el mismo objeto de predictor y produjo
2.212/2.192. Se **invalidó** antes de registrarla como comparación: DefCon se
adapta en `PointsModel.prepare_history` y el objeto compartido conservaba estado
aprendido durante el primer replay. En GW2 cambiaron las matrices xP aunque el
estado previo era idéntico. Ese −20 no mide el aporte del planner.

`EXP-MOVA-2026-022/invalidation.json` preserva el motivo y los resultados originales.
La ejecución corregida vive en `EXP-MOVA-2026-022-isolated`, con bundle cargado
independientemente por brazo. El proyector exige hashes idénticos de xP/matriz/SD
para todas las GWs antes de decidir. El benchmark rechaza registrar comparaciones
marcadas como invalidadas, aunque mantiene su inventario. Esto no atribuye el mismo
problema a EXP021: sus brazos se ejecutaron mediante invocaciones separadas.


## Resultado válido y decisión

La repetición aislada completa 76 jornadas (dos brazos de 38) en 2025/26:
**2.212 vs 2.212, PVA-38 = 0**. Coinciden 38/38 hashes de proyección y 38/38
fingerprints de decisión, tres hits y las ocho fechas de poderes. El bootstrap
pareado devuelve [0,0] porque todos los deltas observados son cero; no implica
certeza de equivalencia en otras temporadas o estados.

El mecanismo mejora el pronóstico de oportunidades pero no cambia la política
realizada en esta trayectoria. **Candidato no seleccionado; promoción no autorizada.**
No se modifica K, suavizado ni el control después de ver este resultado. La primera
corrida contaminada permanece invalidada y no aporta una temporada adicional.

La siguiente hipótesis debe intervenir sobre decisiones que este estado comprimido
no representa: transiciones de plantilla condicionadas a la acción y valor conjunto
Wildcard/Bench Boost, FT y banca. Antes de ajustar otra política, instrumentar los
estados y acciones de oportunidades, preservar precios/FT y construir cobertura
histórica causal de calendario/chips. La comparación deberá incluir la tasa de
cambio de decisión: aquí fue 0/38 pese a cambiar los valores de continuación.
No existe evidencia para promover el planner Markov ni para prometer una gran
mejora del siguiente candidato.

[Resultado portable](transition-results.json) y
[benchmark v2](../benchmark/snapshots/v2/REPORT.md) conservan la comparación válida.
