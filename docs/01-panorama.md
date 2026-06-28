# Panorama Mundial 2026 — Investigación inicial

> Fecha de corte: **2026-06-28** (fin de fase de grupos, inicio Ronda de 32). Fuentes web — ver enlaces al final.

## 1. Formato y contexto

- Primer Mundial con **48 equipos**, sede USA/México/Canadá. 11 jun – 19 jul.
- 12 grupos de 4 → pasan **2 primeros + 8 mejores terceros** = 32 a **Ronda de 32** (nueva). Eliminación directa hasta la final.
- **Tesis central:** el formato ampliado *debía* favorecer a los grandes; ha hecho lo contrario → más upsets, empates, debutantes. Calor en Norteamérica + viajes largos castigan a favoritos. **Varianza alta.**

## 2. Standings finales fase de grupos

| Grupo | 1° | 2° | 3° | 4° (out) |
|---|---|---|---|---|
| A | México 9 | Sudáfrica 4 | Corea 3 | Chequia 1 |
| B | Suiza 7 | Canadá 4 | Bosnia 4 | Qatar 1 |
| C | Brasil 7 | Marruecos 7 | Escocia 3 | Haití 0 |
| D | USA 6 | Australia 4 | Paraguay 4 | Turquía 3 |
| E | Alemania 6 | Costa de Marfil 6 | Ecuador 4 | Curaçao 1 |
| F | Países Bajos 7 | Japón 5 | Suecia 4 | Túnez 0 |
| G | Bélgica 5 | Egipto 5 | Irán 3 | N. Zelanda 1 |
| H | España 7 | Cabo Verde 3 | Uruguay 2 | A. Saudita 2 |
| I | Francia 9 | Noruega 6 | Senegal 3 | Irak 0 |
| J | Argentina 9 | Austria 4 | Argelia 4 | Jordania 0 |
| K | Colombia 7 | Portugal 5 | Congo DR 4 | Uzbekistán 0 |
| L | Inglaterra 7 | Croacia 6 | Ghana 4 | Panamá 0 |

Pleno de 9 pts: **Francia, Argentina, México**.

## 3. Ronda de 32 (cuadro)

- 28 jun: Sudáfrica–Canadá
- 29 jun: Brasil–Japón · Alemania–Paraguay · P. Bajos–Marruecos
- 30 jun: C. Marfil–Noruega · Francia–Suecia · México–Ecuador
- 1 jul: Inglaterra–Congo DR · Bélgica–Senegal · USA–Bosnia
- 2 jul: España–Austria · Portugal–Croacia · Suiza–Argelia
- 3 jul: Australia–Egipto · **Argentina–Cabo Verde** · **Colombia–Ghana**

## 4. Sorpresas clave

- **Cabo Verde** (debutante, ~525k hab, rank ~67): 0-0 a España, 2-2 a Uruguay. País más pequeño en 2ª fase. Elimina a Uruguay.
- **Uruguay eliminado** en grupos (shock mayor).
- **Turquía eliminada** (dark horse): 62 remates sin gol.
- Otros out: Escocia, Irán, A. Saudita.

## 5. xG / suerte (CRÍTICO para el modelo)

**Sobre-rendimiento (suerte → riesgo de caída):**
- México +3.32 xPts (9 reales vs 5.68 esperados) — el más inflado (local + altura).
- Croacia +2.53 · Paraguay (resultados afortunados, no sostenibles).
- Alemania: 9 goles con 6.11 xG, "con suerte" vs C. Marfil.

**Genuinamente buenos:**
- **Francia**: 9 pts con números de elite (5° xG/remate, 20% conversión, 0.57 xG/90 concedidos). El más sólido. NO es suerte.
- **Inglaterra**: mejor perfil de ocasiones ante rivales fuertes.

**Sub-rendimiento (mala suerte, ya out):** Uruguay −3.05, Turquía −2.92, Panamá −2.27.

## 6. Modelos de predicción

**Opta Supercomputer** (Power Rankings ~Elo, 25K sims), top tras grupos:

| Equipo | Post-grupos | Pre-torneo |
|---|---|---|
| Francia | 18.7% | 13.0% ▲ |
| Argentina | 16.3% | — |
| España | 13.5% | era #1 ▼ |
| Inglaterra | 9.7% | — |
| Brasil | 6.5% | 6.6% = |
| P. Bajos | 5.1% | 3.6% ▲ |

- España cayó del trono (era 16.1% pre, #1) tras 0-0 con Cabo Verde.
- Francia subió fuerte (+5.7), favorito de los modelos.

**Nate Silver / PELE** (Substack, 200K sims KO): ajustes de roster, ventaja local elevada anfitriones, simula prórroga/penales. Tabla tras paywall.

**FiveThirtyEight (SPI) está MUERTO** — cerró 2023, plataforma discontinuada 2025. Heredero = natesilver.net.

## 7. Mercados vs modelos (value)

| Equipo | Mercados (Kalshi/Poly) | Opta | Lectura |
|---|---|---|---|
| Francia | 23-24% | 18.7% | Mercado sobrevalora |
| Argentina | 21.3% | 16.3% | Caliente por el cuadro |
| España | 10.6% | 13.5% | Opta ve value |

Casas: Francia +390/+413, España +550, Inglaterra +600.

## 8. Qué funciona (consenso analítico)

- **Diferencia de Elo = driver dominante** (~2 órdenes de magnitud sobre la siguiente variable). En comparativa de 10-11 modelos, XGBoost ganó por poco; el Elo hace casi todo.
- **Ensemble gana**: FIFA rank + Elo + forma + profundidad plantilla + odds agregadas.
- **Mercados de predicción ≈ o mejor** que supercomputadoras en calibración (sin estudio peer-reviewed que lo zanje — cuidado con claims de marketing).
- Base open-source: Elo + Dixon-Coles + Monte Carlo (GitHub Hicruben → cup26matches.com).

## 9. Implicaciones para la polla

1. Francia = favorito más "real" (números + modelos + sin suerte). Brasil plano.
2. Cuidado con México, Croacia, Paraguay, Alemania (inflados por suerte).
3. España posible value si la polla penaliza consenso.
4. Varianza alta → no clavar todos los favoritos; terceros/medianos tienen camino.
5. Modelo: Elo ~80% + xG-adjusted form + ajuste local/calor/viaje + Monte Carlo.

## Fuentes

- Opta Knockout: https://theanalyst.com/articles/world-cup-2026-knockout-stage-predictions-opta-supercomputer
- Yahoo R32 Bracket: https://sports.yahoo.com/soccer/article/world-cup-2026-round-of-32-full-bracket-matchups-schedule-and-how-each-team-qualified-164942403.html
- xG Quadrant (luck table): https://xgquadrant.com/
- Nate Silver / PELE: https://www.natesilver.net/p/world-cup-2026-odds-predictions
- Biggest Upsets (Yahoo): https://sports.yahoo.com/articles/the-biggest-upsets-of-world-cup-2026-so-far-125500104.html
- Market vs Supercomputer (KuCoin): https://www.kucoin.com/news/flash/how-2026-world-cup-win-probabilities-are-calculated-market-prices-vs-supercomputing-models
- 11 Models (Towards Data Science): https://towardsdatascience.com/i-built-11-models-to-predict-the-2026-world-cup-they-crown-four-different-champions/
- Open-source Elo+Dixon-Coles: https://github.com/Hicruben/world-cup-2026-prediction-model
- Al Jazeera R32: https://www.aljazeera.com/sports/2026/6/28/which-teams-have-qualified-for-the-world-cup-2026-knockouts-round-of-32
