---
type: decision
name: GW3 — cierre oficial y feedback
created: 2026-09-08
updated: 2026-09-08
status: verified
tags: [mova, fpl, settlement, feedback]
---

# GW3: cierre y feedback

Corte del 8 de septiembre de 2026, 13:47 Colombia. API oficial con
`finished=true` y `data_checked=true`. Runtime FPL v0.7.0,
`dea98e20db44b05da7b426d0b4476f1cd5fca928`, controles A0/shadow conservados.

## Resultado y comparadores

| Escenario | Puntos | Límite |
| --- | ---: | --- |
| Equipo realmente montado | 45 | 51,05 xP predeadline; promedio oficial 51 |
| Revertir únicamente Egan/Tarkowski a Rodon/Mosquera | 42 | Maguire y Thomas entran automáticamente; no valora FT futuras |
| MILP con Wildcard, acta 15:45:18 UTC del 4 de septiembre | 57 | Consume hipotéticamente Wildcard; no compara utilidad de temporada |
| `season_fixture_h3` | 45 | Shadow virtual, primera GW liquidada |
| Control pareado de ese shadow | 50 | Diferente del MILP con Wildcard |
| Mejor XI retrospectivo con nuestra plantilla | 57 | Oráculo con resultado conocido; no recomendación ex ante |

Transferencias: 9 puntos brutos y **+3 netos** después de autosubs. Capitán
Haaland: 9 base / 18 efectivos, mejor capitán retrospectivo de nuestra plantilla.
La banca sumó 17: Kinsky 6, Tzolis 5, Maguire 2 y Thomas 4. El techo de mejora
legal del XI era 12, no 17; conocer esos resultados no demuestra que Bench Boost
fuera correcto antes de jugar.

Acumulado: 208 puntos. El historial de GW3 devuelve overall rank 1.516.623;
el snapshot del endpoint entry conservado en PostgreSQL devuelve 1.516.596.
La diferencia entre endpoints se conserva; puntos y rank de jornada 7.750.318
sí concilian. GW2 registraba overall rank 845.574.

## Calidad predictiva

Baseline final: 652 jugadores comparados de 654, MAE 1,0448, RMSE 1,9454,
Spearman 0,7673, sesgo agregado −6,4513%; Brier P60 0,07182. Cero residuos
contables. Subestimó portería a cero y sobreestimó goles/asistencias en el
agregado. `drift=insufficient`: las seis jornadas de referencia no existen aún.
En nuestros 15 jugadores, MAE 2,435; los agregados de toda la liga incluyen
muchos jugadores sin minutos y no sustituyen la evaluación de la plantilla.

Tzolis tenía P60 0,418 y jugó 90; Sangaré tenía P60 0,781 y jugó 45.
Es un foco para revisar participación y contexto antes de GW4, no evidencia
suficiente para modificar calibración tras una sola jornada.

## Evidencia y registro

- Paquete versionado: `decisions/fpl/2026-27/gw03_closeout.json`.
- Atribución suplementaria: `decisions/fpl/2026-27/gw03_feedback.json`.
- Montaje: timestamp oficial `picks_last_updated=2026-09-04T15:30:24.909593Z`,
  observado otra vez a las 17:12:34.995 UTC; screenshot verificado por SHA-256
  `804bd7cf1fe1d8e79096abc1edd1bc472a415fe04bf204d5bf6c5eb521314de9`.
- La revisión se fecha el 8 de septiembre: no se inventó aprobación anterior.
  El candidato `do_nothing` describe el equipo humano observado; el envelope
  del motor seleccionaba `milp_baseline`. Son decisiones distintas.
- Los precios de la plantilla real son precios autenticados de compra (£100,0);
  el valor de mercado £100,6 se conserva separado en `source_decision`.
- Job cierre: `job_b8a8478e9f2948f9b780c757ffea1e40`.
- Review: `review_43b4f36993342f7015e0e1f9`; artifact SHA-256
  `8de166f40c5e5419d6429ddaf20b99d82adc72bc76ca46260f6b91d58d7611d4`.
- Review automático: `causalreview_1e359386258a0c528f4ee1d4`; SHA-256
  `cf9bc5a656e3267052df5edd58d217540954cefcc18ae2a40f8483dc67ccd30d`.
  Creó cero propuestas: recurrencia insuficiente. Su contador de 73 checks
  fallidos agrega historia del ciclo; requiere clasificación por check antes
  de atribuir un defecto deportivo al optimizador.

El cierre escribió settlement, 30 outcomes selected/comparator, siete checks y
traza mediante `mova review gw`, después de backup. No promovió modelo,
autonomía ni driver. El importador de ejecución supervisada A1 y la normalización
de autoridad siguen pendientes; el closeout retrospectivo no completa esos gates.

## Operación y siguiente paso

El sync PostgreSQL falló por contención breve del lock con el tick a las
10:10:15 UTC. Reejecutar el servicio a las 18:41:53 UTC reutilizó el import
verificado, sin nueva fotografía. El ajuste del service espera hasta 60 segundos
por el lock y conserva el fallo si vence el plazo. Suite: 1.728 passed,
1 skipped, 79 deselected en el venv Python del laboratorio; la primera ejecución
en conda global falló por colisión del paquete `tests`, no por el cambio.

Para GW4 (12 de septiembre, 07:30 Colombia): actualizar memoria desde el review,
revisar minutos y titularidad de Tzolis/Sangaré, comparar alternativas sin chip
con oportunidad futura de chips y completar research/deliberación dentro del
presupuesto. Mantener A0/shadow. Quedan ocho P2 históricos, alertas externas,
backup off-host y evidencia multi-GW; no se cierran por pasar el doctor.


Verificación posterior a la reparación, 13:52:32 Colombia: **doctor 24 PASS,
0 WARN, 0 FAIL**. Unidad instalada desde el cambio `96352c5`, validada con
`systemd-analyze verify` y ejecución idempotente aprobada. Rollback:
`/var/lib/mova-fpl/artifacts/host-config/20260908-gw03/postgres-sync.service.before`.
El checkout y la imagen del motor conservan `dea98e2`; sólo cambió la unidad host.

La fotografía post-closeout `pgimport_16285642570e43e0849598dab3ee44ad`
pasó 57 tablas. La memoria GW4 con SHA-256
`d2821edb42838827b240f279066c8b0e87c87444a12cefa7eef4f2b129fdb9f6`
incluye ambos reviews de GW3. Los ocho P2 se revisaron individualmente: todos
terminan en HTTP 503 del historial público FPL tras cinco intentos el 4 de
septiembre. Se conserva su estado abierto para el tratamiento de incidentes;
no son fallos actuales de integridad ni afectan los 45 puntos conciliados.

Seguimiento PM actualizado con autorización del usuario: tarea GW3 cerrada,
24/35 tareas done. El paquete está en PR draft #156; merge pendiente.
