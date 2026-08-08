# WP-005 · Conteo defensivo derivado de Opta contra el CSV de FPL

**Temporada:** 2025-26 · **Partidos con eventos:** 291 de 380 · **Eventos:** 58,842

## Concordancia por variante de correspondencia

| Variante | Pares | Exacto | ±1 | ±2 | Sesgo medio | Correlación |
|---|---:|---:|---:|---:|---:|---:|
| `estricta` | 6,413 | 70.2% | 93.6% | 98.6% | -0.09 | 0.983 |
| `con_bloqueos` | 6,482 | 49.8% | 83.8% | 95.1% | +0.42 | 0.967 |
| `entradas_ganadas` | 6,446 | 43.0% | 80.1% | 93.5% | -0.05 | 0.950 |

Mejor correspondencia: **`estricta`**.

## Desglose por posición de la mejor variante

| Posición | Pares | Exacto | ±1 | Sesgo |
|---|---:|---:|---:|---:|
| DEF | 2,426 | 58.0% | 89.1% | -0.24 |
| FWD | 641 | 90.3% | 99.7% | -0.06 |
| GKP | 366 | 50.8% | 83.1% | +0.71 |
| MID | 2,980 | 78.2% | 97.3% | -0.08 |

## Dónde está la discrepancia

| Evento Opta | Columna del CSV | Exacto | ±1 | Media Opta | Media CSV | Corr. |
|---|---|---:|---:|---:|---:|---:|
| Tackle | `tackles` | 99.2% | 100.0% | 1.17 | 1.17 | 0.998 |
| BallRecovery | `recoveries` | 93.2% | 94.4% | 2.87 | 3.24 | 0.778 |
| Clearance + Interception | `clearances_blocks_interceptions` | 71.4% | 93.9% | 2.65 | 2.83 | 0.972 |
| bloqueos implicitos (CBI − C − I) | `—` | — | — | 0.51 | 0.18 | -0.049 |
