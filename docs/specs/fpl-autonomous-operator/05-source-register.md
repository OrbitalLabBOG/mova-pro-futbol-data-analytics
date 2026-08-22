---
type: project
name: "MOVA FPL Autonomous Operator 2026/27 — Source Register"
created: 2026-08-21
updated: 2026-08-21
tags: [mova, fpl, research, sources]
status: proposed
---

# Registro de fuentes

Última verificación: 2026-08-21. Las reglas cambian por temporada; el collector debe
revalidarlas y sellar el bootstrap en vez de asumir que esta lista seguirá vigente.

## Reglas y operación FPL 2026/27

| Fuente | Hecho usado |
| --- | --- |
| [FPL Terms](https://fantasy.premierleague.com/help/terms) | Cláusulas 27, 28(d), 36: control de cuenta, sistemas automatizados y consecuencias de breach. El contenido se carga en un asset JS y fue inspeccionado directamente. |
| [Managing your team](https://www.premierleague.com/en/news/2174899) | Deadline 90 minutos antes, formación, capitán/vice, autosubs y guardado. |
| [Making transfers](https://www.premierleague.com/en/news/2174907) | 1 FT/GW, roll hasta 5, -4, misma posición, 3/club, PP/SP/CP y profit rule. |
| [Chips 2026/27](https://www.premierleague.com/en/news/4679879/whats-happening-with-fpl-chips-in-202627) | Dos juegos de WC/FH/BB/TC; primer juego vence en GW19; uno por GW; FH no GW1. |
| [Price Change Predictor](https://www.premierleague.com/en/news/4680462/whats-new-in-202627-fantasy-price-change-predictor) | Predictor oficial, refresh 15m, cambios 00:00 UK, calibración y señal no garantizada. |
| [BPS 2026/27](https://www.premierleague.com/en/news/4679946/whats-new-in-202627-fantasy-changes-to-bonus-points-system) | tie rules, tackled removido, CBI 1/3 y ajustes de saves/big chance/penalty. |
| [Defensive contributions](https://www.premierleague.com/en/news/4361991/whats-happening-with-defensive-contribution-points-in-202627-fantasy) | DEF 10 CBIT; MID/FWD 12 CBIRT; +2 máximo por partido. |
| [Official injury list](https://www.premierleague.com/en/news/4450606) | Fuente Tier 1 de disponibilidad. |
| [Player Notes](https://www.premierleague.com/en/news/4485566/new-player-notes-feature-warns-fpl-managers-of-possible-upcoming-absences) | Señal oficial contextual en el juego. |
| [Predicted line-ups](https://www.premierleague.com/en/news/4604508/predicted-line-ups-for-premier-league-teams-in-matchweek-29) | Patrón de actualización posterior a ruedas de prensa; predicción, no confirmación. |
| [Pre-season lessons 2026/27](https://www.premierleague.com/en/news/4681482/fpl-202627-pre-season-lessons-for-every-club) | Contexto de roles/minutos de pretemporada. |
| `https://fantasy.premierleague.com/api/bootstrap-static/` | Catálogo, eventos, chips, reglas/configuración y deadline vivo. Endpoint técnico observado, no garantía contractual de API pública. |
| `https://fantasy.premierleague.com/api/fixtures/` | Fixture vivo; requiere validación por season/GW. |

## Arquitectura y observabilidad

| Fuente | Decisión respaldada |
| --- | --- |
| [SQLite Write-Ahead Logging](https://sqlite.org/wal.html) | Un writer, readers concurrentes, checkpoints y restricción same-host; versión corregida ≥3.51.3 por el bug WAL-reset. |
| [SQLite Online Backup API](https://sqlite.org/backup.html) | Backup consistente de una base activa mediante API/`.backup`. |
| [SQLite integrity_check](https://sqlite.org/pragma.html#pragma_integrity_check) | Verificación de integridad en operación, backup y restore drill. |
| [Prometheus instrumentation](https://prometheus.io/docs/practices/instrumentation/) | Batch jobs: last success, duración, items y estados. |
| [Prometheus Pushgateway guidance](https://prometheus.io/docs/practices/pushing/) | Evitar Pushgateway general por stale metrics y pérdida de `up`. |
| [Docker Compose services](https://docs.docker.com/reference/compose-file/services/) | healthcheck, resource limits, restart, secrets, read-only y dependencia por salud. |
| [systemd.timer](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html) | Temporizadores persistentes y administrables; página devolvió 403 al crawler, se debe validar en el man local al implementar. |
| [agent-browser](https://github.com/vercel-labs/agent-browser) | perfiles persistentes y sesiones aisladas; no resuelve por sí solo cumplimiento ni idempotencia. |

## Referentes analíticos y de automatización

Estas fuentes inspiran capacidades; no validan su calidad ni sustituyen evidencia local.

| Referente | Patrón útil | Límite para MOVA |
| --- | --- | --- |
| [Data-Driven Team Selection](https://arxiv.org/abs/2505.02170) | integer programming y evaluación out-of-sample | no cubre operación autenticada/observabilidad de MOVA |
| [OpenFPL](https://arxiv.org/abs/2508.09992) | forecasting abierto comparable con servicios privados | revisar datos/reglas por temporada antes de adoptar |
| [FPL Optimiser](https://github.com/sunilgodara/fpl-optimiser) | multi-week, chips, presets y límite público de FTs | referente de features, no baseline causal local |
| [FPL-Auto](https://github.com/bentindal/FPL-Auto) | ambición de manager autónomo | no demuestra gates contractuales ni write verification |
| [fpl-bot](https://github.com/rithikbanerjee314/fpl-bot) | schedule recurrente y chips como hints | alcance menor; refuerza rollout supervisado |

## Política de uso

- Tier y TTL se asignan a cada observación, no al dominio entero.
- Un artículo que predice XI no se convierte en confirmación aunque sea oficial.
- La fecha de publicación y la del hecho deben distinguirse.
- Toda extracción conserva URL canónica, hash y `observed_at`.
- Una fuente caída o modificada no reescribe evidencia histórica.
- Las licencias y términos se revisan antes de almacenar o redistribuir contenido completo;
  por defecto se conserva claim estructurado y enlace, no el artículo íntegro.
