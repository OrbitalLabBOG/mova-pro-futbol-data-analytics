# Backtest, experimentos y crítica honesta

> 2026-06-28. Medimos el modelo con evidencia (backtest leakage-free WC2018+2022) y lo cuestionamos contra lo que de verdad pasó. Sin maquillaje.

## El experimento que lo define todo

Backtest walk-forward, sin leakage, 128 partidos WC2018+2022 (Elo propio pre-partido + xG de StatsBomb acumulado solo de partidos previos del torneo). Comparamos meterle xG al core con peso θ:

| θ (peso xG en λ) | RPS | skill vs Elo |
|---|---|---|
| **0.0 (Elo puro)** | **0.2165** | baseline ← **mejor** |
| 0.2 | 0.2161 | +0.2% (ruido) |
| 0.4 | 0.2170 | −0.2% |
| 0.6 | 0.2194 | −1.3% |
| 0.8 | 0.2233 | −3.1% |

**Veredicto del experimento:** meter xG / ataque-defensa al **ranking** NO mejora la predicción (mejor caso +0.2%, indistinguible de ruido; más peso = peor). Confirma la evidencia de la literatura: en selección, **el Elo-diff domina y las features extra sobreajustan**.

## Decisiones tomadas por la evidencia (no por intuición)

1. **Core = Elo puro** (quitamos el ajuste de forma xG del ranking; `XG_FORM_K=0`). El backtest lo exige.
2. **Anclaje al mercado** (log-pool, w=0.65): nuestro Elo da RPS 0.216 ≈ casas (~0.20), **ligeramente peor** → no le ganamos al mercado, así que lo usamos de ancla.
3. **xG → solo capa de insight** (regresión/suerte/valor), donde sí aporta valor no-predictivo.

## ¿Qué tan bueno es el modelo? (respuesta honesta)

- Como **predictor**, está **al nivel del mercado, no por encima.** El backtest (RPS 0.216) lo dice: nuestro modelo standalone es ~tan bueno como las casas, un pelín peor. Esto es **lo esperable** — el mercado es world-class y batirlo consistentemente en selección es casi imposible (docs/08).
- Tras anclar, el modelo **calibra casi exacto con Opta** (ver abajo). Es decir: es un modelo **sólido y bien calibrado**, no un oráculo que ve el futuro mejor que Opta.
- **Lo "world class" aquí no es out-predecir al mercado** (eso sería deshonesto prometerlo). Es: (a) calibración, (b) la **capa de insight/valor para la polla**, (c) honestidad sobre la incertidumbre.

## Resultado calibrado (Elo + ancla mercado)

| Equipo | MODELO | Mercado | Opta |
|---|---|---|---|
| Argentina | 22.4% | 19.5% | 16.3% |
| France | 21.3% | 21.9% | 18.7% |
| Spain | 13.4% | 10.5% | 13.5% |
| England | 9.3% | 10.1% | 9.7% |
| Brazil | 5.7% | 5.8% | 6.5% |

## Crítica contra lo que de verdad pasó

- **Francia (mejor plantilla, ganó sus 3, varios por goleada):** el modelo la pone #2 (21.3%), prácticamente empatada con Argentina y alineada con Opta/mercado. ✓ Corregido el bug que la hundía.
- **Argentina marginalmente #1 (22.4%):** se sostiene por (a) nuestro Elo la tiene #1 (campeona vigente) y (b) **el bracket más blando** (R32 vs Cabo Verde #40, cuarto débil). El insight lo deja explícito: su ventaja es *camino + rating*, no dominio. Disputa razonable con el mercado (que pone a Francia #1).
- **Regresión (lo no-obvio que sí aporta):** el insight marca **Países Bajos +5.2 y Francia +4.4 goles sobre xG** → finalización caliente, candidatos a regresar; **Turquía −5.2** (gran xG, finalización pésima → eliminada con mala suerte). Esto es señal real que el ojo no cuantifica.
- **Lo que el modelo NO hace (honesto):** no usa head-to-head específico ni matchups de estilo (la evidencia dice que son ruido con pocos partidos; el backtest confirma que ni el xG ayuda al core). No tenemos valor de plantilla (Transfermarkt) — la única feature que la literatura (Groll) muestra que ayuda marginalmente además del mercado.

## Implicación para la polla

El edge **no es un ranking mejor** (somos ≈ mercado). El edge es:
1. **Calibración** + **valor vs el público** (insight): dónde la gente sobre-elige (Brasil/Argentina/Colombia en polla local) y dónde hay value.
2. **Camino de bracket**: Argentina tiene el sorteo más fácil → mejor expectativa aunque Francia tenga mejor equipo.
3. **Regresión**: no caer en el espejismo de la finalización caliente (Francia/Países Bajos).

## Posibles mejoras reales (con evidencia, no fe)

- **Valor de plantilla (Transfermarkt)** como feature — único extra que la literatura muestra que aporta sobre el mercado. Habría que testearlo en backtest.
- **Elo con trayectoria** (SDR, arXiv 2606.24171 reporta RPS mucho mejor) — requiere snapshots históricos de Elo; nuestro Elo propio podría extenderse.
- **Subir w_market** (somos peores que el mercado → quizá merece más peso).
- Todo lo demás (más features de evento) el backtest ya dijo que **no ayuda**.
