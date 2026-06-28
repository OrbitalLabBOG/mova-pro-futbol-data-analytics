# Supermodelos de predicción — referencia (post-grupos)

> Snapshot **2026-06-28** (fin de grupos, pre-R32). Cifras de junio 2026. Las % implícitas de casas las calculamos nosotros (brutas, con vig → suman >100%). Donde no se pudo confirmar, se marca explícitamente.

## Tabla maestra — probabilidad de TÍTULO (%)

| Equipo | Opta | Nate Silver/PELE | Kalshi | Polymarket | Casas (FanDuel impl.) |
|---|---|---|---|---|---|
| 🇫🇷 Francia | **18.66** | paywall¹ | 24.9 | 22.9 | 22.7 |
| 🇦🇷 Argentina | **16.26** | paywall | 21.9 | 20.8 | 19.6 |
| 🇪🇸 España | 13.47 | ~11.7 (pre)³ | 10.5 | 11.2 | 13.3 |
| 🏴 Inglaterra | 9.68 | paywall | 10.0 | 10.3 | 13.3 |
| 🇧🇷 Brasil | 6.47 | paywall | 5.9 | 6.1 | 7.1 |
| 🇳🇱 P. Bajos | 5.11 | paywall | 6.3 | 5.1 | 5.6 |
| 🇵🇹 Portugal | 4.74 | paywall | 6.6 | 5.8 | 6.3 |
| 🇩🇪 Alemania | 4.36 | paywall | 3.7 | 4.0 | 6.3 |
| 🇨🇴 Colombia | 3.19 | paywall | 2.7 | 2.7 | 2.8 |
| 🇳🇴 Noruega | 2.95 | paywall | n/d | n/d | 2.8 |
| 🇺🇸 USA | fuera top-10 | paywall | 3.6 | 2.3 | 2.8 |

¹ PELE post-grupos está tras paywall (no confirmado). ³ España PELE 11.7% es **pre-torneo**, no comparable directo.

## Favorito por modelo y cambio vs pre-torneo

- **Opta:** Francia **18.66%** (era 2ª con 13.0%; saltó al ganar sus 3). España cayó de favorita a 3ª (13.47%) tras el 0-0 con Cabo Verde. Brasil casi inmóvil.
- **Kalshi / Polymarket:** Francia ~23-25%. **Argentina disparó** tras cierre de grupos (bracket favorable) a ~21%.
- **Casas:** Francia favorita (+340/+350). USA de 60-1 → 30-1 tras ganar Grupo D.
- **FiveThirtyEight (SPI) está MUERTO** (cerró 2023). Heredero = natesilver.net (PELE).
- **Modelo U. Liverpool** (España 26.1%, final Eng-Esp): es **pre-torneo (12-jun)**, ya desactualizado.

## Divergencias = dónde está el value (lo más valioso)

| # | Equipo | Lectura | Posible jugada |
|---|---|---|---|
| A | **Argentina** | Mercados 21-22% vs Opta 16.3% (gap ~5pts). Mercado "se enamoró" del bracket fácil (Cabo Verde en R32) | Si confías en xG → **fade Argentina** |
| B | **Francia** | Mercados 23-25% vs Opta 18.7%. Cara por el 3-de-3 | Posible **fade**, value en el campo |
| C | **España** | Opta 13.5% (3ª) vs mercados 10-11% (5ª). Castigada de más por el 0-0 vs Cabo Verde | Posible **value de compra** si fue ruido |
| D | **Inglaterra** | Casas 13.3% vs Opta/mercados ~10% | Pequeño fade |
| E | **USA** | Kalshi 3.6% vs Polymarket 2.3% — sesgo local US | Sobrevalorada en Kalshi |

**Dato estructural:** España+Francia+Inglaterra+Argentina+Brasil ≈ 60% combinado — **el top más parejo en una década** → favorece estrategias de value sobre apostar al favorito.

## Metodología: qué funciona

- **Mercados (Kalshi/Polymarket) reaccionan más rápido y fuerte** a bracket/momentum; **Opta (xG + plantilla) es más estable y conservador**. La **divergencia Opta-vs-mercado es la señal de value**.
- El formato 48 (8 mejores terceros) **amortiguó** los upsets en clasificación: casi todos los favoritos pasaron (salvo Uruguay) → ningún modelo quedó catastróficamente mal.
- PELE fue el más contrarian pre-torneo (bajó a Francia por grupo difícil) → la subestimó (Francia ganó los 3).

## R32: lo publicado
- **Opta** prob. de llegar a cuartos (anfitriones): USA 42.5%, México 28.3%, Canadá 25.2%. No publica % por partido.
- **PELE:** 200.000 simulaciones para knockout, pero % por partido tras paywall.
- **No hay % partido-a-partido confirmados** de R32 (paywall o no publicado).

## Implicación para NUESTRO modelo
- **Benchmark dorado = Opta** (xG + fuerza de plantilla, estable). Recalibrar tras cada jornada.
- **Nuestro diferenciador = reportar el delta modelo-vs-mercado** como métrica de value. Hoy ese delta señala: Argentina y Francia sobrevaloradas por mercado; España posible compra; USA inflada en Kalshi.

## Fuentes
- Opta Knockout: https://theanalyst.com/articles/world-cup-2026-knockout-stage-predictions-opta-supercomputer
- SI supercomputer post-grupos: https://www.si.com/soccer/supercomputer-predicts-2026-world-cup-winner-after-group-stage-concludes
- Nate Silver/PELE: https://www.natesilver.net/p/world-cup-2026-odds-predictions
- Polymarket: https://polymarket.com/event/world-cup-winner
- DeFiRate (Kalshi+Poly agregador): https://defirate.com/prediction-markets/world-cup-odds/
- U. Liverpool (pre-torneo): https://news.liverpool.ac.uk/2026/06/12/is-it-euro-2024-all-over-again-supercomputer-predicts-world-cup-results/
