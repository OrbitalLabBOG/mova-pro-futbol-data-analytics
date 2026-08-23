---
type: preliminary-review
name: "GW2 — preliminar con GW1 aún abierta"
created: 2026-08-23
updated: 2026-08-23
tags: [mova, fpl, gw2, research, readiness, chips, evidence]
status: preliminary
---

# GW2 — revisión preliminar

## Veredicto

La corrida es útil para descubrir hipótesis, pero **no autoriza Wildcard ni transferencias**.
La API oficial mantiene GW1 como `is_current`, `finished=false` y `data_checked=false`; Fulham–
Chelsea aún no había comenzado. GW2 ya estaba marcada `is_next`, con deadline
`2026-08-28T17:30:00Z`.

El equipo llevaba provisionalmente 27 puntos, 25 en el banco y João Pedro pendiente. Estas cifras
pueden cambiar con el último partido, autosubs, bonus y validación final.

## Inputs sellados

- Snapshot público: `20260823T182425Z`.
- Bootstrap SHA-256: `4190d2d795260512670766491e4549783cbe4ba18b0935dc9dd25495af1281ab`.
- Fixtures SHA-256: `fd29f1ae5dff7b2021b012d66beefbb56ff18734cccedce2b39c6d8dd5a95aa9`.
- 606 jugadores, 20 clubes, 380 fixtures y 118 jugadores con disponibilidad reducida.
- Estado privado sanitizado de `losmillosFPL`, team id `3609854`: 15 jugadores, una FT y £0.0m.
- Modelos: minutes/points `1.1.0`; política MILP, horizonte GW2–GW4.

## Escenarios

| Escenario | xP GW2 | Operaciones | Chip | Observación |
| --- | ---: | ---: | --- | --- |
| chips bloqueados | 48.8 | 2 transferencias, 1 hit | ninguno | vende Haaland y M. Sangaré; compra Enzo e Igor Thiago |
| planificador activo | 54.7 | 12 transferencias | wildcard | diferencia inmediata visible de 5.9 xP; valor de horizonte reportado +16.1 |

Ambas plantillas pasan reglas formales. Eso valida presupuesto/composición, no la premisa deportiva.

## Señales que impiden promover la Wildcard

1. GW1 no está asentada y Chelsea todavía no había jugado.
2. La propuesta sin chips vende a Haaland antes de Coventry (H) en GW3. Haber sumado dos puntos en
   GW1 no es evidencia suficiente para perder esa opcionalidad.
3. Mukiele entra en la Wildcard con P(60) de 91%, aunque Sunderland ya jugó y él registró cero
   minutos en GW1. La API lo marca disponible, por lo que el parte médico solo no captura el riesgo
   de selección.
4. Tres jugadores de Sunderland concentran exposición durante un horizonte que incluye Fulham (H),
   Brentford (A) y Arsenal (H). Debe compararse contra alternativas, no aceptarse por el solve único.
5. Palmer, Enzo y João Pedro no pueden evaluarse con evidencia de GW1 hasta Fulham–Chelsea.
6. `research_signals=0`: todavía no existe acta de prensa, lesiones y alineaciones versionada.

La información pública previa sí respalda que Roefs y Le Fée pertenecen al núcleo de minutos de
Sunderland. Para Mukiele había competencia/recuperación física y la observación real de cero minutos
eleva la incertidumbre; no se convierte automáticamente en `lock_out`, pero exige investigación.

## Ajustes del harness derivados

- `AGENTS.md` pasa a ser la instrucción canónica para Codex; `CLAUDE.md` queda como puente.
- Snapshots incorporan `event_context` con jornada actual, settlement y partidos sin comenzar.
- `mova status` separa salud técnica de `gameweek.readiness`.
- Las actas bloquean promoción mientras la jornada previa no esté `finished + data_checked`.
- Las actas enumeran entradas/salidas y expresan hits en puntos.
- Compose entrega las rutas canónicas de DB/modelos también a corridas manuales, eliminando drift
  entre el scheduler y el CLI.

No se recalibra el modelo con una sola jornada. La incorporación causal de minutos actuales,
confirmaciones de lineup y señales de research pertenece a HV1-03/HV1-05 y debe medirse en shadow.

## Siguiente revisión

1. Recolectar al cerrar GW1 y verificar `finished/data_checked`.
2. Reconciliar puntos, autosubs y score definitivo del equipo.
3. Incorporar noticias y probabilidad de minutos con fuente/fecha/confianza.
4. Correr cuatro escenarios: hold, una FT, hit y Wildcard.
5. Comparar GW2 y horizonte, incluyendo explícitamente una variante que conserva Haaland.
6. Emitir acta provisional después del settlement y acta final dentro de las últimas 24 horas.

## Fuentes públicas

- API oficial FPL: `https://fantasy.premierleague.com/api/bootstrap-static/` y
  `https://fantasy.premierleague.com/api/fixtures/`.
- Calendario oficial Premier League:
  `https://www.premierleague.com/en/news/4675097`.
- Predicted lineups FFS:
  `https://cdn.fantasyfootballscout.co.uk/team-news`.
- Contexto Sunderland/minutos:
  `https://www.fantasyfootballscout.co.uk/2026/08/03/fpl-pre-season-mukiele-le-fee-injuries-mbeumo-pen`.
