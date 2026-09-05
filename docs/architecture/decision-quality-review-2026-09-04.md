---
title: "MOVA FPL — revisión de decisiones, investigación y autonomía"
date: 2026-09-04
status: research-review
owner: MOVA Fantasy
tags: [fpl, research, decision-quality, autonomy, evaluation]
---

# Revisión de decisiones y autonomía

## Alcance y conclusión

Revisión del código `161cfe1` (v0.6.3), runtime observado el 4 de septiembre de
2026, skills, plan y evidencia del laboratorio EXP-MOVA-2026. Se inspeccionaron
las rutas centrales y resultados guardados; no se reejecutaron todos los
backtests. La búsqueda se hizo con Orbix Research y se complementó con fuentes
primarias: no constituye una revisión sistemática exhaustiva.

El objetivo asumido es maximizar puntos de temporada. Ganar una mini-liga puede
requerir otra función objetivo según diferencia, rivales y jornadas restantes.
Esta revisión propone experimentos; no modifica la spec aprobada, promueve un
modelo ni autoriza escrituras en FPL.

La mayor oportunidad es conectar un pronóstico temporal correcto con decisiones
legales de temporada y comprobar su utilidad. Hay mejoras prometedoras ya
implementadas en shadow. Añadir complejidad sin aprovecharlas duplicaría trabajo.

## Salud: infraestructura y calidad de decisión son dimensiones distintas

El doctor observado pasó 24 checks, sin warnings ni fallos. API, PostgreSQL,
fuentes de datos y ocho timers estaban saludables. El checkout y la imagen
coincidían. Esto acredita operación, no superioridad del modelo.

La preparación para autonomía tenía 15 checks aprobados, 10 pendientes y ninguno
bloqueado; seguía `not_ready`, A0/shadow, con kill switch activo y browser writes
desactivadas. Faltan evidencia de drivers, ciclos completos, alertas externas y
backup/restore fuera del host, entre otros gates. Había ocho incidentes P2 de
shadow decision; el último inspeccionado correspondía a un HTTP 503 del endpoint
oficial de historial. No se verificó una causa común para los ocho.

GW4 era preliminar porque GW3 no estaba cerrada. Los 30 registros de evaluación
analítica no equivalen a 30 jornadas independientes; el scorecard de mejora
continua aún mostraba cero evaluaciones y cero lecciones.

La suite ejecutada durante esta revisión del README obtuvo 1.329 passed,
6 failed, 1 skipped y 79 deselected. Los seis fallos usan un deadline fijo ya
vencido contra el reloj real: la autorización devuelve correctamente
`deadline_closed`. Hay que congelar el reloj en esas pruebas, manteniendo las
pruebas de rechazo después del deadline.

## Hallazgos del motor

| Área | Evidencia vigente | Consecuencia / mejora propuesta |
| --- | --- | --- |
| Historial | `append_closed` ya incorpora jornadas oficiales cerradas; EXP-019 reparó atribución histórica de club | No volver a diagnosticar como pendiente el historial congelado de Haaland/Sangaré. Medir la corrección con liquidación real. |
| Horizonte operativo | `cli/live.py` alimenta `build_xp_matrix`: xP del rival actual × cantidad de fixtures × decay 0,84 | Evaluar el proyector por rival, localía y fixture que ya existe en `engine/projection.py`, antes de inventar otro planificador. |
| Dobles jornadas | El servicio analítico multiplica la proyección de un fixture; el proyector alternativo suma fixtures, con disponibilidad congelada | Unificar contratos y modelar descanso/rotación compartidos; no asumir que ambos partidos tienen idéntica expectativa o disponibilidad independiente. |
| Minutos | Clasificador con recencia, historial y calibración; sin features explícitas de congestión, minutos en copas o cambios de rol | Challenger de titularidad, suplencia y minutos condicionales con información disponible antes del deadline. |
| Puntos | Tasas por componentes con shrinkage; minutos condicionales globales por rama; bonus a partir de BPS90 agregado | Probar minutos condicionales contextuales y un modelo de bonus que respete la competencia dentro del partido. Comparar con un predictor directo como challenger. |
| Optimización | Peso fijo de banca 0,12; vicecapitán posterior; autosubs reales en evaluación, no optimizados completamente | Evaluar once, orden de banca, capitán y vicecapitán sobre escenarios conjuntos con reglas exactas. |
| Chips y FT | Umbrales explícitos, lookahead limitado y valor terminal heurístico | Calibrar valor de oportunidad mediante replay legal; no elevar horizonte o fijar valor de FT por intuición. |
| Research | Intervenciones tipadas en shadow, sin aplicación; worker usa prompts embebidos | Evaluar el efecto de hechos verificables sobre entradas acotadas; cambiar un SKILL.md no cambia automáticamente el worker desplegado. |

La última evaluación final observada era GW2: sesgo agregado de puntos de
−15,55%, con gran contribución de aparición/minutos. Es una señal para investigar,
no una prueba de que el modelo corregido de GW3 conserve exactamente ese sesgo.
Hay que comparar predicciones congeladas y liquidadas de la misma versión.

## Qué enseñan los experimentos existentes

| Experimento | Resultado registrado | Lectura correcta |
| --- | --- | --- |
| EXP-003, calendario por fixture h3 | Desarrollo: +33, +72, −21; media +28 e IC95 [−95, 155]. Holdout 2025-26: 2.306 vs 2.141, +165 | Prioridad alta para evaluación prospectiva; no evidencia concluyente multitemporada. Auditoría posterior reprodujo fingerprints 38/38. |
| Ablación odds-CS | Replay legal: 2.130 vs 2.168, −38; mejoraba Brier de portería a cero | Menor error predictivo no garantiza mejores decisiones. Conservar como challenger. |
| EXP-004, eventos sobre h3 | +7, +52, −132; media −24,33 | No reincorporar las mismas proxies rechazadas sin una hipótesis nueva. |
| EXP-009, recourse estocástico | Delta cero en las tres temporadas de desarrollo | Añadir escenarios no produjo utilidad en la variante probada. |
| EXP-012, valor terminal fijo de FT | Media −66,5 puntos en cuatro temporadas | Un punto fijo por FT empeoró la política probada. |
| EXP-017, mezcla de estados de minutos | Desarrollo +148, −111, +82; temporada externa +29, frágil a la mejor GW | Mantener en shadow; evitar presentar el ensemble como ganador demostrado. |

Fuentes internas: [laboratorio](../../experiments/long_horizon/README.md),
[ablación de odds/eventos](../decisions/2026-27/odds-events-ablation.md) y artefactos
en el directorio hermano `mova-fpl-experiments/EXP-MOVA-2026-*/`.

Los brazos del shadow de horizonte deshabilitan chips y mantienen trayectorias
virtuales propias. Una diferencia frente a la decisión manual/productiva no se
puede atribuir íntegramente al calendario si también cambian chips o estado.

## Literatura aplicable

| Fuente primaria | Aporte transferible | Límite para MOVA |
| --- | --- | --- |
| [OpenFPL, 2025](https://arxiv.org/html/2508.09992v1), [código oficial](https://github.com/daniegr/OpenFPL) | Ensembles por posición y múltiples horizontes con FPL/Understat; baseline público para un challenger directo | Evaluación prospectiva GW32–38 de 2024/25, no temporada completa. No demuestra superioridad en todas las métricas ni utilidad de una política legal de 38 GW. |
| [A data-driven framework for team selection in FPL, v2, 2025](https://arxiv.org/html/2505.02170v2) | Integra predicción y optimización determinista/robusta de selección | La robustez no mejora uniformemente; no reemplaza el simulador propio de transferencias y chips. |
| [Smart “Predict, then Optimize!”, Elmachtoub y Grigas](https://arxiv.org/abs/1710.08005) | Entrenar considerando el costo de la decisión, no solo error de predicción | SPO+ no aporta por sí mismo evidencia FPL. Aplicarlo después de asegurar causalidad y un comparador estable. |
| [SkillsBench, v4, junio de 2026](https://arxiv.org/abs/2602.12670) | Skills procedimentales enfocadas, evaluadas contra agentes sin skill | Beneficio dependiente del entorno; instalar muchas skills no acredita utilidad en nuestro runtime. |
| [Counterfactual Trace Auditing of LLM Agent Skills, 2026](https://arxiv.org/abs/2605.11946) | Comparar trazas con/sin skill, además del resultado | Medir adherencia, costo y efecto incremental; una explicación más larga puede no mejorar decisiones. |
| [τ-bench, 2024](https://arxiv.org/abs/2406.12045) | Verificar estado final y consistencia en ejecuciones repetidas | Referencia para fiabilidad del operador, no prueba de calidad futbolística. |
| [FM-Bench, agosto de 2026](https://arxiv.org/abs/2608.18423) | Evaluación de agentes de gestión futbolística con consecuencias de largo plazo | Simulación de clubes, no Fantasy Premier League; transferir metodología, no sus rankings. |

La recomendación derivada es conservar la separación: modelo probabilístico para
pronosticar, optimizador para elegir acciones legales y agente para investigar,
verificar y operar. El LLM debe justificar hechos que cambien entradas, no imponer
un capitán o una transferencia por persuasión narrativa.

## Protocolo para mejorar decisiones

1. **Congelar el information set.** Registrar datos, publicación de noticias,
   hora de disponibilidad, calendario conocido, reglas, modelos y prompts por
   hash antes del deadline. No usar retrospectivamente alineaciones o cambios
   de calendario que todavía no eran públicos.
2. **Separar preguntas.** Comparar una decisión desde un estado común para
   atribución local y, por separado, políticas con plantillas, bancos, FT y
   precios de compra propios durante toda la temporada. Descontar hits y
   liquidar autosubs, capitanía y chips legalmente.
3. **Seleccionar por utilidad.** Métrica principal: diferencia pareada de puntos
   de temporada (PVA-38). Acompañar con calibración de minutos, CRPS, cobertura,
   cambios de decisión, hits y fragilidad por jornada/temporada. Un oracle con
   resultados futuros sirve como diagnóstico, nunca como política ejecutable.
4. **Evitar selección sobre el examen.** El holdout 2025-26 fue válido para el
   candidato congelado original; su reutilización adaptativa no crea nuevos
   holdouts independientes. Usar selección temporal anidada y candidatos
   congelados para evaluación prospectiva. Reentrenar por fold: los artefactos
   productivos ajustados hasta 2025-26 no se evalúan como holdout en esa temporada.
5. **Mantener incertidumbre honesta.** Bootstrap por bloques y sensibilidad a
   temporadas/jornadas, sin excluir derrotas. Tres cierres consecutivos acreditan
   continuidad operativa, no superioridad estadística.

El replay histórico conoce la asignación final de aplazamientos; 2022-23 no se
simula por las transferencias ilimitadas del Mundial y Assistant Manager de
2024-25 no está modelado. Estos límites impiden vender los puntos simulados como
una predicción exacta del rendimiento futuro.

Para escenarios nuevos, distinguir incertidumbre sobre capacidad/minutos de la
aleatoriedad del resultado. Modelar correlación entre goles, asistencias, clean
sheets y disponibilidad. El recourse actual fija la primera acción y resuelve
futuros completos por escenario: revisar no anticipatividad antes de ampliarlo,
pues podría valorar decisiones futuras como si conocieran resultados aún no
observados. Es un riesgo metodológico a probar, no una acusación de leakage vivo.

## Secuencia propuesta dentro del plan vigente

| Orden | Entrega concreta | Criterio de aceptación |
| --- | --- | --- |
| 1 | Cerrar GW3 cuando sea oficial y auditar trazas del baseline corregido; corregir reloj de pruebas | Liquidación reproducible, versión identificada y suite sin fallos temporales |
| 2 | Evaluar `season_fixture_h3` con el mismo contrato de proyección, chips y estado; registrar diferencias en DGW | Atribución limpia, continuidad de shadow y evidencia prospectiva antes de promoción |
| 3 | Challenger de minutos con titular/suplente, descanso y cambios de rol; comparar también el ensemble existente | Mejora en calibración y utilidad decisional fuera de muestra, sin regresiones ocultas por promedios |
| 4 | Challenger directo de puntos y evaluación conjunta de capitanía/banca; estudiar bonus y chips por separado | PVA-38 y sensibilidad favorables frente al baseline congelado, con costo medido |
| 5 | Research enfocado en decisiones sensibles: disponibilidad, rol y rotación; hechos con fuente y caducidad | Ensayo pareado con/sin intervención, inputs acotados y cero acciones forzadas por el LLM |
| Transversal | Gates del harness: drivers, alertas externas, restore fuera del host y ciclos completos | Evidencia durable que satisfaga el preflight; ninguna promoción automática por mejorar xP |

Para skills, reutilizar `fpl-expert`, `mova-fpl-operator` y `fpl-web-ops`, añadiendo
referencias pequeñas para auditar pronósticos, comparar decisiones y liquidar
resultados. Versionar explícitamente las instrucciones que consume el worker;
medir factualidad, cumplimiento, latencia y costo con/sin esos módulos. No asumir
que el runtime descubre skills del repositorio.

La [spec del harness](../specs/fpl-autonomous-operator/10-autonomous-harness-v1.md)
sigue siendo la hoja de ruta. Primero fiabilidad demostrada en shadow; después,
habilitación gradual por tipo de acción y riesgo bajo sus gates. La promoción de
un modelo y el permiso para escribir en FPL son decisiones independientes. La
primera iteración recomendada es cerrar evidencia existente y evaluar calendario
por fixture, no reescribir el sistema ni activar autonomía total.
