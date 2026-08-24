---
type: decision
name: "MOVA FPL — rollout del servicio analítico"
created: 2026-08-24
updated: 2026-08-24
tags: [mova, fpl, analytics, drift, postgres, vps, rollout]
status: approved
---

# Rollout del servicio analítico

## Decisión

Se aprueba el servicio analítico en el VPS desde la revisión `85f8873`. El baseline conserva
autoridad sobre el path de decisión; `odds_cs_shadow` se calcula y evalúa en paralelo sin poder
modificar el equipo. WhoScored permanece disponible para research y fuera del modelo productivo.

## Evidencia observada

- PRs #19 y #20 integradas a `main`; CI final: 791 pruebas aprobadas, 1 omitida y 79 pruebas de
  datos lentas excluidas por marcador.
- Backup previo: SQLite `/opt/orbital/backups/mova-fpl/20260824T131859Z` y PostgreSQL
  `/opt/orbital/backups/mova-fpl/postgres/20260824T131902Z`.
- PostgreSQL 17.11 aplicó `005:model_analytics`; migraciones vigentes 1–5.
- Cobertura `complete`: 20 clubes, 38 GWs, 609 jugadores, 380 fixtures, 21 eventos de odds,
  43 bookmakers, 10/10 fixtures GW2 con h2h/totals, 9 partidos WhoScored y 13.744 eventos.
- Proyección GW2 anterior al cutoff `2026-08-28T17:30:00Z`:
  - baseline: 609 jugadores, xP 757,62 y CS 111,53;
  - odds-CS shadow: 609 jugadores, xP 754,09 y CS 109,93;
  - delta xP individual: mínimo −0,3550, promedio −0,0058 y máximo +0,4814.
- Se corrigió el join `Leeds` ↔ `Leeds United`; cobertura final de mercado 10/10, mínimo 34
  bookmakers y máximo fit RMSE 0,0146.
- API healthy/ready y contratos de analytics, scorecards, GW y Prometheus expuestos.
- `mova doctor`: 21 PASS, 0 WARN y 0 FAIL; checkout e imagen en `85f8873`.
- `mova-fpl-analytics.timer` habilitado cada 30 minutos. Su primera ejecución automática cerró
  con exit 0: migración no-op, ambos batches reutilizados en 367 ms y reconciliación en 67 ms,
  sin duplicados y con dos batches correctamente en `waiting_for_data_checked`.

No se creó una evaluación artificial de GW1: la API oficial todavía no reporta `data_checked` y
queda un fixture sin iniciar. El primer scorecard se emitirá tras el cierre oficial. Hasta reunir
seis referencias comparables, drift será `insufficient`, salvo una falla estructural de accounting.

## Rollback

Deshabilitar el timer y restaurar checkout/imagen. La migración es aditiva y se preservan tablas,
artifacts y logs para auditoría. El rollout no habilitó escrituras de browser ni cambió el path de
decisión del equipo.
