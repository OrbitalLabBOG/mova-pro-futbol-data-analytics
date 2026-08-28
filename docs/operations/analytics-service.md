---
type: runbook
name: "MOVA FPL — servicio analítico y drift por gameweek"
created: 2026-08-24
updated: 2026-08-24
tags: [mova, fpl, analytics, model, drift, observability]
status: active
---

# Servicio analítico y drift por gameweek

Esta capa vuelve operable el modelo desde el harness. Sella lo que el modelo sabía antes del
deadline, lo contrasta después contra la API oficial y conserva el scorecard completo. No elige
jugadores, no reentrena y no escribe en la cuenta FPL.

## Flujo y causalidad

1. `mova analytics project` toma el último artifact FPL observado antes del deadline, carga los
   modelos versionados y crea un batch inmutable por jugador con xP, desviación, P(juega), P(60)
   y los diez componentes. Un snapshot nuevo supersede el anterior para esa GW, pero no lo borra.
2. El collector obtiene `event/{gw}/live` para cada jornada `data_checked` y vuelve a leer la
   última por posibles correcciones oficiales.
3. `mova analytics reconcile` evalúa únicamente el batch vigente contra un artifact oficial
   cerrado. La clave `batch + actual artifact + final` vuelve la operación idempotente.
4. `mova analytics run` ejecuta ambos pasos. El timer lo invoca cada 30 minutos; si no hay trabajo
   nuevo termina sin duplicar proyecciones ni evaluaciones.

El estado de jugadores de 2026/27 viene del bootstrap vigente; las tasas individuales aún usan
la última temporada cerrada (`2025-26`), igual que el path de decisión validado. Incorporar
jornadas actuales al estado del modelo requiere un experimento causal y una versión nueva; no se
hace silenciosamente durante `reconcile`.

## Métricas

Cada `model_evaluation_run` expone:

- puntos: total predicho/real, sesgo absoluto y relativo, MAE, RMSE, Pearson y Spearman;
- minutos: Brier y ECE de P(juega) y P(60);
- portería a cero: Brier y log-loss en GKP/DEF con 60+ minutos;
- componentes: total predicho/real, sesgo, sesgo relativo y MAE para aparición, goles,
  asistencias, CS, encajados, DefCon, bonus, tarjetas, paradas y otros;
- cobertura: jugadores proyectados, reales y emparejados.
- accounting: comprueba que los diez componentes sumen exactamente xP/puntos reales; una
  discrepancia alerta de inmediato aunque todavía no existan seis GWs de referencia.

La primera referencia exige seis GWs finales del mismo `variant` y versiones de modelo. Antes de
eso `drift_status=insufficient`: es falta de muestra, no alarma. Después se compara con la mediana
histórica y se marca `watch` o `alert` por sesgo total, ECE, Brier de CS, deterioro de MAE/RMSE o
caída de Spearman. Los umbrales versionados viven en `mova_fpl/analytics/drift.py`; cada motivo
persiste valor y umbrales observados.

Un `alert` abre un incidente P2 deduplicado. Es una señal para estudiar datos, reglas,
calibración y componentes; no autoriza reentrenar ni promover otro modelo automáticamente.

## Datos usados y señales shadow

PostgreSQL conserva `model_projection_batches`, `player_projections`,
`model_evaluation_runs` y `model_evaluation_components`. La migración canónica es `005`.
Los JSON inmutables viven bajo
`/var/lib/mova-fpl/artifacts/analytics-service/projections/<season>/gwNN/`.

- API FPL oficial: activa en proyección y evaluación.
- Odds de mercado: disponible como variante shadow, aún no promovida. El experimento mostró una
  señal defensiva útil, pero no mejoró el backtest legal end-to-end; forzarla en producción sería
  confundir evidencia parcial con mejora del sistema.
- Eventos WhoScored: disponibles para investigación, rechazados como feature productiva por el
  experimento vigente. Su cobertura sigue siendo parte de la salud del data plane.

## Operación del agente

```bash
mova analytics status
mova analytics project
mova analytics reconcile
mova analytics run

curl -s http://127.0.0.1:8787/api/v1/analytics | python -m json.tool
curl -s http://127.0.0.1:8787/api/v1/analytics/scorecards?limit=10 | python -m json.tool
curl -s http://127.0.0.1:8787/api/v1/analytics/gw/2 | python -m json.tool
curl -s http://127.0.0.1:8787/metrics | grep '^mova_model_'
journalctl -u mova-fpl-analytics.service -n 200 --no-pager
```

Secuencia de diagnóstico:

1. Confirmar `mova data coverage` y que la GW tenga `data_checked` + filas live.
2. Confirmar artifact/versiones del batch y que `generated_at < cutoff_at`.
3. Leer `points`, `minutes`, `clean_sheet` y después cada componente; un total cercano puede
   esconder sesgos que se cancelan.
4. Si el estado es `insufficient`, esperar referencias. Si es `watch`, abrir investigación sin
   cambiar el modelo. Si es `alert`, revisar incidente, calidad de fuente, reglas y cambio de
   distribución antes de diseñar un experimento/reentrenamiento.
5. Nunca usar `reconcile` como feature del mismo batch evaluado ni editar una evaluación pasada.

### Jornada histórica sin batch predeadline

No se crea una proyección retroactiva para completar un hueco. `mova review gw` puede registrar un
diagnóstico `retrospective` y una atribución pareada de decisiones documentadas, pero conserva
`causality_status=not_eligible_no_predeadline_batch`. Esos reviews no entran al baseline de drift
ni a `v_model_latest_scorecard`. GW1 2026/27 es el caso de referencia.

## Recuperación

Un fallo deja job, step, `error_code`, correlación y stack trace en journald. Corregir la causa y
volver a ejecutar `mova analytics run`; las claves idempotentes evitan duplicados. Las migraciones
son aditivas. En rollback se puede deshabilitar `mova-fpl-analytics.timer` sin detener collectors,
API, tick ni browser; se preservan PostgreSQL y artifacts para auditoría.

## Último rollout verificado

La evidencia del despliegue del 24 de agosto de 2026, incluidas cobertura, proyecciones shadow,
pruebas y rollback, está en el
[acta del servicio analítico](../decisions/2026-27/analytics-service-rollout.md).
